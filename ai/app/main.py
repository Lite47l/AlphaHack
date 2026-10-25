"""AI-сервис: бизнес-контекст компаний, ранжирование, агент инсайтов, чат, трассировка (контракт docs/api_contract.md)."""
import hashlib
import json
import logging
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .agent import InsightAgent
from .bank import BankCorpus
from .chat import ChatService
from .config import settings
from .feed import FeedService
from .llm import LLMClient
from .profiles import ProfileStore
from .storage import make_store
from .writer import PROMPT_VERSION


class JsonFormatter(logging.Formatter):
    SKIP = set(vars(logging.LogRecord('', 0, '', 0, '', None, None))) | {'message', 'asctime'}

    def format(self, r):
        d = {'time': self.formatTime(r), 'level': r.levelname, 'logger': r.name, 'msg': r.getMessage()}
        d.update({k: v for k, v in vars(r).items() if k not in self.SKIP})
        if r.exc_info:
            d['exc'] = self.formatException(r.exc_info)
        return json.dumps(d, ensure_ascii=False, default=str)


h = logging.StreamHandler(sys.stdout)
h.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[h], force=True)
log = logging.getLogger('app')

S: dict = {}
ROLES = {'cfo', 'ceo', 'treasurer', 'accountant'}


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = make_store(settings)
    store.ensure_schema()
    profiles = ProfileStore.load()
    profiles.add_database_companies(store.list_companies())
    bank = BankCorpus.load()
    llm = LLMClient(settings, store)
    S.update(store=store, profiles=profiles, bank=bank, llm=llm, feed=FeedService(profiles, bank, store),
             agent=InsightAgent(profiles, bank, store, llm), chat=ChatService(profiles, bank, store, llm),
             pool=ThreadPoolExecutor(max_workers=4, thread_name_prefix='agent'), running=set(), lock=threading.Lock())
    log.info('ai service ready', extra={'profiles': len(profiles.profiles), 'data_source': profiles.source.split(':')[0],
                                        'corpus': bank.version, 'llm_enabled': llm.enabled})
    yield
    S['pool'].shutdown(wait=False, cancel_futures=True)


