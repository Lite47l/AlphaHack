"""Клиент OpenAI-совместимого API организаторов.

Правила кейса: используются только модели из `config.ALLOWED_MODELS`; модель вне списка —
отказ без сетевого запроса. Суточный бюджет токенов и кэш ответов — в хранилище (`Store`).
В логи пишутся модель, роль, длительность, токены и статус — никогда ключ и тексты промптов.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from .config import is_allowed_model

log = logging.getLogger('app.llm')

ROLES = ('planner', 'extractor', 'writer', 'chat')
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_THINK_RE = re.compile(r'<think(?:ing)?>.*?</think(?:ing)?>', re.S | re.I)
_FENCE_RE = re.compile(r'```[ \t]*(?:json|JSON|json5)?[ \t]*\n?(.*?)```', re.S)
_TRAILING_COMMA_RE = re.compile(r',\s*([}\]])')


class LLMError(Exception):
    """code: 'disabled' | 'budget' | 'not_allowed' | 'timeout' | 'http' | 'parse'."""

    def __init__(self, code: str, message: str, raw: str | None = None):
        super().__init__(f'{code}: {message}')
        self.code = code
        self.message = message
        self.raw = raw


@dataclass
class LLMResult:
    text: str
    data: dict | list | None
    model: str
    role: str
    prompt_tokens: int
    completion_tokens: int
    cached: bool
    duration_ms: int


# ---------------------------------------------------------------- text helpers

def strip_think(text: str) -> str:
    """Убрать рассуждения reasoning-моделей: блоки <think>…</think>, незакрытый <think> в начале
    и «хвост» рассуждения, если модель выдала только закрывающий тег."""
    if not text:
        return ''
    t = _THINK_RE.sub('', text)
    low = t.lower()
    for close in ('</think>', '</thinking>'):
        i = low.rfind(close)
        if i != -1:
            t = t[i + len(close):]
            low = t.lower()
    stripped = t.lstrip()
    if stripped.lower().startswith(('<think>', '<thinking>')):
        return ''  # рассуждение оборвалось (max_tokens) — ответа нет
    return t.strip()


def _scan_balanced(text: str, start: int) -> int | None:
    """Индекс закрывающей скобки для text[start] in '{[' с учётом строк JSON."""
    stack: list[str] = []
    in_str = False
    esc = False
    pairs = {'{': '}', '[': ']'}
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in pairs:
            stack.append(pairs[ch])
        elif ch in '}]':
            if not stack or stack.pop() != ch:
                return None
            if not stack:
                return i
    return None


def _loads(candidate: str):
    try:
        return json.loads(candidate)
    except ValueError:
        pass
    fixed = _TRAILING_COMMA_RE.sub(r'\1', candidate)
    if fixed != candidate:
        try:
            return json.loads(fixed)
        except ValueError:
            pass
    return None


def extract_json(text: str) -> dict | list | None:
    """Надёжно достать JSON-объект/массив из ответа модели: целиком, из ```json-ограды
    или первый сбалансированный {…}/[…]. Неудача → None."""
    t = strip_think(text or '').strip()
    if not t:
        return None
    candidates = [t] + [m.strip() for m in _FENCE_RE.findall(t)]
    for c in candidates:
        v = _loads(c)
        if isinstance(v, (dict, list)):
            return v
    for c in candidates:
        tries = 0
        for i, ch in enumerate(c):
            if ch not in '{[':
                continue
            tries += 1
            if tries > 64:
                break
            end = _scan_balanced(c, i)
            if end is None:
                continue
            v = _loads(c[i:end + 1])
            if isinstance(v, (dict, list)):
                return v
    return None


def _content_text(content) -> str:
    """content может быть строкой или списком частей [{type:'text', text:'…'}]."""
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and isinstance(p.get('text'), str):
                parts.append(p['text'])
            elif isinstance(p, str):
                parts.append(p)
        return ''.join(parts)
    return str(content)


def _chat_url(base_url: str) -> str:
    base = (base_url or '').strip().rstrip('/')
    if base.endswith('/chat/completions'):
        return base
    if base.endswith('/v1') or urlsplit(base).path not in ('', '/'):
        return base + '/chat/completions'
    return base + '/v1/chat/completions'


def _ssl_verify():
    """Дополнительный корневой сертификат (например, НУЦ Минцифры) из LLM_CA_FILE поверх certifi."""
    ca = os.environ.get('LLM_CA_FILE', '').strip()
    if not ca:
        return True
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        ctx.load_verify_locations(cafile=ca)
        return ctx
    except (OSError, ssl.SSLError) as e:
        log.warning('LLM_CA_FILE not loaded: %s', type(e).__name__)
        return True


# ---------------------------------------------------------------- client

class LLMClient:
    """Потокобезопасный синхронный клиент (httpx.Client разделяется между потоками)."""

    def __init__(self, settings, store, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.store = store
        self.retry_pause_s = 1.0
        self._url = _chat_url(settings.llm_base_url) if settings.llm_base_url else ''
        timeout = float(settings.llm_timeout_s or 60)
        self._http = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            verify=_ssl_verify() if transport is None else True,
            headers={'Content-Type': 'application/json'},
        )

    def close(self) -> None:
        self._http.close()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.llm_enabled)

    def model_for(self, role: str) -> str:
        if role not in ROLES:
            raise ValueError(f'unknown LLM role: {role!r}')
        return getattr(self.settings, f'model_{role}')

    def budget_left(self) -> int:
        return max(0, int(self.settings.llm_daily_token_budget) - int(self.store.usage_today()))

    @staticmethod
    def cache_key(model: str, messages: list[dict], json_mode: bool, max_tokens: int) -> str:
        raw = model + json.dumps(messages, sort_keys=True, ensure_ascii=False) + str(bool(json_mode)) + str(max_tokens)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    # ----- public
    def complete(self, role: str, messages: list[dict], *, json_mode: bool = False,
                 max_tokens: int | None = None, temperature: float = 0.2) -> LLMResult:
        model = self.model_for(role)
        if not self.enabled:
            raise LLMError('disabled', 'LLM не настроена (нет LLM_BASE_URL или LLM_API_KEY)')
        if not is_allowed_model(model):
            log.warning('llm refused role=%s model=%s status=not_allowed', role, model)
            raise LLMError('not_allowed', f'модель {model!r} не входит в список разрешённых')
        max_tokens = int(max_tokens or self.settings.llm_max_tokens)
        key = self.cache_key(model, messages, json_mode, max_tokens)

        # Кэш проверяется до бюджета: ответ из кэша не расходует токены.
        t0 = time.monotonic()
        hit = self.store.cache_get(key)
        if hit is not None and isinstance(hit.get('text'), str):
            data = hit.get('data')
            if not json_mode or isinstance(data, (dict, list)):
                ms = int((time.monotonic() - t0) * 1000)
                log.info('llm call role=%s model=%s status=cached duration_ms=%d', role, model, ms)
                return LLMResult(text=hit['text'], data=data if json_mode else None, model=model, role=role,
                                 prompt_tokens=0, completion_tokens=0, cached=True, duration_ms=ms)

        if self.store.usage_today() >= self.settings.llm_daily_token_budget:
            log.warning('llm refused role=%s model=%s status=budget', role, model)
            raise LLMError('budget', 'исчерпан суточный бюджет токенов LLM')

        body: dict = {'model': model, 'messages': messages, 'temperature': temperature, 'max_tokens': max_tokens}
        if json_mode:
            body['response_format'] = {'type': 'json_object'}
        if not getattr(self.settings, 'llm_reasoning', False):
            # шлюз организаторов (OpenRouter-совместимый) по умолчанию включает «размышления» у Qwen/GLM:
            # они съедают max_tokens и бюджет. Ответ нужен структурированный, поэтому reasoning выключаем.
            body['reasoning'] = {'enabled': False}

        try:
            resp = self._post(body)
            if resp.status_code == 400 and ('response_format' in body or 'reasoning' in body):
                # не все OpenAI-совместимые серверы поддерживают эти параметры — один повтор без них
                log.info('llm role=%s model=%s status=400 retry_without_optional_params', role, model)
                body = {k: v for k, v in body.items() if k not in ('response_format', 'reasoning')}
                resp = self._post(body)
        except LLMError as e:
            self._log_fail(role, model, t0, e.code)
            raise
        if resp.status_code != 200:
            self._log_fail(role, model, t0, f'http_{resp.status_code}')
            raise LLMError('http', f'HTTP {resp.status_code}: {self._error_message(resp)}')

        try:
            payload = resp.json()
            msg = payload['choices'][0]['message']
        except (ValueError, KeyError, IndexError, TypeError) as e:
            self._log_fail(role, model, t0, 'bad_response')
            raise LLMError('parse', f'неожиданный формат ответа: {type(e).__name__}',
                           raw=resp.text[:4000]) from e
        raw_content = _content_text(msg.get('content'))
        reasoning = _content_text(msg.get('reasoning_content') or msg.get('reasoning'))
        text = strip_think(raw_content)

        usage = payload.get('usage') or {}
        pt = self._int(usage.get('prompt_tokens'))
        ct = self._int(usage.get('completion_tokens'))
        if pt <= 0:
            pt = sum(len(_content_text(m.get('content'))) for m in messages if isinstance(m, dict)) // 3
        if ct <= 0:
            ct = len(raw_content + reasoning) // 3
        self.store.add_usage(model, pt, ct)  # токены потрачены, даже если ответ дальше не разберётся
        ms = int((time.monotonic() - t0) * 1000)

        data = None
        if json_mode:
            data = extract_json(text)
            if data is None:
                log.warning('llm call role=%s model=%s status=parse_error duration_ms=%d '
                            'prompt_tokens=%d completion_tokens=%d', role, model, ms, pt, ct)
                raise LLMError('parse', 'ответ модели не содержит корректного JSON', raw=raw_content)
        elif not text:
            log.warning('llm call role=%s model=%s status=empty duration_ms=%d prompt_tokens=%d '
                        'completion_tokens=%d', role, model, ms, pt, ct)
            raise LLMError('parse', 'пустой ответ модели', raw=raw_content)

        self.store.cache_put(key, model, {'text': text, 'data': data, 'prompt_tokens': pt,
                                          'completion_tokens': ct})
        log.info('llm call role=%s model=%s status=ok duration_ms=%d prompt_tokens=%d completion_tokens=%d',
                 role, model, ms, pt, ct)
        return LLMResult(text=text, data=data, model=model, role=role, prompt_tokens=pt,
                         completion_tokens=ct, cached=False, duration_ms=ms)

    # ----- internals
    def _post(self, body: dict) -> httpx.Response:
        """POST с повторами: один при таймауте/5xx/429, до трёх при обрыве соединения (TLS через прокси)."""
        headers = {'Authorization': f'Bearer {self.settings.llm_api_key}'}
        last_exc: Exception | None = None
        conn_errors = 0
        for attempt in range(4):
            try:
                resp = self._http.post(self._url, json=body, headers=headers)
            except httpx.TimeoutException as e:
                last_exc = e
                if attempt == 0 and conn_errors == 0:
                    self._pause(None)
                    continue
                raise LLMError('timeout', f'нет ответа за {self.settings.llm_timeout_s} с') from None
            except httpx.HTTPError as e:
                last_exc = e
                conn_errors += 1
                if conn_errors < 4:
                    self._pause(None)
                    continue
                raise LLMError('http', f'ошибка соединения: {type(e).__name__}') from None
            if resp.status_code in _RETRY_STATUSES and attempt == conn_errors:
                self._pause(resp)
                continue
            return resp
        raise LLMError('http', f'ошибка соединения: {type(last_exc).__name__}')  # pragma: no cover

    def _pause(self, resp: httpx.Response | None) -> None:
        delay = self.retry_pause_s
        if resp is not None and resp.status_code == 429:
            try:
                delay = max(delay, min(5.0, float(resp.headers.get('retry-after', delay))))
            except ValueError:
                pass
        if delay > 0:
            time.sleep(delay)

    @staticmethod
    def _int(v) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _error_message(resp: httpx.Response) -> str:
        try:
            err = resp.json().get('error')
            msg = err.get('message') if isinstance(err, dict) else err
            return str(msg or '')[:200]
        except (ValueError, AttributeError):
            return resp.text[:200]

    @staticmethod
    def _log_fail(role: str, model: str, t0: float, status: str) -> None:
        log.warning('llm call role=%s model=%s status=%s duration_ms=%d', role, model, status,
                    int((time.monotonic() - t0) * 1000))
