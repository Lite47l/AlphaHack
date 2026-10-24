"""Профили компаний и каналы чувствительности к событиям (бизнес-контекст клиента).

Канал — объяснимый механизм, через который внешнее событие может затронуть компанию
(стоимость долга, доходность ликвидности, ФОТ, внешняя торговля, спрос, топливо...).
Сила канала считается только из наблюдаемых полей профиля и платёжного графа; у каждого
канала есть basis — ссылки на поля (P:<FIELD>) и графовые факты (G:<key>), которые
затем попадают в объяснение ранжирования и в трассировку инсайта.
"""
import json
import logging
from pathlib import Path

from .config import settings
from .data_build import FILES, PRODUCT_FIELDS, build_profiles

log = logging.getLogger(__name__)

CHANNELS = {
    'cost_of_debt': 'Стоимость заёмного финансирования',
    'liquidity_yield': 'Доходность свободной ликвидности',
    'payroll': 'Расходы на персонал',
    'foreign_trade': 'Внешнеэкономическая деятельность и курс',
    'consumer_demand': 'Потребительский спрос',
    'fuel_costs': 'Цены на топливо и энергию',
    'metals_prices': 'Цены на металлы',
    'construction_cycle': 'Строительный цикл и недвижимость',
    'state_budget': 'Госрасходы и налоги',
    'agri_prices': 'Цены на агропродукцию',
    'financial_markets': 'Финансовые рынки и регулирование',
}
WORKERS_WEIGHT = {'Более 251': 0.6, '101-250': 0.4, '16-100': 0.2, 'Менее 15': 0.05}


def _share(dist: list[dict], keys: set[str]) -> float:
    return sum(x['share'] for x in dist if x['key'] in keys)


