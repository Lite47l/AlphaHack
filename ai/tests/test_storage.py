"""Тесты хранилища: MemoryStore всегда; PgStore — при заданном TEST_DATABASE_URL.

Пример запуска PgStore:
    docker run -d --rm --name ai-test-pg -e POSTGRES_PASSWORD=pg -p 55432:5432 postgres:17-alpine
    TEST_DATABASE_URL=postgresql://postgres:pg@127.0.0.1:55432/postgres python -m pytest -q
ВНИМАНИЕ: тест пересоздаёт таблицы sources/news/ai_* в этой БД — используйте только временную базу.
"""
import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import storage
from app.storage import MemoryStore, PgStore, Store, make_store, news_id_for_url

PG_URL = os.environ.get('TEST_DATABASE_URL', '').strip()

GO_NEWS_SQL = """
DROP TABLE IF EXISTS ai_news_events, ai_insights, ai_traces, ai_chat_messages, ai_llm_usage,
    ai_llm_cache, ai_feedback, news, sources CASCADE;
CREATE TABLE sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    base_url TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX idx_sources_name_unique ON sources (name);
CREATE TABLE news (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (url)
);
"""

NOW = datetime.now(timezone.utc).replace(microsecond=0)
NEWS = [
    {'title': 'Ставка 14%', 'summary': 'ЦБ сохранил ставку', 'url': 'https://cbr.ru/a',
     'source_name': 'Банк России', 'published_at': (NOW - timedelta(days=1)).isoformat()},
    {'title': 'Рубль укрепился', 'summary': 'Курс', 'url': 'https://rbc.ru/b',
     'source_name': 'РБК', 'published_at': (NOW - timedelta(days=10)).isoformat()},
    {'title': 'Свежая без даты', 'summary': '', 'url': 'https://rbc.ru/c',
     'source_name': 'РБК', 'published_at': None},
]


def _pg_exec(sql: str, params=None):
    import psycopg
    with psycopg.connect(PG_URL, autocommit=True) as conn:
        conn.execute(sql, params)


def _pg_seed_news(items, with_go_columns=False):
    import psycopg
    with psycopg.connect(PG_URL, autocommit=True) as conn:
        if with_go_columns:
            conn.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS content TEXT NOT NULL DEFAULT '', "
                         "ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'collector', "
                         "ADD COLUMN IF NOT EXISTS fetched_at TIMESTAMPTZ")
        ids = []
        for it in items:
            src = conn.execute(
                'INSERT INTO sources (name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name '
                'RETURNING id', (it['source_name'],)).fetchone()[0]
            nid = news_id_for_url(it['url'])
            conn.execute('INSERT INTO news (id, source_id, title, summary, url, published_at) '
                         'VALUES (%s, %s, %s, %s, %s, %s)',
                         (nid, src, it['title'], it['summary'], it['url'], it['published_at']))
            if with_go_columns and it.get('content'):
                conn.execute('UPDATE news SET content = %s, origin = %s WHERE id = %s',
                             (it['content'], it.get('origin', 'collector'), nid))
            ids.append(nid)
        return ids


@pytest.fixture(params=['memory', 'pg'])
def store(request):
    if request.param == 'memory':
        s = MemoryStore()
        s.ensure_schema()
        s.seed = lambda items: [s.add_news(i)['id'] for i in items]
        yield s
        return
    if not PG_URL:
        pytest.skip('TEST_DATABASE_URL не задан')
    _pg_exec(GO_NEWS_SQL)
    s = PgStore(PG_URL, wait_timeout=20)
    s.ensure_schema()
    s.ensure_schema()  # идемпотентно
    s.seed = _pg_seed_news
    yield s
    s.close()


def _json_roundtrip(v):
    assert json.loads(json.dumps(v)) == v
    return v


# ---------------------------------------------------------------- news

