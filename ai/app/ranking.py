"""A04: объяснимое ранжирование новостей под компанию.

score = Σ weight_i · component_i (каждый компонент в [0, 1]) × свежесть.
Компоненты не дублируют друг друга: отрасль (прямое совпадение сектора), каналы влияния
(продукты/ВЭД/персонал — через какие механизмы событие касается компании), контрагенты
(отрасли платёжных партнёров, 1 шаг графа), регион, макрозначимость события, покрытие
аналитикой банка. Правил вида «для такого-то ID показать новость» нет: всё считается из
профиля и события. Неизвестные признаки не добавляют баллов и снижают уверенность.

Уточнения по итогам офлайн-оценки (docs/evaluation_report.md): макрособытие, бьющее по основному каналу
компании (ставка → кредит, курс → ВЭД), считается для неё прямым; контрагенты не дублируют отрасль и требуют
весомого объёма платежей; агро-события различаются по товарным группам ОКВЭД; зарубежные и чужие региональные
события понижаются. Свежесть считается от переданного now (лента передаёт время самой свежей новости).
"""
import math
from datetime import datetime, timezone

from .events import parse_dt
from .profiles import CHANNELS
from .sectors import commodities_for_okved, label

WEIGHTS = {'sector': 0.27, 'channel': 0.30, 'counterparty': 0.12, 'region': 0.08, 'macro': 0.15, 'bank': 0.08}
LABELS = {
    'sector': 'Отрасль компании', 'channel': 'Каналы влияния на компанию', 'counterparty': 'Контрагенты (граф платежей)',
    'region': 'Регион регистрации', 'macro': 'Макрозначимость события', 'bank': 'Есть позиция в аналитике банка',
}
MACRO_TYPES = {'key_rate', 'inflation', 'fx', 'gdp_macro', 'budget_tax', 'labor_market', 'credit_market'}
LEVELS = [(0.45, 'high'), (0.3, 'medium'), (0.18, 'low')]
MACRO_PRIMARY_W = 0.8       # канал события с весом ≥ 0.8 — основной механизм передачи макрособытия
COMMODITY_MISMATCH = 0.4    # агро-событие о чужой товарной группе
CP_MIN_SIDE_SHARE, CP_MIN_COUNT = 0.1, 20  # весомость стороны платежей для компонента «контрагенты»
GEO_FOREIGN, GEO_OTHER_REGION = 0.5, 0.75
KEY_FIELDS = ('MAINOKVED_CODE', 'REGION', 'CL_PRODUCT_LOA_MARK', 'AMOUNT_WORKERS_FNS_GRADATION', 'REVENUE_COMPANY')


def freshness(published_at, now: datetime | None = None) -> float:
    dt = parse_dt(published_at)
    if not dt:
        return 0.8
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = max(0.0, (now - dt).total_seconds() / 86400)
    return 0.6 + 0.4 * math.exp(-age / 10)


def latest_time(news: list[dict]) -> datetime | None:
    """Время самой свежей новости набора — опорное «сейчас» для свежести (None — использовать текущее время)."""
    return max((dt for n in news if (dt := parse_dt(n.get('published_at')))), default=None)


