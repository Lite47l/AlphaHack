import json
import logging
import threading

import httpx
import pytest

from app.config import Settings
from app.llm import LLMClient, LLMError, extract_json, strip_think
from app.storage import MemoryStore

KEY = 'sk-very-secret-key-123'


def make_settings(**kw) -> Settings:
    base = dict(llm_base_url='https://llm.example/v1', llm_api_key=KEY,
                model_planner='GLM-5.3-Flash', model_extractor='Gemma-4-26B-A4B',
                model_writer='Qwen3.6-35B-A3B', model_chat='Qwen3.6-35B-A3B',
                llm_timeout_s=5, llm_daily_token_budget=10_000, llm_max_tokens=500, database_url='')
    base.update(kw)
    return Settings(**base)


def ok_response(content, usage=(100, 20), **msg_extra):
    body = {'choices': [{'message': {'role': 'assistant', 'content': content, **msg_extra}}]}
    if usage:
        body['usage'] = {'prompt_tokens': usage[0], 'completion_tokens': usage[1]}
    return httpx.Response(200, json=body)


class Recorder:
    """MockTransport-обработчик: отдаёт ответы по очереди и запоминает запросы."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            self.requests.append(request)
            r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        # новый объект на каждый запрос: один Response нельзя отдавать несколько раз
        return httpx.Response(r.status_code, headers=r.headers, content=r.content)

    def bodies(self):
        return [json.loads(r.content) for r in self.requests]


def make_client(rec, store=None, **kw):
    c = LLMClient(make_settings(**kw), store or MemoryStore(), transport=httpx.MockTransport(rec))
    c.retry_pause_s = 0
    return c


MSGS = [{'role': 'system', 'content': 'Ты аналитик.'}, {'role': 'user', 'content': 'Ставка 14%?'}]


def test_model_not_allowed_refused_without_request():
    rec = Recorder(ok_response('hi'))
    c = make_client(rec, model_writer='gpt-4o')
    with pytest.raises(LLMError) as ei:
        c.complete('writer', MSGS)
    assert ei.value.code == 'not_allowed'
    assert rec.requests == []


def test_allowed_model_with_provider_prefix():
    rec = Recorder(ok_response('ok'))
    c = make_client(rec, model_writer='zai-org/GLM-5.3-Flash')
    assert c.complete('writer', MSGS).text == 'ok'


def test_disabled_without_key():
    rec = Recorder(ok_response('hi'))
    c = make_client(rec, llm_api_key='')
    assert c.enabled is False
    with pytest.raises(LLMError) as ei:
        c.complete('chat', MSGS)
    assert ei.value.code == 'disabled'
    assert rec.requests == []


def test_request_shape_and_url():
    rec = Recorder(ok_response('Ответ'))
    c = make_client(rec)
    r = c.complete('planner', MSGS, temperature=0.1)
    req = rec.requests[0]
    assert str(req.url) == 'https://llm.example/v1/chat/completions'
    assert req.headers['authorization'] == f'Bearer {KEY}'
    body = rec.bodies()[0]
    assert body['model'] == 'GLM-5.3-Flash' and body['messages'] == MSGS
    assert body['max_tokens'] == 500 and body['temperature'] == 0.1
    assert 'response_format' not in body
    assert (r.text, r.model, r.role, r.prompt_tokens, r.completion_tokens, r.cached) == \
        ('Ответ', 'GLM-5.3-Flash', 'planner', 100, 20, False)


@pytest.mark.parametrize('base,expected', [
    ('https://h.example', 'https://h.example/v1/chat/completions'),
    ('https://h.example/v1/', 'https://h.example/v1/chat/completions'),
    ('https://h.example/api/openai', 'https://h.example/api/openai/chat/completions'),
])
def test_url_building(base, expected):
    rec = Recorder(ok_response('x'))
    c = make_client(rec, llm_base_url=base.rstrip('/'))
    c.complete('chat', MSGS)
    assert str(rec.requests[0].url) == expected


def test_json_with_fences_and_think():
    content = ('<think>Нужно подумать {"not": "this"}</think>\nВот ответ:\n```json\n'
               '{"headline": "Ставка 14%", "items": [1, 2,],}\n```\nГотово.')
    rec = Recorder(ok_response(content, reasoning_content='длинное рассуждение'))
    r = make_client(rec).complete('writer', MSGS, json_mode=True)
    assert r.data == {'headline': 'Ставка 14%', 'items': [1, 2]}
    assert '<think>' not in r.text
    assert rec.bodies()[0]['response_format'] == {'type': 'json_object'}


def test_json_parse_failure_has_raw_and_counts_usage():
    store = MemoryStore()
    rec = Recorder(ok_response('извините, не могу', usage=(50, 5)))
    with pytest.raises(LLMError) as ei:
        make_client(rec, store).complete('writer', MSGS, json_mode=True)
    assert ei.value.code == 'parse'
    assert ei.value.raw == 'извините, не могу'
    assert store.usage_today() == 55


def test_extract_json_variants():
    assert extract_json('prefix {"a": "x}y", "b": [1, {"c": 2}]} suffix [3]') == {'a': 'x}y', 'b': [1, {'c': 2}]}
    assert extract_json('[1, 2]') == [1, 2]
    assert extract_json('{broken {"ok": true}') == {'ok': True}
    assert extract_json('nothing here') is None
    assert extract_json('<think>{"a":1}') is None
    assert strip_think('reasoning only</think>  answer') == 'answer'


def test_retry_without_response_format_on_400():
    rec = Recorder(httpx.Response(400, json={'error': {'message': 'response_format not supported'}}),
                   ok_response('{"ok": true}'))
    r = make_client(rec).complete('extractor', MSGS, json_mode=True)
    assert r.data == {'ok': True}
    b1, b2 = rec.bodies()
    assert 'response_format' in b1 and 'response_format' not in b2


def test_retry_once_on_5xx_and_timeout():
    rec = Recorder(httpx.Response(503, text='busy'), ok_response('ok'))
    assert make_client(rec).complete('chat', MSGS).text == 'ok'
    assert len(rec.requests) == 2

    rec = Recorder(httpx.ReadTimeout('slow'), ok_response('ok2'))
    assert make_client(rec).complete('chat', MSGS).text == 'ok2'

    rec = Recorder(httpx.ReadTimeout('slow'))
    with pytest.raises(LLMError) as ei:
        make_client(rec).complete('chat', MSGS)
    assert ei.value.code == 'timeout' and len(rec.requests) == 2

    rec = Recorder(httpx.Response(500, text='boom'))
    with pytest.raises(LLMError) as ei:
        make_client(rec).complete('chat', MSGS)
    assert ei.value.code == 'http' and len(rec.requests) == 2


def test_cache_hit_does_not_spend_budget():
    store = MemoryStore()
    rec = Recorder(ok_response('{"x": 1}', usage=(300, 40)))
    c = make_client(rec, store)
    r1 = c.complete('writer', MSGS, json_mode=True)
    used = store.usage_today()
    assert used == 340 and r1.cached is False
    r2 = c.complete('writer', MSGS, json_mode=True)
    assert r2.cached is True and r2.data == {'x': 1} and r2.text == r1.text
    assert store.usage_today() == used
    assert len(rec.requests) == 1
    # другой max_tokens — другой ключ кэша
    c.complete('writer', MSGS, json_mode=True, max_tokens=100)
    assert len(rec.requests) == 2


def test_budget_exceeded():
    store = MemoryStore()
    store.add_usage('Qwen3.6-35B-A3B', 900, 100)
    rec = Recorder(ok_response('x'))
    c = make_client(rec, store, llm_daily_token_budget=1000)
    assert c.budget_left() == 0
    with pytest.raises(LLMError) as ei:
        c.complete('chat', MSGS)
    assert ei.value.code == 'budget'
    assert rec.requests == []


def test_usage_estimated_when_missing():
    store = MemoryStore()
    rec = Recorder(ok_response('a' * 30, usage=None))
    r = make_client(rec, store).complete('chat', MSGS)
    assert r.completion_tokens == 10
    assert r.prompt_tokens == sum(len(m['content']) for m in MSGS) // 3
    assert store.usage_today() == r.prompt_tokens + r.completion_tokens


def test_key_and_prompt_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    rec = Recorder(httpx.Response(401, json={'error': {'message': 'bad key'}}), ok_response('ok'))
    c = make_client(rec)
    with pytest.raises(LLMError):
        c.complete('chat', MSGS)
    c.complete('planner', MSGS)
    c.complete('planner', MSGS)  # cached
    text = caplog.text
    assert 'llm call' in text
    assert KEY not in text
    assert 'Ставка 14%?' not in text and 'Ты аналитик' not in text


def test_unknown_role():
    with pytest.raises(ValueError):
        make_client(Recorder(ok_response('x'))).model_for('hacker')


def test_thread_safety_parallel_calls():
    store = MemoryStore()
    rec = Recorder(ok_response('ok', usage=(10, 1)))
    c = make_client(rec, store)
    errors = []

    def run(i):
        try:
            c.complete('chat', [{'role': 'user', 'content': f'q{i}'}])
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert store.usage_today() == 16 * 11