def test_news_read(store: Store):
    ids = store.seed(NEWS)
    assert store.count_news() == 3
    items = _json_roundtrip(store.list_news())
    assert [i['title'] for i in items] == ['Свежая без даты', 'Ставка 14%', 'Рубль укрепился']
    assert set(items[0]) == {'id', 'title', 'summary', 'content', 'url', 'source_name',
                             'published_at', 'fetched_at', 'origin'}
    first = items[1]
    assert first['id'] == ids[0] == news_id_for_url('https://cbr.ru/a')
    assert first['source_name'] == 'Банк России'
    assert first['content'] == '' and first['origin'] in ('collector', 'snapshot', 'user')
    assert datetime.fromisoformat(first['published_at']) == NOW - timedelta(days=1)
    assert first['fetched_at']
    assert items[0]['published_at']  # COALESCE(published_at, created_at)

    since = (NOW - timedelta(days=5)).isoformat()
    assert {i['title'] for i in store.list_news(since_iso=since)} == {'Ставка 14%', 'Свежая без даты'}
    assert len(store.list_news(limit=1)) == 1

    assert store.get_news(ids[1])['title'] == 'Рубль укрепился'
    assert store.get_news('not-a-uuid') is None
    assert store.get_news(str(uuid.uuid4())) is None


def test_pg_news_with_go_columns_and_readonly(monkeypatch):
    if not PG_URL:
        pytest.skip('TEST_DATABASE_URL не задан')
    _pg_exec(GO_NEWS_SQL)
    s = PgStore(PG_URL, wait_timeout=20)
    try:
        # news по схеме 001 (без content/origin/fetched_at) — работаем с подстановками
        assert s.list_news() == [] and s.count_news() == 0
        # Go-миграция добавила колонки «на лету» — неполный набор колонок перепроверяется
        _pg_seed_news([{**NEWS[0], 'content': 'Полный текст', 'origin': 'user'}], with_go_columns=True)
        assert s.list_news()[0]['content'] == ''  # до перепроверки — кэш колонок
        monkeypatch.setattr(storage, '_NEWS_COLS_RECHECK_S', 0.0)
        n = s.list_news()[0]
        assert n['content'] == 'Полный текст' and n['origin'] == 'user'
        assert n['fetched_at']  # fetched_at NULL → created_at
        with pytest.raises(NotImplementedError):
            s.add_news({'title': 'x', 'url': 'https://x'})
    finally:
        s.close()


def test_pg_no_news_table():
    if not PG_URL:
        pytest.skip('TEST_DATABASE_URL не задан')
    _pg_exec('DROP TABLE IF EXISTS news, sources CASCADE')
    s = PgStore(PG_URL, wait_timeout=20)
    try:
        assert s.list_news() == [] and s.count_news() == 0 and s.get_news(str(uuid.uuid4())) is None
    finally:
        s.close()


def test_memory_add_news_dedup_and_snapshot(tmp_path):
    s = MemoryStore()
    a = s.add_news({'title': 'A', 'url': 'https://x/a', 'origin': 'user'})
    b = s.add_news({'title': 'A2', 'url': 'https://x/a'})
    assert a == b and a['id'] == news_id_for_url('https://x/a') and a['origin'] == 'user'
    assert s.count_news() == 1

    snap = {'generated_at': '2026-10-24T19:00:00+03:00', 'items': [
        {'title': 'T1', 'summary': 'S', 'url': 'https://cbr.ru/1', 'source_name': 'Банк России',
         'published_at': '2026-10-23T13:30:00+03:00'},
        {'title': 'T2', 'summary': 'S', 'url': 'https://cbr.ru/2', 'source_name': 'РБК',
         'published_at': '2026-10-22T10:00:00Z'},
        {'title': 'bad, no url'},
    ]}
    (tmp_path / 'news_snapshot.json').write_text(json.dumps(snap), encoding='utf-8')
    st = make_store(SimpleNamespace(database_url='', data_dir=tmp_path))
    assert isinstance(st, MemoryStore) and st.count_news() == 2
    n = st.get_news(news_id_for_url('https://cbr.ru/1'))
    assert n['origin'] == 'snapshot' and n['published_at'] == '2026-10-23T10:30:00+00:00'
    assert n['fetched_at'] == '2026-10-24T16:00:00+00:00'

    empty = make_store(SimpleNamespace(database_url='', data_dir=tmp_path / 'missing'))
    assert empty.count_news() == 0


# ---------------------------------------------------------------- events