def channels_for(profile: dict) -> dict:
    obs = {k: v['value'] for k, v in profile['observed'].items()}
    sectors = {s['key'] for s in profile['sectors']}
    pout = profile['derived']['payments_out']
    pin = profile['derived']['payments_in']
    ch: dict[str, dict] = {}

    def add(name, strength, basis, note):
        cur = ch.setdefault(name, {'key': name, 'label': CHANNELS[name], 'strength': 0.0, 'basis': [], 'notes': []})
        cur['strength'] = round(min(1.0, max(cur['strength'], strength) + (0.1 if cur['strength'] and strength else 0)), 3)
        cur['basis'] += [b for b in basis if b not in cur['basis']]
        cur['notes'].append(note)

    debt = [(f, w) for f, w in (('CL_PRODUCT_LOA_MARK', 0.9), ('CL_PRODUCT_LEA_MARK', 0.6),
                                ('FACTORING_MARK', 0.5), ('CL_PRODUCT_GAR_MARK', 0.35)) if obs.get(f) == 1]
    if debt:
        add('cost_of_debt', max(w for _, w in debt) + 0.05 * (len(debt) - 1), [f'P:{f}' for f, _ in debt],
            'В банке есть ' + ', '.join(PRODUCT_FIELDS[f].lower() for f, _ in debt))
    if obs.get('CL_PRODUCT_DEP_MARK') == 1:
        add('liquidity_yield', 0.7, ['P:CL_PRODUCT_DEP_MARK'], 'Есть депозитные продукты')
    w = WORKERS_WEIGHT.get(obs.get('AMOUNT_WORKERS_FNS_GRADATION') or '', 0)
    if w >= 0.2:
        add('payroll', w, ['P:AMOUNT_WORKERS_FNS_GRADATION'], f'Численность (ФНС): {obs.get("AMOUNT_WORKERS_FNS_GRADATION")}')
    if obs.get('CL_PRODUCT_ZPP_MARK') == 1:
        add('payroll', 0.4, ['P:CL_PRODUCT_ZPP_MARK'], 'Есть зарплатный проект')
    if obs.get('FTS_FLAG') == 1:
        countries = obs.get('FTS_COUNTRY_NAME') or 'страны не указаны'
        add('foreign_trade', 0.8, ['P:FTS_FLAG', 'P:FTS_COUNTRY_NAME'],
            f'Компания есть в базе ФТС ({countries}); направление операций (импорт/экспорт) в данных не указано')
    cp_fts = sum(x['share'] for x in pout['fts_countries'][:3]) if pout['fts_countries'] else 0
    if cp_fts >= 0.1:
        add('foreign_trade', 0.35, ['G:payments_out.fts_countries'],
            f'Заметная часть исходящих платежей идёт контрагентам с ВЭД (≈{cp_fts:.0%} объёма)')
    if sectors & {'retail', 'hospitality'}:
        add('consumer_demand', 1.0, ['P:MAINOKVED_CODE'], 'Компания работает с конечным потребителем')
    elif sectors & {'consumer_goods', 'auto'} or (sectors & {'agri_food'} and sectors & {'wholesale'}):
        add('consumer_demand', 0.6, ['P:MAINOKVED_CODE'], 'Продукция компании ориентирована на потребительский рынок')
    retail_in = _share(pin['sectors'], {'retail', 'hospitality'})
    if retail_in >= 0.05:
        add('consumer_demand', 0.4, ['G:payments_in.sectors'],
            f'Часть входящих платежей — от розницы/общепита (≈{retail_in:.0%})')
    if 'fuel_energy' in sectors:
        add('fuel_costs', 0.9, ['P:MAINOKVED_CODE'], 'Цены на топливо и энергию напрямую определяют выручку и маржу')
    elif sectors & {'transport', 'agri_food', 'construction'}:
        add('fuel_costs', 0.5, ['P:MAINOKVED_CODE'], 'Топливо — существенная статья затрат для отрасли')
    fuel_out = _share(pout['sectors'], {'fuel_energy'})
    if fuel_out >= 0.05:
        add('fuel_costs', min(0.8, 0.3 + fuel_out), ['G:payments_out.sectors'],
            f'Платежи контрагентам из топливного сектора ≈{fuel_out:.0%} исходящего объёма')
    if 'metals_mining' in sectors:
        add('metals_prices', 0.9, ['P:MAINOKVED_CODE'], 'Цены на металлы определяют выручку')
    elif sectors & {'construction', 'machinery', 'auto'}:
        add('metals_prices', 0.45, ['P:MAINOKVED_CODE'], 'Металл — входящее сырьё для отрасли')
    if sectors & {'construction', 'real_estate'}:
        add('construction_cycle', 0.9, ['P:MAINOKVED_CODE'], 'Отрасль зависит от строительного цикла и ипотеки')
    constr_in = _share(pin['sectors'], {'construction', 'real_estate'})
    if constr_in >= 0.1:
        add('construction_cycle', 0.4, ['G:payments_in.sectors'], f'Покупатели из строительства ≈{constr_in:.0%} входящих платежей')
    if sectors & {'construction', 'utilities', 'public'}:
        add('state_budget', 0.5, ['P:MAINOKVED_CODE'], 'Отрасль чувствительна к госзаказу и бюджетным расходам')
    if 'agri_food' in sectors:
        add('agri_prices', 0.8, ['P:MAINOKVED_CODE'], 'Цены на агросырьё влияют на закупки или выручку')
    if 'finance' in sectors:
        add('financial_markets', 0.8, ['P:MAINOKVED_CODE'], 'Финансовая деятельность зависит от рынков и регулирования')
    return ch


