"""A04: объяснимое ранжирование новостей под компанию.

score = Σ weight_i · component_i (каждый компонент в [0, 1]) × свежесть.
Компоненты не дублируют друг друга: отрасль (прямое совпадение сектора), каналы влияния
(продукты/ВЭД/персонал — через какие механизмы событие касается компании), контрагенты
(отрасли платёжных партнёров, 1 шаг графа), регион, макрозначимость события, покрытие
аналитикой банка. Правил вида «для такого-то ID показать новость» нет: всё считается из
профиля и события. Неизвестные признаки не добавляют баллов и снижают уверенность.
"""
import math
from datetime import datetime, timezone

from .events import parse_dt
from .profiles import CHANNELS
from .sectors import label

WEIGHTS = {'sector': 0.27, 'channel': 0.30, 'counterparty': 0.12, 'region': 0.08, 'macro': 0.15, 'bank': 0.08}
LABELS = {
    'sector': 'Отрасль компании', 'channel': 'Каналы влияния на компанию', 'counterparty': 'Контрагенты (граф платежей)',
    'region': 'Регион регистрации', 'macro': 'Макрозначимость события', 'bank': 'Есть позиция в аналитике банка',
}
MACRO_TYPES = {'key_rate', 'inflation', 'fx', 'gdp_macro', 'budget_tax', 'labor_market', 'credit_market'}
LEVELS = [(0.45, 'high'), (0.3, 'medium'), (0.18, 'low')]
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


def score(profile: dict, event: dict, bank_cov: float = 0.0, published_at=None, now: datetime | None = None) -> dict:
    comps = []
    if not event.get('business_relevant', True):
        return {'score': 0.0, 'level': 'none', 'components': [], 'reasons': ['Публикация не относится к бизнес-событиям'],
                'why_short': 'Не относится к бизнесу', 'confidence': 'high', 'profile_warnings': []}

    # 1. отрасль: доля секторов события, совпавших с секторами компании (первый сектор компании — основной)
    comp_sectors = [s['key'] for s in profile['sectors']]
    ev_sectors = event.get('sectors', [])
    matched = [s for s in ev_sectors if s in comp_sectors]
    sector_v = 0.0
    if matched:
        sector_v = 1.0 if comp_sectors and matched[0] == comp_sectors[0] or len(matched) > 1 else 0.75
    if event.get('event_type') in MACRO_TYPES and sector_v:
        sector_v *= 0.3  # для макрособытия упоминание отрасли в тексте — фон, а не прямое отраслевое событие
    comps.append(('sector', sector_v, (f'Событие касается отрасли компании: {", ".join(label(s) for s in matched)}'
                                       if matched else 'Отрасль события не совпадает с ОКВЭД компании'),
                  ['P:MAINOKVED_CODE'] if matched else []))

    # 2. каналы: max(влияние события по каналу × сила канала у компании) + бонус за второй канал
    ch_hits = []
    for ch, w in event.get('channels', {}).items():
        c = profile['channels'].get(ch)
        if c:
            ch_hits.append((w * c['strength'], ch, c))
    ch_hits.sort(key=lambda x: -x[0])
    channel_v = 0.0
    if ch_hits:
        channel_v = min(1.0, ch_hits[0][0] + (0.15 * ch_hits[1][0] if len(ch_hits) > 1 else 0))
    reason = '; '.join(f'{c["label"]}: {c["notes"][0]}' for _, _, c in ch_hits[:2]) if ch_hits else \
        'Нет подтверждённых данными механизмов влияния на компанию'
    comps.append(('channel', channel_v, reason, [b for _, _, c in ch_hits[:2] for b in c['basis']]))

    # 3. контрагенты: доля платежей с партнёрами из отраслей события (исходящие и входящие)
    cp_v, cp_reason, cp_ev = 0.0, 'Отрасли контрагентов не связаны с событием', []
    if ev_sectors:
        out_share = sum(x['share'] for x in profile['derived']['payments_out']['sectors'] if x['key'] in ev_sectors)
        in_share = sum(x['share'] for x in profile['derived']['payments_in']['sectors'] if x['key'] in ev_sectors)
        best = max(out_share, in_share)
        if best >= 0.02:
            cp_v = min(1.0, best * 2.5) * (0.3 if event.get('event_type') in MACRO_TYPES else 1.0)
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
                   'contribution': round(WEIGHTS[k] * v * fr, 4), 'reason': r, 'evidence': ev}
                  for k, v, r, ev in comps]
    reasons = [c['reason'] for c in sorted(components, key=lambda c: -c['contribution']) if c['value'] > 0][:3]
    why = _why_short(event, ch_hits, matched, cp_v, cp_reason)
    return {'score': total, 'level': level, 'components': components, 'reasons': reasons, 'why_short': why,
            'confidence': confidence, 'freshness': round(fr, 3), 'profile_warnings': warnings,
            'channels_hit': [{'key': ch, 'label': CHANNELS[ch], 'impact': round(v, 3)} for v, ch, _ in ch_hits[:3]]}


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