def test_events(store: Store):
    n1, n2 = str(uuid.uuid4()), str(uuid.uuid4())
    assert store.get_events([n1], 'rules-v1') == {}
    store.put_event(n1, 'rules-v1', {'event_type': 'key_rate', 'sectors': ['finance']})
    store.put_event(n2, 'rules-v1', {'event_type': 'fx'})
    store.put_event(n1, 'llm-v1', {'event_type': 'other'})
    store.put_event(n1, 'rules-v1', {'event_type': 'key_rate', 'direction': 'hold'})  # upsert
    got = store.get_events([n1, n2, 'garbage'], 'rules-v1')
    assert got == {n1: {'event_type': 'key_rate', 'direction': 'hold'}, n2: {'event_type': 'fx'}}
    assert store.get_events([], 'rules-v1') == {}


# ---------------------------------------------------------------- insights

def _insight(cache_key='k1', status='queued'):
    return {'id': str(uuid.uuid4()), 'cache_key': cache_key, 'company_id': 'U_1',
            'news_id': str(uuid.uuid4()), 'role': 'cfo', 'status': status, 'trace_id': str(uuid.uuid4())}


def test_insights(store: Store):
    row = _insight()
    store.create_insight(row)
    got = _json_roundtrip(store.get_insight(row['id']))
    for k in ('id', 'cache_key', 'company_id', 'news_id', 'role', 'status', 'trace_id'):
        assert got[k] == row[k]
    assert got['result'] is None and got['error'] is None and got['mode'] is None
    assert got['progress'] == [] and got['created_at'] and got['updated_at']

    progress = [{'step': 1, 'kind': 'tool', 'name': 'get_company_profile', 'status': 'ok'}]
    result = {'mode': 'llm', 'headline': 'Ставка', 'validation': {'passed': True, 'repairs': 1},
              'bank_view': {'status': 'found'}}
    store.update_insight(row['id'], status='processing', progress=progress)
    store.update_insight(row['id'], status='completed', result=result, mode='llm', error=None)
    got = store.get_insight(row['id'])
    assert got['status'] == 'completed' and got['result'] == result and got['progress'] == progress
    assert got['mode'] == 'llm'
    assert got['updated_at'] >= got['created_at']
    with pytest.raises(ValueError):
        store.update_insight(row['id'], id='x')
    store.update_insight(str(uuid.uuid4()), status='failed')  # нет такой — без ошибки

    assert store.get_insight('nope') is None
    assert store.get_insight(str(uuid.uuid4())) is None

    # find_insight_by_key: самый свежий из активных, failed игнорируется
    assert store.find_insight_by_key('k1')['id'] == row['id']
    newer = _insight()
    store.create_insight(newer)
    assert store.find_insight_by_key('k1')['id'] == newer['id']
    store.update_insight(newer['id'], status='failed', error='boom')
    assert store.find_insight_by_key('k1')['id'] == row['id']
    store.create_insight(_insight('k2', status='failed'))
    assert store.find_insight_by_key('k2') is None
    assert store.find_insight_by_key('missing') is None


# ---------------------------------------------------------------- traces

def test_traces(store: Store):
    tid, iid = str(uuid.uuid4()), str(uuid.uuid4())
    assert store.get_trace(tid) is None and store.get_trace('bad') is None
    store.save_trace(tid, iid, 'insight', [{'step': 1}], {'duration_ms': 100})
    store.save_trace(tid, iid, 'insight', [{'step': 1}, {'step': 2}], {'duration_ms': 300, 'mode': 'llm'})
    t = _json_roundtrip(store.get_trace(tid))
    assert t['trace_id'] == tid and t['insight_id'] == iid and t['kind'] == 'insight'
    assert t['steps'] == [{'step': 1}, {'step': 2}] and t['summary'] == {'duration_ms': 300, 'mode': 'llm'}
    assert t['created_at'] and t['updated_at']
    store.save_trace(str(uuid.uuid4()), None, 'chat', [], {})
    assert store.get_trace(tid)['insight_id'] == iid


# ---------------------------------------------------------------- chat

def test_chat(store: Store):
    iid, other = str(uuid.uuid4()), str(uuid.uuid4())
    tid = str(uuid.uuid4())
    m1 = store.add_chat(iid, 'U_1', 'user', 'Как это повлияет?', {}, None)
    m2 = store.add_chat(iid, 'U_1', 'assistant', 'Ответ', {'statements': [{'text': 'x'}]}, tid)
    store.add_chat(other, 'U_2', 'user', 'чужой', {}, None)
    assert set(m1) == {'id', 'insight_id', 'role', 'content', 'payload', 'trace_id', 'created_at'}
    assert isinstance(m1['id'], int) and m2['id'] > m1['id']
    assert m2['trace_id'] == tid and m2['payload'] == {'statements': [{'text': 'x'}]}
    msgs = _json_roundtrip(store.list_chat(iid))
    assert [m['content'] for m in msgs] == ['Как это повлияет?', 'Ответ']
    assert store.list_chat('bad') == []