app = FastAPI(title='Alfa News Insights — AI service', version='1.0', lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse({'error': exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    field = '.'.join(str(x) for x in first.get('loc', [])[1:]) or 'request'
    return JSONResponse({'error': f'invalid {field}: {first.get("msg", "validation error")}'}, status_code=400)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception('unhandled error', extra={'path': request.url.path})
    return JSONResponse({'error': 'внутренняя ошибка AI-сервиса'}, status_code=500)


@app.middleware('http')
async def access_log(request: Request, call_next):
    t = time.monotonic()
    resp = await call_next(request)
    log.info('http request', extra={'request_id': request.headers.get('x-request-id'), 'method': request.method,
                                    'path': request.url.path, 'status': resp.status_code,
                                    'duration_ms': int((time.monotonic() - t) * 1000)})
    return resp


def _profile_or_404(cid: str):
    p = S['profiles'].get(cid)
    if not p:
        raise HTTPException(404, 'компания не найдена')
    return p


def _scope(company_id: str, client_id: str | None):
    """Граница доступа: инсайты и диалоги компании доступны только в контексте этой компании."""
    if not client_id:
        raise HTTPException(401, 'не указан контекст клиента (заголовок X-Client-Id)')
    if client_id != company_id:
        log.warning('access denied', extra={'company_id': company_id, 'client_id': client_id})
        raise HTTPException(403, 'нет доступа к данным другой компании')


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.get('/api/v1/system/status')
def system_status():
    p, b = S['profiles'], S['bank']
    return {'data_source': p.source.split(':')[0], 'profiles': len(p.profiles), 'profiles_version': p.version,
            'segment_min_revenue': settings.min_revenue, 'corpus_version': b.version, 'bank_documents': len(b.docs),
            'bank_fragments': len(b.chunks), 'news_in_db': S['store'].count_news(), 'llm': settings.public(),
            'llm_budget_left_today': S['llm'].budget_left() if S['llm'].enabled else None,
            'mode': 'llm' if S['llm'].enabled else 'rules', 'prompt_version': PROMPT_VERSION}


@app.get('/api/v1/companies')
def companies(query: str = '', limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    items, total = S['profiles'].search(query, limit, offset)
    return {'items': items, 'total': total, 'limit': limit, 'offset': offset,
            'data_source': S['profiles'].source.split(':')[0]}


@app.get('/api/v1/companies/{company_id}')
def company(company_id: str):
    p = _profile_or_404(company_id)
    return {'summary': S['profiles'].summary(p), 'observed': p['observed'], 'products': p['products'],
            'missing_fields': p['missing_fields'], 'profile_status': p['profile_status'], 'segment': p['segment'],
            'channels': sorted(p['channels'].values(), key=lambda c: -c['strength']), 'derived': p['derived'],
            'data_notes': p['data_notes']}


@app.get('/api/v1/companies/{company_id}/feed')
def feed(company_id: str, limit: int = Query(20, ge=1, le=100), days: int = Query(None, ge=1, le=365),
         include_filtered: bool = False):
    _profile_or_404(company_id)
    return S['feed'].feed(company_id, limit, days or settings.feed_window_days, include_filtered)


@app.get('/api/v1/relevance')
def relevance(news_id: str, company_ids: str):
    ids = [c.strip() for c in company_ids.split(',') if c.strip()]
    if not ids:
        raise HTTPException(400, 'invalid company_ids')
    r = S['feed'].relevance(news_id, ids)
    if r is None:
        raise HTTPException(404, 'новость не найдена')
    return r


class InsightRequest(BaseModel):
    company_id: str = Field(min_length=1, max_length=64)
    news_id: str = Field(min_length=1, max_length=64)
    role: str = 'cfo'
    force: bool = False


def _cache_key(company_id, news_id, role, news):
    raw = '|'.join([company_id, news_id, role, S['profiles'].version, S['bank'].version, PROMPT_VERSION,
                    'llm' if S['llm'].enabled else 'rules', hashlib.sha256((news['title'] + (news.get('summary') or '')
                                                                             + (news.get('content') or '')).encode()).hexdigest()[:12]])
    return hashlib.sha256(raw.encode()).hexdigest()


def _run_insight(insight_id, company_id, news_id, role, trace_id):
    store = S['store']
    last = [0.0]

    def on_update(trace):
        if time.monotonic() - last[0] > 0.3:
            last[0] = time.monotonic()
            store.update_insight(insight_id, progress=trace.progress(), status='processing')
    try:
        store.update_insight(insight_id, status='processing')
        result, trace = S['agent'].run(company_id, news_id, role, trace_id, on_update)
        store.save_trace(trace.trace_id, insight_id, 'insight', trace.steps, trace.summary(result['mode']))
        store.update_insight(insight_id, status='completed', result=result, mode=result['mode'], progress=trace.progress())
    except Exception as e:
        log.exception('insight failed', extra={'insight_id': insight_id, 'trace_id': trace_id})
        store.update_insight(insight_id, status='failed', error=f'Анализ не выполнен: {type(e).__name__}: {str(e)[:200]}')
    finally:
        with S['lock']:
            S['running'].discard(insight_id)


@app.post('/api/v1/insights', status_code=202)
def create_insight(req: InsightRequest, x_client_id: str | None = Header(None)):
    _profile_or_404(req.company_id)
    _scope(req.company_id, x_client_id)
    role = req.role if req.role in ROLES else 'cfo'
    news = S['store'].get_news(req.news_id)
    if not news:
        raise HTTPException(404, 'новость не найдена')
    key = _cache_key(req.company_id, req.news_id, role, news)
    if not req.force:
        found = S['store'].find_insight_by_key(key)
        if found:
            return {'insight_id': found['id'], 'status': found['status'], 'trace_id': found['trace_id'],
                    'cached': found['status'] == 'completed'}
    insight_id, trace_id = str(uuid.uuid4()), str(uuid.uuid4())
    S['store'].create_insight({'id': insight_id, 'cache_key': key, 'company_id': req.company_id, 'news_id': req.news_id,
                               'role': role, 'status': 'queued', 'trace_id': trace_id})
    with S['lock']:
        S['running'].add(insight_id)
    S['pool'].submit(_run_insight, insight_id, req.company_id, req.news_id, role, trace_id)
    return {'insight_id': insight_id, 'status': 'queued', 'trace_id': trace_id, 'cached': False}


def _insight_or_404(insight_id: str, client_id: str | None) -> dict:
    try:
        uuid.UUID(insight_id)
    except ValueError:
        raise HTTPException(400, 'invalid id: expected UUID')
    row = S['store'].get_insight(insight_id)
    if not row:
        raise HTTPException(404, 'инсайт не найден')
    _scope(row['company_id'], client_id)
    return row


@app.get('/api/v1/insights/{insight_id}')
def get_insight(insight_id: str, x_client_id: str | None = Header(None)):
    row = _insight_or_404(insight_id, x_client_id)
    status = row['status']
    if status in ('queued', 'processing') and insight_id not in S['running']:
        status = 'failed'  # процесс был прерван (например, перезапуск сервиса)
        row['error'] = row.get('error') or 'Анализ прерван — запустите повторно'
    return {'insight_id': row['id'], 'company_id': row['company_id'], 'news_id': row['news_id'], 'role': row['role'],
            'status': status, 'error': row.get('error') or None, 'trace_id': row['trace_id'],
            'created_at': row.get('created_at'), 'updated_at': row.get('updated_at'), 'progress': row.get('progress') or [],
            'result': row.get('result') if status == 'completed' else None}


@app.get('/api/v1/insights/{insight_id}/trace')
def get_trace(insight_id: str, x_client_id: str | None = Header(None)):
    row = _insight_or_404(insight_id, x_client_id)
    t = S['store'].get_trace(row['trace_id'])
    if not t:
        raise HTTPException(404, 'трассировка ещё не готова')
    return {'trace_id': row['trace_id'], 'insight_id': insight_id, 'kind': t.get('kind', 'insight'),
            'steps': t.get('steps', []), 'summary': t.get('summary', {})}


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


@app.get('/api/v1/insights/{insight_id}/chat')
def chat_history(insight_id: str, x_client_id: str | None = Header(None)):
    _insight_or_404(insight_id, x_client_id)
    return {'messages': [_msg(m) for m in S['store'].list_chat(insight_id)]}


def _msg(m):
    payload = m.get('payload') or {}
    return {'id': m['id'], 'role': m['role'], 'content': m['content'], 'statements': payload.get('statements', []),
            'sources': payload.get('sources', {}), 'mode': payload.get('mode'), 'trace_id': m.get('trace_id'),
            'created_at': m.get('created_at')}


@app.post('/api/v1/insights/{insight_id}/chat')
def chat(insight_id: str, req: ChatRequest, x_client_id: str | None = Header(None)):
    row = _insight_or_404(insight_id, x_client_id)
    if row['status'] != 'completed':
        raise HTTPException(409, 'инсайт ещё не готов')
    store = S['store']
    store.add_chat(insight_id, row['company_id'], 'user', req.question, {}, None)
    ans = S['chat'].answer(row, req.question)
    trace = ans.pop('trace')
    store.save_trace(trace.trace_id, insight_id, 'chat', trace.steps, trace.summary(ans['mode']))
    msg = store.add_chat(insight_id, row['company_id'], 'assistant', ans['content'],
                         {'statements': ans['statements'], 'sources': ans['sources'], 'mode': ans['mode']}, trace.trace_id)
    return {'message': _msg(msg), 'history': [_msg(m) for m in store.list_chat(insight_id)]}


class FeedbackRequest(BaseModel):
    rating: int = Field(ge=-1, le=1)
    reason: str = Field('', max_length=500)


@app.post('/api/v1/insights/{insight_id}/feedback')
def feedback(insight_id: str, req: FeedbackRequest, x_client_id: str | None = Header(None)):
    row = _insight_or_404(insight_id, x_client_id)
    S['store'].add_feedback(insight_id, row['company_id'], req.rating, req.reason)
    return {'ok': True}


@app.get('/api/v1/bank/documents')
def bank_documents():
    return {'items': S['bank'].documents(), 'corpus_version': S['bank'].version, 'extraction': S['bank'].extraction}


@app.get('/api/v1/bank/search')
def bank_search(q: str = Query(min_length=2, max_length=300), k: int = Query(5, ge=1, le=20)):
    return {'items': S['bank'].search(q, k=k, min_score=0.5)}


@app.get('/api/v1/metrics/summary')
def metrics():
    m = S['store'].metrics_summary()
    m['llm_enabled'] = S['llm'].enabled
    return m
