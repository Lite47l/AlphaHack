"""Хранилище AI-сервиса: PostgreSQL (PgStore) или память (MemoryStore).

Таблица `news` принадлежит Go-сервису — AI её только читает. Свои таблицы AI создаёт
с префиксом `ai_` в `ensure_schema()` и не трогает таблицы Go.

Все методы возвращают dict/list с JSON-сериализуемыми значениями: UUID → str,
даты → ISO 8601 (UTC), Decimal → float.
"""
from __future__ import annotations

import copy
import json
import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

log = logging.getLogger('app.storage')

INSIGHT_ACTIVE_STATUSES = ('completed', 'processing', 'queued')
INSIGHT_UPDATABLE = ('status', 'result', 'error', 'mode', 'progress', 'trace_id')
INSIGHT_JSON_FIELDS = ('result', 'progress')


# ---------------------------------------------------------------- helpers

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_utc() -> date:
    return _now().date()


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def _parse_dt(v: Any) -> datetime | None:
    """ISO-строка/datetime → aware datetime (UTC). Некорректное значение → None."""
    if v is None or v == '':
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        try:
            dt = datetime.fromisoformat(str(v).strip().replace('Z', '+00:00'))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _norm_value(v: Any) -> Any:
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (datetime, date)):
        return _iso(v)
    if isinstance(v, Decimal):
        return float(v)
    return v


def _norm_row(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {k: _norm_value(v) for k, v in row.items()}


def _json_dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


def _jsonable(v: Any) -> Any:
    """Глубокая копия через JSON — та же семантика, что у jsonb в PostgreSQL."""
    if v is None:
        return None
    return json.loads(_json_dumps(v))


def _valid_uuid(v: Any) -> str | None:
    if v is None:
        return None
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, AttributeError, TypeError):
        return None