# ---------------------------------------------------------------- llm usage / cache

def test_usage_and_cache(store: Store):
    assert store.usage_today() == 0
    store.add_usage('GLM-5.3-Flash', 100, 20)
    store.add_usage('GLM-5.3-Flash', 50, 5)
    store.add_usage('Qwen3.6-35B-A3B', 10, 1)
    assert store.usage_today() == 186
    summ = _json_roundtrip(store.usage_summary(7))
    today = datetime.now(timezone.utc).date().isoformat()
    by_model = {r['model']: r for r in summ}
    assert by_model['GLM-5.3-Flash'] == {'day': today, 'model': 'GLM-5.3-Flash', 'calls': 2,
                                         'prompt_tokens': 150, 'completion_tokens': 25}
    assert by_model['Qwen3.6-35B-A3B']['calls'] == 1

    assert store.cache_get('k') is None
    store.cache_put('k', 'GLM-5.3-Flash', {'text': 'a', 'data': {'x': [1]}})
    store.cache_put('k', 'GLM-5.3-Flash', {'text': 'b', 'data': None})
    assert store.cache_get('k') == {'text': 'b', 'data': None}


# ---------------------------------------------------------------- feedback / metrics

def test_metrics(store: Store):
    empty = _json_roundtrip(store.metrics_summary())
    assert empty['insights_total'] == 0 and empty['validation_pass_rate'] is None
    assert empty['avg_duration_ms'] is None and empty['feedback'] == {'up': 0, 'down': 0}

    def done(passed, bank, repairs, mode='llm'):
        r = _insight(cache_key=str(uuid.uuid4()))
        store.create_insight(r)
        store.update_insight(r['id'], status='completed', mode=mode, result={
            'mode': mode, 'validation': {'passed': passed, 'repairs': repairs}, 'bank_view': {'status': bank}})
        return r

    a = done(True, 'found', 0)
    done(True, 'not_found', 2)
    done(False, 'found', 1, mode='rules')
    store.create_insight(_insight(cache_key='q'))
    store.save_trace(str(uuid.uuid4()), a['id'], 'insight', [], {'duration_ms': 1000})
    store.save_trace(str(uuid.uuid4()), a['id'], 'insight', [], {'duration_ms': 3000})
    store.save_trace(str(uuid.uuid4()), a['id'], 'chat', [], {'duration_ms': 500})
    store.save_trace(str(uuid.uuid4()), a['id'], 'insight', [], {'duration_ms': 'n/a'})
    store.add_chat(a['id'], 'U_1', 'user', 'q', {}, None)
    store.add_feedback(a['id'], 'U_1', 1, '')
    store.add_feedback(a['id'], 'U_1', 1, 'полезно')
    store.add_feedback(a['id'], 'U_1', -1, 'не про нас')
    store.add_usage('GLM-5.3-Flash', 100, 20)
    store.cache_put('c1', 'GLM-5.3-Flash', {'text': 'x'})

    m = _json_roundtrip(store.metrics_summary())
    assert m['insights_total'] == 4
    assert m['by_status'] == {'completed': 3, 'queued': 1}
    assert m['by_mode'] == {'llm': 2, 'rules': 1}
    assert m['validation_pass_rate'] == pytest.approx(2 / 3, abs=1e-3)
    assert m['bank_view_found_rate'] == pytest.approx(2 / 3, abs=1e-3)
    assert m['avg_duration_ms'] == 2000
    assert m['avg_repairs'] == pytest.approx(1.0)
    assert m['chat_messages'] == 1
    assert m['feedback'] == {'up': 2, 'down': 1}
    assert m['llm_tokens_today'] == 120 and m['llm_calls_today'] == 1
    assert m['cache_entries'] == 1


def test_memory_thread_safety():
    s = MemoryStore()

    def work():
        for _ in range(200):
            s.add_usage('m', 1, 1)
            s.add_chat(str(uuid.uuid4()), 'U', 'user', 'x', {}, None)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert s.usage_today() == 8 * 200 * 2
    assert s.metrics_summary()['chat_messages'] == 1600
