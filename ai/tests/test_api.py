"""Сквозной тест API AI-сервиса (in-memory хранилище, синтетические профили, офлайн-снимок новостей)."""
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

DATA = Path(__file__).resolve().parents[2] / 'data'


@pytest.fixture(scope='module')
def client():
    from app import main
    from app.config import settings
    from app.data_build import build_profiles
    from app.profiles import ProfileStore
    settings.database_url = ''
    settings.llm_base_url = settings.llm_api_key = ''
    orig = ProfileStore.load
    ProfileStore.load = classmethod(lambda cls: cls(build_profiles(DATA / 'synthetic', 15e9), 'synthetic:test'))
    try:
        with TestClient(main.app) as c:
            yield c
    finally:
        ProfileStore.load = orig


def wait(client, iid, cid):
    for _ in range(100):
        r = client.get(f'/api/v1/insights/{iid}', headers={'X-Client-Id': cid}).json()
        if r['status'] in ('completed', 'failed'):
            return r
        time.sleep(0.05)
    raise AssertionError('timeout')


def test_end_to_end(client):
    st = client.get('/api/v1/system/status').json()
    assert st['mode'] == 'rules' and st['profiles'] >= 8
    comps = client.get('/api/v1/companies').json()
    assert comps['total'] >= 8
    cid = 'U_9000001'
    prof = client.get(f'/api/v1/companies/{cid}').json()
    assert prof['channels'] and prof['observed']['MAINOKVED_CODE']['source'].endswith('MAINOKVED_CODE')
    feed = client.get(f'/api/v1/companies/{cid}/feed', params={'limit': 10, 'include_filtered': True}).json()
    assert feed['items'] and feed['stats']['filtered_non_business'] > 0
    top = feed['items'][0]
    assert top['relevance']['reasons'] and top['relevance']['components']

    nid = top['news_id']
    assert client.post('/api/v1/insights', json={'company_id': cid, 'news_id': nid}).status_code == 401
    assert client.post('/api/v1/insights', json={'company_id': cid, 'news_id': nid},
                       headers={'X-Client-Id': 'U_9000002'}).status_code == 403
    r = client.post('/api/v1/insights', json={'company_id': cid, 'news_id': nid}, headers={'X-Client-Id': cid})
    assert r.status_code == 202
    iid = r.json()['insight_id']
    res = wait(client, iid, cid)
    assert res['status'] == 'completed', res
    ins = res['result']
    assert ins['what_happened'] and ins['sources'] and ins['validation']['passed']
    # чужой контекст не видит инсайт
    assert client.get(f'/api/v1/insights/{iid}', headers={'X-Client-Id': 'U_9000002'}).status_code == 403
    # кэш: повторный запрос возвращает тот же инсайт
    again = client.post('/api/v1/insights', json={'company_id': cid, 'news_id': nid}, headers={'X-Client-Id': cid}).json()
    assert again['insight_id'] == iid and again['cached']
    tr = client.get(f'/api/v1/insights/{iid}/trace', headers={'X-Client-Id': cid}).json()
    assert tr['steps'] and tr['summary']['tool_calls'] >= 5
    ch = client.post(f'/api/v1/insights/{iid}/chat', json={'question': 'На чём основан вывод?'}, headers={'X-Client-Id': cid})
    assert ch.status_code == 200 and ch.json()['message']['content']
    assert len(client.get(f'/api/v1/insights/{iid}/chat', headers={'X-Client-Id': cid}).json()['messages']) == 2
    assert client.post(f'/api/v1/insights/{iid}/chat', json={'question': 'а у них?'},
                       headers={'X-Client-Id': 'U_9000003'}).status_code == 403
    assert client.post(f'/api/v1/insights/{iid}/feedback', json={'rating': 1}, headers={'X-Client-Id': cid}).json()['ok']
    rel = client.get('/api/v1/relevance', params={'news_id': nid, 'company_ids': 'U_9000001,U_9000007'}).json()
    assert len(rel['results']) == 2
    m = client.get('/api/v1/metrics/summary').json()
    assert m['insights_total'] >= 1
    assert client.get('/api/v1/bank/documents').json()['items']
    assert client.get('/api/v1/companies/NOPE').status_code == 404
    assert client.get('/api/v1/insights/not-a-uuid', headers={'X-Client-Id': cid}).status_code == 400


def test_base_company_without_financial_profile_still_sees_business_news(client):
    from app.main import S
    cid = '75ad1adb-7c36-4101-bd17-7c782a620c2f'
    S['profiles'].add_database_companies([{'id': cid, 'name': 'Основная компания', 'industry': '', 'description': ''}])
    feed = client.get(f'/api/v1/companies/{cid}/feed').json()
    assert feed['items'], 'Missing company profile must not hide every business publication'
    assert any(item['relevance']['level'] == 'none' for item in feed['items'])
    assert all(item['filtered_reason'] is None for item in feed['items'])