class ProfileStore:
    def __init__(self, data: dict, source: str):
        self.version = data['version']
        self.source = source
        self.meta = {k: v for k, v in data.items() if k != 'profiles'}
        self.profiles = {p['company_id']: p for p in data['profiles']}
        for p in self.profiles.values():
            p['channels'] = channels_for(p)
        self.regions = sorted({p['observed']['REGION']['value'] for p in self.profiles.values() if p['observed']['REGION']['value']})

    @classmethod
    def load(cls) -> 'ProfileStore':
        store = cls._load()
        if settings.include_edge_cases and not store.source.startswith('synthetic'):
            store.add_edge_cases()
        return store

    def add_edge_cases(self):
        """Синтетические пограничные случаи рядом с реальными данными: в реальной выборке нет компаний с пропусками
        ключевых полей, а сервис должен показывать устойчивость к неполным и неоднозначным профилям."""
        synth = build_profiles(settings.data_dir / 'synthetic', 15e9)
        for p in synth['profiles']:
            if p['company_id'] in ('U_9000008', 'U_9000009'):
                kind = 'неполный профиль' if p['profile_status'] == 'matched' else 'неоднозначный ID'
                p['display_name'] = f'Синтетический пример: {kind}'
                p['data_notes'].insert(0, 'Синтетическая компания из data/synthetic — пограничный случай для проверки устойчивости, не клиент из датасета.')
                p['channels'] = channels_for(p)
                self.profiles[p['company_id']] = p

    @classmethod
    def _load(cls) -> 'ProfileStore':
        """Реальные данные (RAW_DATA_DIR или data/raw) → готовый data/generated → синтетика."""
        state = settings.state_dir / 'profiles.json'
        candidates = [Path(settings.raw_dir)] if settings.raw_dir else []
        candidates.append(settings.data_dir / 'raw')
        for raw in candidates:
            if all((raw / f).is_file() for f in FILES.values()):
                if state.is_file():
                    data = json.loads(state.read_text(encoding='utf-8'))
                    if data.get('raw_dir') == str(raw) and data.get('min_revenue') == settings.min_revenue:
                        return cls(data, f'real:{raw}')
                log.info('building profiles from %s', raw)
                data = build_profiles(raw, settings.min_revenue)
                data['raw_dir'] = str(raw)
                state.parent.mkdir(parents=True, exist_ok=True)
                state.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
                return cls(data, f'real:{raw}')
        gen = settings.data_dir / 'generated' / 'profiles.json'
        if gen.is_file():
            return cls(json.loads(gen.read_text(encoding='utf-8')), f'generated:{gen}')
        synth = settings.data_dir / 'synthetic'
        log.warning('real data not found, using synthetic dataset %s', synth)
        return cls(build_profiles(synth, settings.min_revenue), f'synthetic:{synth}')

    def get(self, company_id: str) -> dict | None:
        return self.profiles.get(company_id)

    def summary(self, p: dict) -> dict:
        obs = p['observed']
        key_missing = [f for f in ('MAINOKVED_CODE', 'REVENUE_COMPANY', 'REGION', 'CL_PRODUCT_LOA_MARK',
                                   'AMOUNT_WORKERS_FNS_GRADATION') if f in p['missing_fields']]
        return {
            'company_id': p['company_id'], 'display_name': p['display_name'], 'subtitle': p['subtitle'],
            'okved_code': obs['MAINOKVED_CODE']['value'], 'region': obs['REGION']['value'],
            'revenue': obs['REVENUE_COMPANY']['value'], 'cl_type': obs['CL_TYPE']['value'],
            'sectors': p['sectors'], 'profile_status': p['profile_status'],
            'completeness': 'incomplete' if key_missing or p['profile_status'] != 'matched' else 'complete',
            'key_missing': key_missing,
            'top_channels': [c['label'] for c in sorted(p['channels'].values(), key=lambda c: -c['strength'])[:3]],
        }

    def search(self, query: str = '', limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        q = query.strip().lower()
        items = sorted(self.profiles.values(), key=lambda p: -(p['observed']['REVENUE_COMPANY']['value'] or 0))
        if q:
            items = [p for p in items if q in p['company_id'].lower() or q in (p['subtitle'] or '').lower()
                     or q in p['display_name'].lower()
                     or q in (p['observed']['REGION']['value'] or '').lower()
                     or any(q in s['label'].lower() for s in p['sectors'])]
        return [self.summary(p) for p in items[offset:offset + limit]], len(items)

    def fact(self, company_id: str, ref: str) -> dict | None:
        """Разрешение ссылок P:<FIELD> и G:<path> в значение с происхождением (для источников и валидатора)."""
        p = self.get(company_id)
        if not p:
            return None
        kind, _, key = ref.partition(':')
        if kind == 'P' and key in p['observed']:
            o = p['observed'][key]
            return {'id': ref, 'type': 'profile', 'title': o['title'], 'value': o['value'], 'origin': o['source']}
        if kind == 'G':
            node = p['derived']
            for part in key.split('.'):
                if not isinstance(node, dict) or part not in node:
                    return None
                node = node[part]
            return {'id': ref, 'type': 'graph', 'title': GRAPH_TITLES.get(key, key), 'value': node,
                    'origin': 'df_Uid_payment_hack.csv / df_Fid_Uid_link_hack.csv (агрегаты, 1 шаг графа)'}
        return None


GRAPH_TITLES = {
    'payments_out.sectors': 'Отрасли получателей исходящих платежей',
    'payments_in.sectors': 'Отрасли плательщиков входящих платежей',
    'payments_out.fts_countries': 'Страны ФТС у получателей платежей',
    'payments_in.fts_countries': 'Страны ФТС у плательщиков',
    'payments_out.top5_share': 'Доля топ-5 получателей в исходящих платежах',
    'payments_in.top5_share': 'Доля топ-5 плательщиков во входящих платежах',
    'payments_out.counterparties': 'Число получателей платежей',
    'payments_in.counterparties': 'Число плательщиков',
    'payments_out.regions': 'Регионы получателей платежей',
    'group': 'Группа компаний',
    'revenue_rank': 'Позиция по выручке в классе ОКВЭД (в выборке)',
    'persons': 'Связанные физлица',
}