def news_id_for_url(url: str) -> str:
    """Детерминированный id новости из снимка (uuid5 от url)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, url))


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


# ---------------------------------------------------------------- interface

class Store(ABC):
    """Единый интерфейс хранилища. Реализации потокобезопасны."""

    kind: str = 'abstract'

    @abstractmethod
    def ensure_schema(self) -> None: ...

    # новости (только чтение у Pg)
    @abstractmethod
    def list_news(self, since_iso: str | None = None, limit: int = 500) -> list[dict]: ...
    @abstractmethod
    def get_news(self, news_id: str) -> dict | None: ...
    @abstractmethod
    def count_news(self) -> int: ...
    @abstractmethod
    def add_news(self, item: dict) -> dict: ...

    # события новостей
    @abstractmethod
    def get_events(self, news_ids: list[str], extractor: str) -> dict[str, dict]: ...
    @abstractmethod
    def put_event(self, news_id: str, extractor: str, event: dict) -> None: ...

    # инсайты
    @abstractmethod
    def find_insight_by_key(self, cache_key: str) -> dict | None: ...
    @abstractmethod
    def create_insight(self, row: dict) -> None: ...
    @abstractmethod
    def update_insight(self, insight_id: str, **fields) -> None: ...
    @abstractmethod
    def get_insight(self, insight_id: str) -> dict | None: ...

    # трассировки
    @abstractmethod
    def save_trace(self, trace_id: str, insight_id: str | None, kind: str, steps: list, summary: dict) -> None: ...
    @abstractmethod
    def get_trace(self, trace_id: str) -> dict | None: ...

    # чат
    @abstractmethod
    def add_chat(self, insight_id: str, company_id: str, role: str, content: str,
                 payload: dict, trace_id: str | None) -> dict: ...
    @abstractmethod
    def list_chat(self, insight_id: str) -> list[dict]: ...

    # LLM
    @abstractmethod
    def usage_today(self) -> int: ...
    @abstractmethod
    def add_usage(self, model: str, prompt_tokens: int, completion_tokens: int) -> None: ...
    @abstractmethod
    def usage_summary(self, days: int = 7) -> list[dict]: ...
    @abstractmethod
    def cache_get(self, key: str) -> dict | None: ...
    @abstractmethod
    def cache_put(self, key: str, model: str, response: dict) -> None: ...

    # обратная связь и мониторинг
    @abstractmethod
    def add_feedback(self, insight_id: str, company_id: str, rating: int, reason: str) -> None: ...
    @abstractmethod
    def metrics_summary(self) -> dict: ...

    def close(self) -> None:  # pragma: no cover - по умолчанию нечего закрывать
        pass


def _check_insight_fields(fields: dict) -> None:
    unknown = set(fields) - set(INSIGHT_UPDATABLE)
    if unknown:
        raise ValueError(f'update_insight: unknown fields {sorted(unknown)}')


# ---------------------------------------------------------------- memory

class MemoryStore(Store):
    """Хранилище в памяти: для тестов и запуска без БД. Та же семантика, что у PgStore."""

    kind = 'memory'

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._news: dict[str, dict] = {}
        self._news_by_url: dict[str, str] = {}
        self._events: dict[tuple[str, str], dict] = {}
        self._insights: dict[str, dict] = {}
        self._traces: dict[str, dict] = {}
        self._chat: list[dict] = []
        self._chat_seq = 0
        self._usage: dict[tuple[str, str], dict] = {}
        self._cache: dict[str, dict] = {}
        self._feedback: list[dict] = []
        self._feedback_seq = 0

    def ensure_schema(self) -> None:
        return None

    # ----- news
    @staticmethod
    def _news_public(n: dict) -> dict:
        return {k: n[k] for k in ('id', 'title', 'summary', 'content', 'url', 'source_name',
                                  'published_at', 'fetched_at', 'origin')}

    @staticmethod
    def _news_sort_dt(n: dict) -> datetime:
        return _parse_dt(n['published_at']) or _parse_dt(n['_created_at']) or datetime.min.replace(tzinfo=timezone.utc)

    def add_news(self, item: dict) -> dict:
        url = str(item.get('url') or '').strip()
        title = str(item.get('title') or '').strip()
        if not url and not title:
            raise ValueError('add_news: url or title required')
        with self._lock:
            if url and url in self._news_by_url:
                return self._news_public(self._news[self._news_by_url[url]])
            nid = _valid_uuid(item.get('id')) or news_id_for_url(url or f'title:{title}')
            created = _now()
            pub = _parse_dt(item.get('published_at'))
            fetched = _parse_dt(item.get('fetched_at')) or created
            n = {
                'id': nid,
                'title': title,
                'summary': str(item.get('summary') or ''),
                'content': str(item.get('content') or ''),
                'url': url,
                'source_name': str(item.get('source_name') or ''),
                # как COALESCE(published_at, created_at) в PgStore
                'published_at': _iso(pub or created),
                'fetched_at': _iso(fetched),
                'origin': str(item.get('origin') or 'collector'),
                '_created_at': _iso(created),
            }
            self._news[nid] = n
            if url:
                self._news_by_url[url] = nid
            return self._news_public(n)

    def load_snapshot(self, path: Path) -> int:
        """Загрузить data/news_snapshot.json (формат из docs/api_contract.md). Возвращает число новостей."""
        try:
            raw = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError) as e:
            log.warning('news snapshot not loaded: %s', e)
            return 0
        items = raw.get('items', []) if isinstance(raw, dict) else raw
        fetched = raw.get('generated_at') if isinstance(raw, dict) else None
        n = 0
        for it in items or []:
            if not isinstance(it, dict) or not it.get('url'):
                continue
            try:
                self.add_news({**it, 'origin': it.get('origin') or 'snapshot',
                               'fetched_at': it.get('fetched_at') or fetched})
                n += 1
            except ValueError:
                continue
        return n

    def list_news(self, since_iso: str | None = None, limit: int = 500) -> list[dict]:
        since = _parse_dt(since_iso)
        with self._lock:
            items = list(self._news.values())
        if since is not None:
            items = [n for n in items if self._news_sort_dt(n) >= since]
        items.sort(key=self._news_sort_dt, reverse=True)
        return [self._news_public(n) for n in items[:max(0, int(limit))]]

    def get_news(self, news_id: str) -> dict | None:
        nid = _valid_uuid(news_id)
        if nid is None:
            return None
        with self._lock:
            n = self._news.get(nid)
            return self._news_public(n) if n else None

    def count_news(self) -> int:
        with self._lock:
            return len(self._news)

    # ----- events
    def get_events(self, news_ids: list[str], extractor: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        with self._lock:
            for raw_id in news_ids:
                nid = _valid_uuid(raw_id)
                if nid and (nid, extractor) in self._events:
                    out[nid] = copy.deepcopy(self._events[(nid, extractor)])
        return out

    def put_event(self, news_id: str, extractor: str, event: dict) -> None:
        nid = _valid_uuid(news_id)
        if nid is None:
            raise ValueError(f'invalid news_id: {news_id!r}')
        with self._lock:
            self._events[(nid, extractor)] = _jsonable(event)

    # ----- insights
    def find_insight_by_key(self, cache_key: str) -> dict | None:
        with self._lock:
            rows = [r for r in self._insights.values()
                    if r['cache_key'] == cache_key and r['status'] in INSIGHT_ACTIVE_STATUSES]
            if not rows:
                return None
            rows.sort(key=lambda r: (r['created_at'], r['_seq']), reverse=True)
            return self._insight_public(rows[0])

    def create_insight(self, row: dict) -> None:
        iid = _valid_uuid(row.get('id'))
        if iid is None:
            raise ValueError('create_insight: valid uuid id required')
        now = _iso(_now())
        with self._lock:
            if iid in self._insights:
                raise ValueError(f'insight {iid} already exists')
            self._insights[iid] = {
                'id': iid,
                'cache_key': row.get('cache_key'),
                'company_id': row.get('company_id'),
                'news_id': _valid_uuid(row.get('news_id')),
                'role': row.get('role'),
                'status': row.get('status') or 'queued',
                'mode': row.get('mode'),
                'result': _jsonable(row.get('result')),
                'error': row.get('error'),
                'progress': _jsonable(row.get('progress')) or [],
                'trace_id': _valid_uuid(row.get('trace_id')),
                'created_at': now,
                'updated_at': now,
                '_seq': len(self._insights),
            }

    def update_insight(self, insight_id: str, **fields) -> None:
        _check_insight_fields(fields)
        iid = _valid_uuid(insight_id)
        with self._lock:
            r = self._insights.get(iid) if iid else None
            if r is None:
                return
            for k, v in fields.items():
                if k in INSIGHT_JSON_FIELDS:
                    v = _jsonable(v)
                elif k == 'trace_id':
                    v = _valid_uuid(v)
                r[k] = v
            r['updated_at'] = _iso(_now())

    @staticmethod
    def _insight_public(r: dict) -> dict:
        return copy.deepcopy({k: v for k, v in r.items() if not k.startswith('_')})

    def get_insight(self, insight_id: str) -> dict | None:
        iid = _valid_uuid(insight_id)
        with self._lock:
            r = self._insights.get(iid) if iid else None
            return self._insight_public(r) if r else None

    # ----- traces
    def save_trace(self, trace_id: str, insight_id: str | None, kind: str, steps: list, summary: dict) -> None:
        tid = _valid_uuid(trace_id)
        if tid is None:
            raise ValueError(f'invalid trace_id: {trace_id!r}')
        now = _iso(_now())
        with self._lock:
            prev = self._traces.get(tid)
            self._traces[tid] = {
                'trace_id': tid,
                'insight_id': _valid_uuid(insight_id),
                'kind': kind,
                'steps': _jsonable(steps) or [],
                'summary': _jsonable(summary) or {},
                'created_at': prev['created_at'] if prev else now,
                'updated_at': now,
            }

    def get_trace(self, trace_id: str) -> dict | None:
        tid = _valid_uuid(trace_id)
        with self._lock:
            t = self._traces.get(tid) if tid else None
            return copy.deepcopy(t) if t else None

    # ----- chat
    def add_chat(self, insight_id: str, company_id: str, role: str, content: str,
                 payload: dict, trace_id: str | None) -> dict:
        iid = _valid_uuid(insight_id)
        if iid is None:
            raise ValueError(f'invalid insight_id: {insight_id!r}')
        with self._lock:
            self._chat_seq += 1
            msg = {
                'id': self._chat_seq,
                'insight_id': iid,
                'company_id': company_id,
                'role': role,
                'content': content,
                'payload': _jsonable(payload) or {},
                'trace_id': _valid_uuid(trace_id),
                'created_at': _iso(_now()),
            }
            self._chat.append(msg)
            return {k: copy.deepcopy(v) for k, v in msg.items() if k != 'company_id'}

    def list_chat(self, insight_id: str) -> list[dict]:
        iid = _valid_uuid(insight_id)
        if iid is None:
            return []
        with self._lock:
            return [{k: copy.deepcopy(v) for k, v in m.items() if k != 'company_id'}
                    for m in self._chat if m['insight_id'] == iid]

    # ----- LLM usage / cache
    def usage_today(self) -> int:
        day = _today_utc().isoformat()
        with self._lock:
            return sum(u['prompt_tokens'] + u['completion_tokens']
                       for (d, _m), u in self._usage.items() if d == day)

    def add_usage(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        key = (_today_utc().isoformat(), model)
        with self._lock:
            u = self._usage.setdefault(key, {'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0})
            u['calls'] += 1
            u['prompt_tokens'] += int(prompt_tokens or 0)
            u['completion_tokens'] += int(completion_tokens or 0)

    def usage_summary(self, days: int = 7) -> list[dict]:
        start = (_today_utc() - timedelta(days=max(1, int(days)) - 1)).isoformat()
        with self._lock:
            rows = [{'day': d, 'model': m, **u} for (d, m), u in self._usage.items() if d >= start]
        rows.sort(key=lambda r: (r['day'], r['model']))
        rows.sort(key=lambda r: r['day'], reverse=True)
        return copy.deepcopy(rows)

    def cache_get(self, key: str) -> dict | None:
        with self._lock:
            c = self._cache.get(key)
            return copy.deepcopy(c['response']) if c else None

    def cache_put(self, key: str, model: str, response: dict) -> None:
        with self._lock:
            self._cache[key] = {'model': model, 'response': _jsonable(response), 'created_at': _iso(_now())}

    # ----- feedback / metrics
    def add_feedback(self, insight_id: str, company_id: str, rating: int, reason: str) -> None:
        with self._lock:
            self._feedback_seq += 1
            self._feedback.append({'id': self._feedback_seq, 'insight_id': _valid_uuid(insight_id),
                                   'company_id': company_id, 'rating': int(rating),
                                   'reason': reason or '', 'created_at': _iso(_now())})

    def metrics_summary(self) -> dict:
        with self._lock:
            insights = copy.deepcopy(list(self._insights.values()))
            traces = copy.deepcopy(list(self._traces.values()))
            chat_n = len(self._chat)
            fb = [f['rating'] for f in self._feedback]
            cache_n = len(self._cache)
        day = _today_utc().isoformat()
        with self._lock:
            today = [u for (d, _m), u in self._usage.items() if d == day]
        tokens_today = sum(u['prompt_tokens'] + u['completion_tokens'] for u in today)
        calls_today = sum(u['calls'] for u in today)

        by_status = Counter(r['status'] for r in insights)
        def _mode(r: dict) -> str | None:
            res = r.get('result')
            return r.get('mode') or (res.get('mode') if isinstance(res, dict) else None)

        by_mode = Counter(m for m in map(_mode, insights) if m)
        completed = [r['result'] for r in insights if r['status'] == 'completed' and isinstance(r.get('result'), dict)]
        v_pass = [str((res.get('validation') or {}).get('passed')).lower() == 'true'
                  for res in completed if isinstance(res.get('validation'), dict)
                  and res['validation'].get('passed') is not None]
        bank = [(res.get('bank_view') or {}).get('status') for res in completed
                if isinstance(res.get('bank_view'), dict) and res['bank_view'].get('status')]
        repairs = [res['validation']['repairs'] for res in completed
                   if isinstance(res.get('validation'), dict)
                   and isinstance(res['validation'].get('repairs'), (int, float))
                   and not isinstance(res['validation'].get('repairs'), bool)]

        def _dur(kind: str) -> int | None:
            vals = [t['summary']['duration_ms'] for t in traces
                    if t['kind'] == kind and isinstance(t.get('summary'), dict)
                    and isinstance(t['summary'].get('duration_ms'), (int, float))
                    and not isinstance(t['summary'].get('duration_ms'), bool)]
            return int(round(sum(vals) / len(vals))) if vals else None

        return {
            'insights_total': len(insights),
            'by_status': dict(by_status),
            'by_mode': dict(by_mode),
            'validation_pass_rate': _rate(sum(v_pass), len(v_pass)),
            'bank_view_found_rate': _rate(sum(1 for s in bank if s == 'found'), len(bank)),
            'avg_duration_ms': _dur('insight'),
            'avg_chat_duration_ms': _dur('chat'),
            'avg_repairs': round(sum(repairs) / len(repairs), 4) if repairs else None,
            'chat_messages': chat_n,
            'feedback': {'up': sum(1 for r in fb if r > 0), 'down': sum(1 for r in fb if r < 0)},
            'llm_tokens_today': tokens_today,
            'llm_calls_today': calls_today,
            'cache_entries': cache_n,
        }


# ---------------------------------------------------------------- postgres

_SCHEMA_SQL = [
    """CREATE TABLE IF NOT EXISTS ai_news_events (
        news_id UUID NOT NULL,
        extractor TEXT NOT NULL,
        event JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (news_id, extractor)
    )""",
    """CREATE TABLE IF NOT EXISTS ai_insights (
        id UUID PRIMARY KEY,
        cache_key TEXT NOT NULL,
        company_id TEXT NOT NULL,
        news_id UUID,
        role TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        mode TEXT,
        result JSONB,
        error TEXT,
        progress JSONB NOT NULL DEFAULT '[]'::jsonb,
        trace_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ai_insights_cache_key ON ai_insights (cache_key, created_at DESC)",
    """CREATE TABLE IF NOT EXISTS ai_traces (
        trace_id UUID PRIMARY KEY,
        insight_id UUID,
        kind TEXT NOT NULL,
        steps JSONB NOT NULL DEFAULT '[]'::jsonb,
        summary JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ai_traces_insight ON ai_traces (insight_id)",
    """CREATE TABLE IF NOT EXISTS ai_chat_messages (
        id BIGSERIAL PRIMARY KEY,
        insight_id UUID NOT NULL,
        company_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL DEFAULT '',
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        trace_id UUID,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ai_chat_insight ON ai_chat_messages (insight_id, id)",
    """CREATE TABLE IF NOT EXISTS ai_llm_usage (
        day DATE NOT NULL,
        model TEXT NOT NULL,
        calls INTEGER NOT NULL DEFAULT 0,
        prompt_tokens BIGINT NOT NULL DEFAULT 0,
        completion_tokens BIGINT NOT NULL DEFAULT 0,
        PRIMARY KEY (day, model)
    )""",
    """CREATE TABLE IF NOT EXISTS ai_llm_cache (
        key TEXT PRIMARY KEY,
        model TEXT NOT NULL,
        response JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS ai_feedback (
        id BIGSERIAL PRIMARY KEY,
        insight_id UUID,
        company_id TEXT NOT NULL DEFAULT '',
        rating SMALLINT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS idx_ai_feedback_insight ON ai_feedback (insight_id)",
]

_TODAY_UTC_SQL = "(now() AT TIME ZONE 'UTC')::date"
_NEWS_OPTIONAL = ('content', 'origin', 'fetched_at')
_NEWS_COLS_RECHECK_S = 60.0


class PgStore(Store):
    """PostgreSQL через psycopg 3 + пул соединений (autocommit, dict_row, TimeZone=UTC)."""

    kind = 'postgres'

    def __init__(self, database_url: str, *, min_size: int = 1, max_size: int = 8,
                 wait_timeout: float = 60.0) -> None:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        def _configure(conn) -> None:
            conn.execute("SET TIME ZONE 'UTC'")

        self._pool = ConnectionPool(
            database_url, min_size=min_size, max_size=max_size, open=False,
            kwargs={'autocommit': True, 'row_factory': dict_row},
            configure=_configure, check=ConnectionPool.check_connection, name='ai-store',
        )
        self._pool.open(wait=False)
        try:
            self._pool.wait(timeout=wait_timeout)
        except Exception as e:  # PoolTimeout
            self._pool.close()
            raise RuntimeError(f'PostgreSQL недоступен за {wait_timeout:.0f} с: {type(e).__name__}') from e
        self._cols_lock = threading.Lock()
        self._news_cols: set[str] | None = None
        self._news_cols_checked = 0.0

    def close(self) -> None:
        self._pool.close()

    # ----- low-level
    def _all(self, sql: str, params: Any = None) -> list[dict]:
        with self._pool.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_norm_row(r) for r in rows]

    def _one(self, sql: str, params: Any = None) -> dict | None:
        with self._pool.connection() as conn:
            row = conn.execute(sql, params).fetchone()
        return _norm_row(row)

    def _exec(self, sql: str, params: Any = None) -> None:
        with self._pool.connection() as conn:
            conn.execute(sql, params)

    @staticmethod
    def _jsonb(v: Any):
        from psycopg.types.json import Jsonb
        return Jsonb(v, dumps=_json_dumps)

    def ensure_schema(self) -> None:
        with self._pool.connection() as conn:
            with conn.transaction():
                # сериализуем параллельные старты нескольких реплик
                conn.execute("SELECT pg_advisory_xact_lock(hashtext('ai_ensure_schema'))")
                for stmt in _SCHEMA_SQL:
                    conn.execute(stmt)

    # ----- news (read-only; таблицы news/sources принадлежат Go)
    def _news_columns(self) -> set[str] | None:
        """Колонки news. None — таблицы ещё нет. Неполный набор перепроверяется раз в минуту."""
        with self._cols_lock:
            cols = self._news_cols
            fresh = cols is not None and (
                all(c in cols for c in _NEWS_OPTIONAL)
                or time.monotonic() - self._news_cols_checked < _NEWS_COLS_RECHECK_S)
            if fresh:
                return cols
            rows = self._all(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'news' AND table_schema = ANY(current_schemas(false))")
            found = {r['column_name'] for r in rows}
            if not found:
                return None
            self._news_cols = found
            self._news_cols_checked = time.monotonic()
            return found

    def _news_select(self, cols: set[str]) -> str:
        content = "COALESCE(n.content, '')" if 'content' in cols else "''::text"
        origin = "COALESCE(NULLIF(n.origin, ''), 'collector')" if 'origin' in cols else "'collector'::text"
        fetched = 'COALESCE(n.fetched_at, n.created_at)' if 'fetched_at' in cols else 'n.created_at'
        return (
            "SELECT n.id, n.title, COALESCE(n.summary, '') AS summary, "
            f"{content} AS content, n.url, COALESCE(s.name, '') AS source_name, "
            "COALESCE(n.published_at, n.created_at) AS published_at, "
            f"{fetched} AS fetched_at, {origin} AS origin "
            "FROM news n LEFT JOIN sources s ON s.id = n.source_id"
        )

    def list_news(self, since_iso: str | None = None, limit: int = 500) -> list[dict]:
        cols = self._news_columns()
        if cols is None:
            return []
        sql = self._news_select(cols)
        params: list[Any] = []
        since = _parse_dt(since_iso)
        if since is not None:
            sql += ' WHERE COALESCE(n.published_at, n.created_at) >= %s'
            params.append(since)
        sql += ' ORDER BY COALESCE(n.published_at, n.created_at) DESC, n.id LIMIT %s'
        params.append(max(0, int(limit)))
        return self._all(sql, params)

    def get_news(self, news_id: str) -> dict | None:
        nid = _valid_uuid(news_id)
        cols = self._news_columns() if nid else None
        if cols is None:
            return None
        return self._one(self._news_select(cols) + ' WHERE n.id = %s', (nid,))

    def count_news(self) -> int:
        if self._news_columns() is None:
            return 0
        row = self._one('SELECT count(*) AS n FROM news')
        return int(row['n']) if row else 0

    def add_news(self, item: dict) -> dict:
        raise NotImplementedError('PgStore: таблица news принадлежит Go-сервису, AI только читает')

    # ----- events
    def get_events(self, news_ids: list[str], extractor: str) -> dict[str, dict]:
        ids = [i for i in (_valid_uuid(x) for x in news_ids) if i]
        if not ids:
            return {}
        rows = self._all('SELECT news_id, event FROM ai_news_events '
                         'WHERE extractor = %s AND news_id = ANY(%s::uuid[])', (extractor, ids))
        return {r['news_id']: r['event'] for r in rows}

    def put_event(self, news_id: str, extractor: str, event: dict) -> None:
        nid = _valid_uuid(news_id)
        if nid is None:
            raise ValueError(f'invalid news_id: {news_id!r}')
        self._exec(
            'INSERT INTO ai_news_events (news_id, extractor, event) VALUES (%s, %s, %s) '
            'ON CONFLICT (news_id, extractor) DO UPDATE SET event = EXCLUDED.event, created_at = now()',
            (nid, extractor, self._jsonb(event)))

    # ----- insights
    _INSIGHT_COLS = ('id, cache_key, company_id, news_id, role, status, mode, result, error, '
                     'progress, trace_id, created_at, updated_at')

    def find_insight_by_key(self, cache_key: str) -> dict | None:
        return self._one(
            f'SELECT {self._INSIGHT_COLS} FROM ai_insights WHERE cache_key = %s AND status = ANY(%s) '
            'ORDER BY created_at DESC LIMIT 1', (cache_key, list(INSIGHT_ACTIVE_STATUSES)))

    def create_insight(self, row: dict) -> None:
        iid = _valid_uuid(row.get('id'))
        if iid is None:
            raise ValueError('create_insight: valid uuid id required')
        self._exec(
            'INSERT INTO ai_insights (id, cache_key, company_id, news_id, role, status, mode, result, '
            'error, progress, trace_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
            (iid, row.get('cache_key'), row.get('company_id'), _valid_uuid(row.get('news_id')),
             row.get('role') or '', row.get('status') or 'queued', row.get('mode'),
             self._jsonb(row['result']) if row.get('result') is not None else None,
             row.get('error'), self._jsonb(row.get('progress') or []), _valid_uuid(row.get('trace_id'))))

    def update_insight(self, insight_id: str, **fields) -> None:
        _check_insight_fields(fields)
        iid = _valid_uuid(insight_id)
        if iid is None or not fields:
            return
        sets, params = [], []
        for k, v in fields.items():  # имена колонок — только из белого списка
            if k in INSIGHT_JSON_FIELDS:
                v = self._jsonb(v) if v is not None else (self._jsonb([]) if k == 'progress' else None)
            elif k == 'trace_id':
                v = _valid_uuid(v)
            sets.append(f'{k} = %s')
            params.append(v)
        sets.append('updated_at = now()')
        params.append(iid)
        self._exec(f"UPDATE ai_insights SET {', '.join(sets)} WHERE id = %s", params)

    def get_insight(self, insight_id: str) -> dict | None:
        iid = _valid_uuid(insight_id)
        if iid is None:
            return None
        return self._one(f'SELECT {self._INSIGHT_COLS} FROM ai_insights WHERE id = %s', (iid,))

    # ----- traces
    def save_trace(self, trace_id: str, insight_id: str | None, kind: str, steps: list, summary: dict) -> None:
        tid = _valid_uuid(trace_id)
        if tid is None:
            raise ValueError(f'invalid trace_id: {trace_id!r}')
        self._exec(
            'INSERT INTO ai_traces (trace_id, insight_id, kind, steps, summary) VALUES (%s, %s, %s, %s, %s) '
            'ON CONFLICT (trace_id) DO UPDATE SET insight_id = EXCLUDED.insight_id, kind = EXCLUDED.kind, '
            'steps = EXCLUDED.steps, summary = EXCLUDED.summary, updated_at = now()',
            (tid, _valid_uuid(insight_id), kind, self._jsonb(steps or []), self._jsonb(summary or {})))

    def get_trace(self, trace_id: str) -> dict | None:
        tid = _valid_uuid(trace_id)
        if tid is None:
            return None
        return self._one('SELECT trace_id, insight_id, kind, steps, summary, created_at, updated_at '
                         'FROM ai_traces WHERE trace_id = %s', (tid,))

    # ----- chat
    def add_chat(self, insight_id: str, company_id: str, role: str, content: str,
                 payload: dict, trace_id: str | None) -> dict:
        iid = _valid_uuid(insight_id)
        if iid is None:
            raise ValueError(f'invalid insight_id: {insight_id!r}')
        return self._one(
            'INSERT INTO ai_chat_messages (insight_id, company_id, role, content, payload, trace_id) '
            'VALUES (%s, %s, %s, %s, %s, %s) '
            'RETURNING id, insight_id, role, content, payload, trace_id, created_at',
            (iid, company_id, role, content or '', self._jsonb(payload or {}), _valid_uuid(trace_id)))

    def list_chat(self, insight_id: str) -> list[dict]:
        iid = _valid_uuid(insight_id)
        if iid is None:
            return []
        return self._all('SELECT id, insight_id, role, content, payload, trace_id, created_at '
                         'FROM ai_chat_messages WHERE insight_id = %s ORDER BY id', (iid,))

    # ----- LLM usage / cache
    def usage_today(self) -> int:
        row = self._one('SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS n '
                        f'FROM ai_llm_usage WHERE day = {_TODAY_UTC_SQL}')
        return int(row['n']) if row else 0

    def add_usage(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        self._exec(
            'INSERT INTO ai_llm_usage (day, model, calls, prompt_tokens, completion_tokens) '
            f'VALUES ({_TODAY_UTC_SQL}, %s, 1, %s, %s) '
            'ON CONFLICT (day, model) DO UPDATE SET calls = ai_llm_usage.calls + 1, '
            'prompt_tokens = ai_llm_usage.prompt_tokens + EXCLUDED.prompt_tokens, '
            'completion_tokens = ai_llm_usage.completion_tokens + EXCLUDED.completion_tokens',
            (model, int(prompt_tokens or 0), int(completion_tokens or 0)))

    def usage_summary(self, days: int = 7) -> list[dict]:
        rows = self._all(
            'SELECT day, model, calls, prompt_tokens, completion_tokens FROM ai_llm_usage '
            f'WHERE day > {_TODAY_UTC_SQL} - %s::int ORDER BY day DESC, model', (max(1, int(days)),))
        for r in rows:
            for k in ('calls', 'prompt_tokens', 'completion_tokens'):
                r[k] = int(r[k])
        return rows

    def cache_get(self, key: str) -> dict | None:
        row = self._one('SELECT response FROM ai_llm_cache WHERE key = %s', (key,))
        return row['response'] if row else None

    def cache_put(self, key: str, model: str, response: dict) -> None:
        self._exec(
            'INSERT INTO ai_llm_cache (key, model, response) VALUES (%s, %s, %s) '
            'ON CONFLICT (key) DO UPDATE SET model = EXCLUDED.model, response = EXCLUDED.response, '
            'created_at = now()', (key, model, self._jsonb(response)))

    # ----- feedback / metrics
    def add_feedback(self, insight_id: str, company_id: str, rating: int, reason: str) -> None:
        self._exec('INSERT INTO ai_feedback (insight_id, company_id, rating, reason) VALUES (%s, %s, %s, %s)',
                   (_valid_uuid(insight_id), company_id or '', int(rating), reason or ''))

    def metrics_summary(self) -> dict:
        by_status = {r['status']: int(r['n']) for r in self._all(
            'SELECT status, count(*) AS n FROM ai_insights GROUP BY status')}
        by_mode = {r['m']: int(r['n']) for r in self._all(
            "SELECT COALESCE(mode, result->>'mode') AS m, count(*) AS n FROM ai_insights "
            "WHERE COALESCE(mode, result->>'mode') IS NOT NULL GROUP BY 1")}
        q = self._one(
            "SELECT "
            "count(*) FILTER (WHERE jsonb_typeof(result->'validation'->'passed') IS NOT NULL "
            "                 AND jsonb_typeof(result->'validation'->'passed') <> 'null') AS v_total, "
            "count(*) FILTER (WHERE result->'validation'->>'passed' = 'true') AS v_pass, "
            "count(*) FILTER (WHERE COALESCE(result->'bank_view'->>'status', '') <> '') AS b_total, "
            "count(*) FILTER (WHERE result->'bank_view'->>'status' = 'found') AS b_found, "
            "avg(CASE WHEN jsonb_typeof(result->'validation'->'repairs') = 'number' "
            "         THEN (result->'validation'->>'repairs')::float END) AS avg_repairs "
            "FROM ai_insights WHERE status = 'completed' AND jsonb_typeof(result) = 'object'") or {}
        durs = {r['kind']: r['d'] for r in self._all(
            "SELECT kind, avg((summary->>'duration_ms')::float) AS d FROM ai_traces "
            "WHERE jsonb_typeof(summary->'duration_ms') = 'number' GROUP BY kind")}
        chat = self._one('SELECT count(*) AS n FROM ai_chat_messages') or {'n': 0}
        fb = self._one('SELECT count(*) FILTER (WHERE rating > 0) AS up, '
                       'count(*) FILTER (WHERE rating < 0) AS down FROM ai_feedback') or {}
        usage = self._one('SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS t, '
                          f'COALESCE(SUM(calls), 0) AS c FROM ai_llm_usage WHERE day = {_TODAY_UTC_SQL}') or {}
        cache = self._one('SELECT count(*) AS n FROM ai_llm_cache') or {'n': 0}

        def _int_or_none(v):
            return int(round(v)) if v is not None else None

        return {
            'insights_total': sum(by_status.values()),
            'by_status': by_status,
            'by_mode': by_mode,
            'validation_pass_rate': _rate(int(q.get('v_pass') or 0), int(q.get('v_total') or 0)),
            'bank_view_found_rate': _rate(int(q.get('b_found') or 0), int(q.get('b_total') or 0)),
            'avg_duration_ms': _int_or_none(durs.get('insight')),
            'avg_chat_duration_ms': _int_or_none(durs.get('chat')),
            'avg_repairs': round(q['avg_repairs'], 4) if q.get('avg_repairs') is not None else None,
            'chat_messages': int(chat['n']),
            'feedback': {'up': int(fb.get('up') or 0), 'down': int(fb.get('down') or 0)},
            'llm_tokens_today': int(usage.get('t') or 0),
            'llm_calls_today': int(usage.get('c') or 0),
            'cache_entries': int(cache['n']),
        }


# ---------------------------------------------------------------- factory

def make_store(settings) -> Store:
    """PgStore, если задан DATABASE_URL (ждём БД до ~60 с), иначе MemoryStore со снимком новостей.

    Схема AI-таблиц создаётся сразу (ensure_schema идемпотентен).
    """
    if getattr(settings, 'database_url', ''):
        store: Store = PgStore(settings.database_url, wait_timeout=60.0)
        store.ensure_schema()
        log.info('store: postgres')
        return store
    store = MemoryStore()
    snap = Path(settings.data_dir) / 'news_snapshot.json'
    if snap.is_file():
        n = store.load_snapshot(snap)
        log.info('store: memory, news snapshot loaded: %d items', n)
    else:
        log.info('store: memory, no news snapshot at %s', snap)
    return store
