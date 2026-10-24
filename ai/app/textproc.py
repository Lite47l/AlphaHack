"""Нормализация русского текста для поиска и проверок: токены, лёгкий стемминг, числа."""
import re

_WORD = re.compile(r'[a-zа-яё0-9]+(?:[.,][0-9]+)?', re.I)
_ENDINGS = sorted([
    'иями', 'ями', 'ами', 'ого', 'его', 'ому', 'ему', 'ыми', 'ими', 'иях', 'ах', 'ях', 'ов', 'ев', 'ей',
    'ий', 'ый', 'ой', 'ая', 'яя', 'ое', 'ее', 'ые', 'ие', 'ых', 'их', 'ую', 'юю', 'ом', 'ем', 'ам', 'ям',
    'ться', 'тся', 'ать', 'ять', 'еть', 'ить', 'ла', 'ли', 'ло', 'ет', 'ит', 'ут', 'ют', 'ат', 'ят',
    'ию', 'ия', 'ие', 'ии', 'ью', 'ь', 'а', 'я', 'о', 'е', 'ы', 'и', 'у', 'ю', 'й',
], key=len, reverse=True)
STOP = set('''и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было
вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж
вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто
чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом один почти мой тем
чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть после над больше тот через
эти нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя
такой им более всегда конечно всю между это также году года г млн млрд руб том которые который которая также
the of and to in a is for on with as by at an be this that are from or it'''.split())


def stem(word: str) -> str:
    w = word.lower().replace('ё', 'е')
    if len(w) <= 4 or not re.match('[а-я]', w):
        return w
    for e in _ENDINGS:
        if w.endswith(e) and len(w) - len(e) >= 4:
            w = w[:-len(e)]
            break
    return w[:6]  # обрезка до 6 символов — устойчивый приём для русского поиска («сохранить»/«сохранения»)


def tokens(text: str, drop_stop: bool = True) -> list[str]:
    out = []
    for m in _WORD.finditer(text.lower()):
        t = m.group(0)
        if drop_stop and t in STOP:
            continue
        if t[0].isdigit():
            try:
                t = f"{float(t.replace(',', '.')):g}"  # «14,0» и «14» — одно число
            except ValueError:
                pass
            out.append(t)
            continue
        out.append(stem(t))
    return out


_NUM = re.compile(r'(?<![\w.,])[-+−]?\d{1,3}(?:[  ]\d{3})+(?:[.,]\d+)?|(?<![\w.,])[-+−]?\d+(?:[.,]\d+)?')


_DATES = re.compile(r'\b\d{4}-\d{2}-\d{2}(?:T[\d:.+Z-]+)?\b|\b\d{1,2}\.\d{2}\.\d{4}\b|\b\d{1,2}\.\d{2}(?=[\s,)])'
                    r'|\b\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\b')


def numbers(text: str) -> set[str]:
    """Значимые числа из текста в нормальной форме (для проверки происхождения чисел в выводах)."""
    out = set()
    text = _DATES.sub(' ', text)  # даты — не количественные утверждения
    for m in _NUM.finditer(text):
        raw = m.group(0).replace(' ', '').replace(' ', '').replace('−', '-').replace(',', '.').lstrip('+')
        try:
            val = float(raw)
        except ValueError:
            continue
        if raw.lstrip('-').isdigit() and len(raw.lstrip('-')) == 4 and 1990 <= abs(val) <= 2100:
            continue  # годы не считаем количественным утверждением
        if abs(val) < 10 and raw.lstrip('-').isdigit():
            continue  # «3 шага», «2 сценария» — не количественные утверждения
        out.add(f'{val:g}')
    return out


def sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+(?=[А-ЯЁA-Z«"•(])', re.sub(r'\s+', ' ', text).strip())
    return [p.strip(' •') for p in parts if len(p.strip()) > 20]


def similarity(a: str, b: str) -> float:
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def clean_html(text: str) -> str:
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', text or '', flags=re.S | re.I)
    text = re.sub(r'<br\s*/?>|</p>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    for a, b in (('&nbsp;', ' '), ('&laquo;', '«'), ('&raquo;', '»'), ('&quot;', '"'), ('&amp;', '&'),
                 ('&mdash;', '—'), ('&ndash;', '–'), ('&lt;', '<'), ('&gt;', '>')):
        text = text.replace(a, b)
    return re.sub(r'[ \t]+', ' ', re.sub(r'\n\s*\n+', '\n', text)).strip()


_INJECTION = re.compile(r'игнорируй|забудь (все|предыдущ)|предыдущие инструкции|системн\w* промпт|ignore (all|previous|the above)|'
                        r'system prompt|you are now|ты теперь|выполни команду|disregard', re.I)


def looks_like_injection(text: str) -> bool:
    """Признак попытки управлять моделью через внешний текст (новость, документ). Такие фрагменты не цитируются."""
    return bool(_INJECTION.search(text or ''))