def score(profile: dict, event: dict, bank_cov: float = 0.0, published_at=None, now: datetime | None = None) -> dict:
    comps = []
    if not event.get('business_relevant', True):
        return {'score': 0.0, 'level': 'none', 'components': [], 'reasons': ['Публикация не относится к бизнес-событиям'],
                'why_short': 'Не относится к бизнесу', 'confidence': 'high', 'profile_warnings': []}

    is_macro = event.get('event_type') in MACRO_TYPES
    adjustments = []

    # товарная группа: «урожай картофеля» — не событие зернотрейдера (ОКВЭД → товарные группы, sectors.py)
    ev_comm = set(event.get('commodities') or [])
    comp_comm = set(commodities_for_okved(profile['observed'].get('MAINOKVED_CODE', {}).get('value')))
    comm_mismatch = bool(ev_comm and comp_comm and 'all' not in comp_comm and not ev_comm & comp_comm)
    if comm_mismatch:
        adjustments.append('Товарная группа события не совпадает с профилем компании по ОКВЭД')

    # 1. отрасль: доля секторов события, совпавших с секторами компании (первый сектор компании — основной)
    comp_sectors = [s['key'] for s in profile['sectors']]
    ev_sectors = event.get('sectors', [])
    matched = [s for s in ev_sectors if s in comp_sectors]
    sector_v = 0.0
    if matched:
        sector_v = 1.0 if comp_sectors and matched[0] == comp_sectors[0] or len(matched) > 1 else 0.75
    if is_macro and sector_v:
        sector_v *= 0.3  # для макрособытия упоминание отрасли в тексте — фон, а не прямое отраслевое событие
    if comm_mismatch:
        sector_v *= COMMODITY_MISMATCH

    # 2. каналы: max(влияние события по каналу × сила канала у компании) + бонус за второй канал
    ch_hits = []
    for ch, w in event.get('channels', {}).items():
        c = profile['channels'].get(ch)
        if c:
            if ch == 'agri_prices' and comm_mismatch:
                w *= COMMODITY_MISMATCH
            ch_hits.append((w * c['strength'], ch, c, w))
    ch_hits.sort(key=lambda x: -x[0])
    channel_v = 0.0
    if ch_hits:
        channel_v = min(1.0, ch_hits[0][0] + (0.15 * ch_hits[1][0] if len(ch_hits) > 1 else 0))
    # макрособытие, бьющее по основному механизму передачи (ставка → кредит у компании, курс → ВЭД),
    # для этой компании прямое — как отраслевое. Косвенные каналы (спрос, ФОТ) этого не дают.
    direct_macro = max((v for v, _, _, w in ch_hits if w >= MACRO_PRIMARY_W), default=0.0) if is_macro else 0.0
    sector_note = None
    if direct_macro > sector_v:
        sector_v = direct_macro
        sector_note = 'Макрособытие напрямую затрагивает подтверждённый продукт/канал компании'
    comps.append(('sector', sector_v, sector_note or (
        f'Событие касается отрасли компании: {", ".join(label(s) for s in matched)}'
        if matched else 'Отрасль события не совпадает с ОКВЭД компании'),
        ['P:MAINOKVED_CODE'] if matched else []))
    reason = '; '.join(f'{c["label"]}: {c["notes"][0]}' for _, _, c, _ in ch_hits[:2]) if ch_hits else \
        'Нет подтверждённых данными механизмов влияния на компанию'
    comps.append(('channel', channel_v, reason, [b for _, _, c, _ in ch_hits[:2] for b in c['basis']]))

    # 3. контрагенты: доля платежей с партнёрами из отраслей события (исходящие и входящие).
    # Не дублирует отрасль (собственные сектора компании не считаются) и учитывается, только если
    # сторона платежей весома: ≥10% общего оборота компании и ≥20 платежей.
    cp_v, cp_reason, cp_ev = 0.0, 'Отрасли контрагентов не связаны с событием', []
    cp_sectors = [s for s in ev_sectors if s not in comp_sectors]
    pout, pin = profile['derived']['payments_out'], profile['derived']['payments_in']
    total_amt = (pout.get('amount') or 0) + (pin.get('amount') or 0)

    def _side_ok(side):
        return total_amt > 0 and (side.get('amount') or 0) >= CP_MIN_SIDE_SHARE * total_amt \
            and (side.get('count') or 0) >= CP_MIN_COUNT

    if cp_sectors:
        out_share = sum(x['share'] for x in pout['sectors'] if x['key'] in cp_sectors) if _side_ok(pout) else 0.0
        in_share = sum(x['share'] for x in pin['sectors'] if x['key'] in cp_sectors) if _side_ok(pin) else 0.0
        best = max(out_share, in_share)
        if best >= 0.02:
            cp_v = min(1.0, best * 2.5) * (0.3 if is_macro else 1.0)
            side = 'получателей платежей (возможные поставщики)' if out_share >= in_share else 'плательщиков (возможные покупатели)'
            cp_reason = f'≈{best:.0%} объёма платежей приходится на {side} из отраслей события'
            cp_ev = ['G:payments_out.sectors' if out_share >= in_share else 'G:payments_in.sectors']
    comps.append(('counterparty', cp_v, cp_reason, cp_ev))

    # 4. регион
    region = profile['observed']['REGION']['value']
    reg_v = 1.0 if region and region in event.get('regions', []) else 0.0
    comps.append(('region', reg_v, f'Событие в регионе регистрации компании ({region})' if reg_v else
                  ('Регион события не указан или не совпадает' if region else 'Регион компании неизвестен'),
                  ['P:REGION'] if reg_v else []))

    # 5. макрозначимость (ставка, инфляция и т.п. касаются всех, но в разной мере)
    macro_v = float(event.get('macro_importance', 0))
    comps.append(('macro', macro_v, f'{event.get("event_label", "")}: общеэкономический фактор' if macro_v >= 0.4 else
                  'Локальное/отраслевое событие', []))

    # 6. покрытие аналитикой банка
    comps.append(('bank', bank_cov, 'По теме есть материалы аналитики Альфа-Банка' if bank_cov >= 0.35 else
                  'Позиция банка по теме не найдена или слабо выражена', []))

    raw = sum(WEIGHTS[k] * v for k, v, _, _ in comps)
    # отсутствие связи с компанией (ни отрасли, ни каналов, ни контрагентов) — понижающий множитель
    personal = max(sector_v, channel_v, cp_v)
    if personal < 0.2:
        raw *= 0.6
    # география: событие только иностранного рынка без российского контекста и региональное событие в чужом
    # регионе (кроме макро) — понижающие множители
    geo_m = 1.0
    if event.get('geo_scope') == 'foreign':
        geo_m = GEO_FOREIGN
        adjustments.append('Событие касается зарубежного рынка без российского контекста')
    elif event.get('geo_scope') == 'regional' and not reg_v and not is_macro:
        geo_m = GEO_OTHER_REGION
        adjustments.append('Региональное событие вне региона регистрации компании')
    raw *= geo_m
    fr = freshness(published_at or event.get('published_at'), now)
    total = round(raw * fr, 4)
    level = next((lv for th, lv in LEVELS if total >= th), 'none')

    missing = [f for f in KEY_FIELDS if f in profile['missing_fields']]
    warnings = []
    if profile['profile_status'] != 'matched':
        warnings.append('ID компании встречается в справочнике несколько раз — профиль не используется для персонализации')
    if missing:
        titles = [profile['observed'][f]['title'] for f in missing]
        warnings.append('Неполный профиль: нет ' + ', '.join(t.lower() for t in titles))
    confidence = 'high' if not missing and personal >= 0.5 else ('medium' if len(missing) <= 1 else 'low')

    components = [{'key': k, 'label': LABELS[k], 'value': round(v, 3), 'weight': WEIGHTS[k],
                   'contribution': round(WEIGHTS[k] * v * fr * geo_m, 4), 'reason': r, 'evidence': ev}
                  for k, v, r, ev in comps]
    reasons = [c['reason'] for c in sorted(components, key=lambda c: -c['contribution']) if c['value'] > 0][:3]
    why = _why_short(event, ch_hits, matched, cp_v, cp_reason)
    return {'score': total, 'level': level, 'components': components, 'reasons': reasons, 'why_short': why,
            'confidence': confidence, 'freshness': round(fr, 3), 'profile_warnings': warnings, 'adjustments': adjustments,
            'channels_hit': [{'key': ch, 'label': CHANNELS[ch], 'impact': round(v, 3)} for v, ch, _, _ in ch_hits[:3]]}


def _why_short(event, ch_hits, matched, cp_v, cp_reason) -> str:
    if ch_hits and ch_hits[0][0] >= 0.3:
        c = ch_hits[0][2]
        return f'{c["label"]} — {c["notes"][0][0].lower()}{c["notes"][0][1:]}'
    if matched:
        return f'Затрагивает отрасль компании: {label(matched[0]).lower()}'
    if cp_v:
        return cp_reason[0].upper() + cp_reason[1:]
    if event.get('macro_importance', 0) >= 0.5:
        return f'{event.get("event_label")}: общеэкономический фактор для бизнеса'
    return 'Слабая связь с профилем компании'
