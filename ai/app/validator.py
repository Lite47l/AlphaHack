"""A08: проверка обоснованности и структуры инсайта.

Проверяет: схему и обязательные блоки; что каждый вывод ссылается на существующие источники;
что позиция банка подкреплена фрагментом аналитики и цитата действительно есть в нём; что числа
в выводах встречаются в процитированных источниках; что утверждения о клиенте не противоречат
профилю; что нет запрещённых формулировок (гарантии, доля рынка без основания).
Возвращает замечания с кодом, серьёзностью и путём — их использует агент для доработки.
Ограничение: наличие цитаты не доказывает истинность вывода, проверяется только происхождение.
"""
import re

from .evidence import Evidence
from .textproc import numbers, similarity, tokens

LIST_BLOCKS = ['what_happened', 'why_it_matters', 'risks', 'opportunities', 'ai_conclusions', 'actions']
FORBIDDEN = [
    (re.compile(r'гарантир', re.I), 'Недопустимо гарантировать исход'),
    (re.compile(r'доля рынка|долю рынка|доли рынка', re.I), 'Доля рынка не следует из данных (есть только позиция в выборке)'),
    (re.compile(r'\bROI\b|окупаемост\w* составит', re.I), 'Выдуманный количественный эффект'),
    (re.compile(r'собственник\w* компании является|владеет компанией', re.I), 'Связь физлица не означает владение'),
]
# утверждение о наличии продукта → поле профиля, которое должно быть = 1
PRODUCT_CLAIMS = [
    (re.compile(r'кредит(ы|ов|ных продукт|ную нагрузк|ный портфел)', re.I), ['CL_PRODUCT_LOA_MARK', 'CL_PRODUCT_LEA_MARK', 'FACTORING_MARK']),
    (re.compile(r'лизинг', re.I), ['CL_PRODUCT_LEA_MARK']),
    (re.compile(r'депозит', re.I), ['CL_PRODUCT_DEP_MARK']),
    (re.compile(r'зарплатн\w* проект', re.I), ['CL_PRODUCT_ZPP_MARK']),
    (re.compile(r'факторинг', re.I), ['FACTORING_MARK']),
]
CLAIM_MARKERS = re.compile(r'(у компании|у клиента|компания имеет|есть|использует|наличие)', re.I)


def _issue(code, severity, message, path):
    return {'code': code, 'severity': severity, 'message': message, 'path': path}


def _quote_found(quote: str, text: str) -> bool:
    q = re.sub(r'\s+', ' ', quote.strip(' «»"').lower())
    t = re.sub(r'\s+', ' ', text.lower())
    if len(q) < 15:
        return False
    if q in t:
        return True
    qt = tokens(q)
    tt = set(tokens(t))
    return bool(qt) and sum(1 for x in qt if x in tt) / len(qt) >= 0.85  # OCR/кавычки/переносы


