"""Реестр доказательств анализа: всё, на что может сослаться вывод, с единым source_id.

N:<news_id> — новость, B:<chunk_id> — фрагмент аналитики банка, P:<FIELD> — поле профиля,
G:<path> — агрегат графа. Реестр — общий контекст шагов агента: инструменты добавляют
в него найденное, писатель ссылается только на его ID, валидатор проверяет по нему.
"""
import json

from .textproc import numbers


def _fmt_value(v) -> str:
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)[:1500]
    return '' if v is None else str(v)


class Evidence:
    def __init__(self):
        self.items: dict[str, dict] = {}

    def add(self, source: dict) -> str:
        self.items.setdefault(source['id'], source)
        return source['id']

    def has(self, sid: str) -> bool:
        return sid in self.items

    def text_of(self, sid: str) -> str:
        s = self.items.get(sid)
        if not s:
            return ''
        if s['type'] == 'news':
            return f"{s.get('title', '')}. {s.get('text', '')}"
        if s['type'] == 'bank':
            return f"{s.get('doc_title', '')} {s.get('published_at', '')} {s.get('text', '')}"
        return f"{s.get('title', '')}: {_fmt_value(s.get('value'))}"

    def numbers_of(self, sids: list[str]) -> set[str]:
        out = set()
        for sid in sids:
            s = self.items.get(sid)
            if not s:
                continue
            out |= numbers(self.text_of(sid))
            for v in _walk_numbers(s.get('value')):
                out.add(f'{v:g}')
                if 0 < abs(v) <= 1:
                    out.add(f'{round(v * 100):g}')  # доли графа показываются в процентах
                    out.add(f'{round(v * 100, 1):g}')
                if abs(v) >= 1e6:
                    out.add(f'{round(v / 1e9, 1):g}')  # млрд
                    out.add(f'{round(v / 1e9):g}')
                    out.add(f'{round(v / 1e6):g}')  # млн
        return out

    def public(self) -> dict:
        """Источники для ответа API (без служебных полей)."""
        out = {}
        for sid, s in self.items.items():
            item = {k: v for k, v in s.items() if k != 'text' or s['type'] == 'bank'}
            if s['type'] == 'news':
                item['excerpt'] = (s.get('text') or '')[:600]
            out[sid] = item
        return out

    def prompt_block(self, ids: list[str] | None = None, max_chars: int = 900) -> str:
        """Компактное представление доказательств для промпта (данные, а не инструкции)."""
        lines = []
        for sid in ids or list(self.items):
            s = self.items[sid]
            if s['type'] == 'news':
                lines.append(f'[{sid}] НОВОСТЬ ({s.get("source_name", "")}, {s.get("published_at", "")[:10]}): '
                             f'{s.get("title", "")}. {(s.get("text") or "")[:max_chars * 2]}')
            elif s['type'] == 'bank':
                lines.append(f'[{sid}] АНАЛИТИКА АЛЬФА-БАНКА «{s.get("doc_title")}», {s.get("published_at")}, стр. {s.get("page")}'
                             f'{" (ВНИМАНИЕ: " + s["warning"] + ")" if s.get("warning") else ""}: {s.get("text", "")[:max_chars]}')
            else:
                lines.append(f'[{sid}] ДАННЫЕ КЛИЕНТА — {s.get("title")}: {_fmt_value(s.get("value"))[:max_chars]}')
        return '\n'.join(lines)


def _walk_numbers(v):
    if isinstance(v, bool) or v is None:
        return
    if isinstance(v, (int, float)):
        yield float(v)
    elif isinstance(v, dict):
        for x in v.values():
            yield from _walk_numbers(x)
    elif isinstance(v, list):
        for x in v:
            yield from _walk_numbers(x)