def validate(insight: dict, ev: Evidence, profile: dict) -> dict:
    issues = []
    for block in LIST_BLOCKS:
        if not isinstance(insight.get(block), list):
            issues.append(_issue('schema', 'blocking', f'Блок {block} отсутствует или не список', block))
            insight[block] = []
    if not insight.get('what_happened'):
        issues.append(_issue('schema', 'blocking', 'Нет фактов о событии', 'what_happened'))
    if not insight.get('why_it_matters'):
        issues.append(_issue('no_client_link', 'warning', 'Не объяснена связь события с компанией', 'why_it_matters'))
    if not insight.get('headline'):
        issues.append(_issue('schema', 'warning', 'Нет заголовка инсайта', 'headline'))

    obs = {k: v['value'] for k, v in profile['observed'].items()}
    for block in LIST_BLOCKS:
        for i, st in enumerate(insight.get(block, [])):
            path = f'{block}[{i}]'
            if not isinstance(st, dict) or not st.get('text'):
                issues.append(_issue('schema', 'blocking', 'Пустое утверждение', path))
                continue
            sids = st.get('source_ids') or []
            missing = [s for s in sids if not ev.has(s)]
            if missing:
                issues.append(_issue('unknown_source', 'blocking', f'Ссылки на несуществующие источники: {", ".join(missing)}', path))
            if not sids and block not in ('actions',):
                issues.append(_issue('no_source', 'blocking', 'Утверждение без источника', path))
            if block == 'what_happened' and not any(s.startswith('N:') for s in sids):
                issues.append(_issue('fact_not_from_news', 'blocking', 'Факт события должен ссылаться на новость', path))
            if block == 'why_it_matters' and not any(s.startswith(('P:', 'G:')) for s in sids):
                issues.append(_issue('client_link_unsupported', 'blocking', 'Связь с компанией без ссылки на данные клиента', path))
            if st.get('kind') == 'bank_view' and not any(s.startswith('B:') for s in sids):
                issues.append(_issue('bank_view_unsupported', 'blocking', 'Позиция банка без фрагмента аналитики', path))
            text = st['text']
            cited = [s for s in sids if ev.has(s)]
            unsupported = numbers(text) - ev.numbers_of(cited)
            if unsupported:
                issues.append(_issue('unsupported_number', 'blocking',
                                     f'Числа не найдены в источниках утверждения: {", ".join(sorted(unsupported))}', path))
            for rx, msg in FORBIDDEN:
                if rx.search(text):
                    issues.append(_issue('forbidden_claim', 'blocking', msg, path))
            if block in ('why_it_matters', 'risks', 'opportunities') and CLAIM_MARKERS.search(text) \
                    and not re.search(r'\bнет\b|\bне\s+(?:имеет|использует)', text, re.I):
                for rx, fields in PRODUCT_CLAIMS:
                    if rx.search(text) and not any(obs.get(f) == 1 for f in fields):
                        issues.append(_issue('contradicts_profile', 'blocking',
                                             f'Утверждение о продукте не подтверждено профилем ({", ".join(fields)} ≠ 1)', path))

    bv = insight.get('bank_view') or {}
    statements = bv.get('statements') or []
    if bv.get('status') == 'found' and not statements:
        issues.append(_issue('schema', 'blocking', 'Статус found без утверждений банка', 'bank_view'))
    for i, st in enumerate(statements):
        path = f'bank_view.statements[{i}]'
        b_ids = [s for s in st.get('source_ids', []) if s.startswith('B:') and ev.has(s)]
        if not b_ids:
            issues.append(_issue('bank_view_unsupported', 'blocking', 'Позиция банка без существующего фрагмента аналитики', path))
            continue
        chunk_text = ' '.join(ev.text_of(s) for s in b_ids)
        body = ' '.join(ev.items[s].get('text', '') for s in b_ids)  # цитата — только из текста фрагмента, не из названия
        if not st.get('quote'):
            issues.append(_issue('quote_missing', 'warning', 'Нет дословной цитаты из аналитики банка', path))
        elif not _quote_found(st['quote'], body):
            issues.append(_issue('quote_not_found', 'blocking', 'Цитата не найдена в указанном фрагменте аналитики', path))
        unsupported = numbers(st.get('text', '')) - ev.numbers_of(b_ids)
        if unsupported:
            issues.append(_issue('unsupported_number', 'blocking',
                                 f'Числа позиции банка не найдены во фрагменте: {", ".join(sorted(unsupported))}', path))
        if st.get('text') and similarity(st['text'], chunk_text) < 0.03:
            issues.append(_issue('bank_view_drift', 'warning', 'Пересказ слабо совпадает с фрагментом аналитики', path))

    # противоречие: одновременно риск и возможность с одним и тем же текстом
    rtexts = [s.get('text', '') for s in insight.get('risks', [])]
    for i, o in enumerate(insight.get('opportunities', [])):
        if any(similarity(o.get('text', ''), r) > 0.8 for r in rtexts):
            issues.append(_issue('contradiction', 'warning', 'Одно и то же утверждение и риск, и возможность', f'opportunities[{i}]'))

    blocking = [x for x in issues if x['severity'] == 'blocking']
    return {'passed': not blocking, 'issues': issues, 'blocking': len(blocking)}


def prune(insight: dict, report: dict) -> dict:
    """Консервативная доработка без LLM: удалить утверждения с блокирующими замечаниями."""
    bad = {x['path'] for x in report['issues'] if x['severity'] == 'blocking'}
    removed = []
    for block in LIST_BLOCKS:
        kept = []
        for i, st in enumerate(insight.get(block, [])):
            if f'{block}[{i}]' in bad:
                removed.append(st.get('text', '')[:80])
            else:
                kept.append(st)
        insight[block] = kept
    bv = insight.get('bank_view') or {}
    if bv.get('statements'):
        kept = [st for i, st in enumerate(bv['statements']) if f'bank_view.statements[{i}]' not in bad]
        removed += [st.get('text', '')[:80] for st in bv['statements'] if st not in kept]
        bv['statements'] = kept
        if not kept:
            bv['status'] = 'not_found'
            bv['note'] = 'Позиция банка не подтвердилась проверкой источников и скрыта.'
    if removed:
        insight.setdefault('limitations', []).append(
            f'Проверка удалила {len(removed)} утверждени{"е" if len(removed) == 1 else "я"} без достаточного подтверждения источниками.')
    return insight
