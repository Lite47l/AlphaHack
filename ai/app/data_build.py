"""L04/L05/A02: структурированные профили компаний сегмента и графовый контекст (1 шаг).

Вход — три CSV организаторов (или синтетические в том же формате):
  df_Uid_data_hack.csv, df_Fid_Uid_link_hack.csv, df_Uid_payment_hack.csv  (`;`, UTF-8-sig)
Выход — profiles.json: профили компаний с выручкой ≥ порога (крупный бизнес по кейсу — 15 млрд).

Принципы (согласованы с L03/A01):
- прямые наблюдения (observed) отделены от вычисленных признаков (derived), у каждого — источник;
- пропуск остаётся пропуском и попадает в missing_fields, а не заменяется нулём;
- повторяющийся ID компании → profile_status=ambiguous, спорные атрибуты не выбираются;
- платёж не доказывает роль поставщика/покупателя, связь физлица не доказывает владение;
- период и единицы платежей в данных не указаны — суммы показываются как «объём в ед. датасета».

  python -m app.data_build --raw <папка с CSV> --out profiles.json [--min-revenue 15e9]
"""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from .sectors import label, sectors_for_okved

FILES = {
    'companies': 'df_Uid_data_hack.csv',
    'persons': 'df_Fid_Uid_link_hack.csv',
    'payments': 'df_Uid_payment_hack.csv',
}
PRODUCT_FIELDS = {
    'CL_PRODUCT_RKO_MARK': 'Расчётно-кассовое обслуживание',
    'CL_PRODUCT_GAR_MARK': 'Банковские гарантии',
    'CL_PRODUCT_LOA_MARK': 'Кредитные продукты',
    'CL_PRODUCT_LEA_MARK': 'Лизинг',
    'CL_PRODUCT_DEP_MARK': 'Депозиты',
    'CL_PRODUCT_ZPP_MARK': 'Зарплатный проект',
    'FACTORING_MARK': 'Факторинг',
}
OBSERVED_FIELDS = {
    'MAINOKVED_CODE': 'Код основного ОКВЭД', 'MAINOKVED_NAME': 'Основной вид деятельности',
    'ORG_TYPE': 'Тип организации', 'OKFS_NAME': 'Форма собственности',
    'COMPANY_AGE_YEARS_GRADATION': 'Возраст компании, лет', 'ECO_MARK_LABEL': 'Стадия развития бизнеса',
    'REVENUE_COMPANY': 'Годовая выручка', 'AMOUNT_WORKERS_FNS_GRADATION': 'Работники (ФНС)',
    'AMOUNT_WORKERS_SPARK_GRADATION': 'Работники (СПАРК)', 'CL_TYPE': 'Тип клиента',
    'NEGATIVEMARK': 'Признак ключевого собственника', 'FTS_FLAG': 'Есть данные в базе ФТС',
    'FTS_COUNTRY_NAME': 'Страны в данных ФТС', 'GROUP_ID': 'Группа компаний',
    'CITY': 'Город регистрации', 'REGION': 'Регион регистрации', **PRODUCT_FIELDS,
}
CL_TYPE_LABEL = {'CLIENT': 'Действующий клиент', 'CLOSE_CLIENT': 'Закрытый клиент', 'PROSPECT': 'Потенциальный клиент'}
PERSON_MARKERS = {'Неопределенный город', 'Не определено', 'ИНН не определён'}


def _read(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=';', dtype='string', encoding='utf-8-sig', keep_default_na=False)
    for c in df.columns:
        df[c] = df[c].str.strip().replace('', pd.NA)
    return df


def _num(v):
    if v is None or pd.isna(v):
        return None
    try:
        f = float(str(v).replace(',', '.'))
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def _flag(v):
    n = _num(v)
    return None if n is None else int(n)


def _val(v):
    return None if v is None or pd.isna(v) else str(v)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def build_profiles(raw_dir: str | Path, min_revenue: float = 15e9, top_n: int = 10) -> dict:
    raw_dir = Path(raw_dir)
    paths = {k: raw_dir / v for k, v in FILES.items()}
    for k, p in paths.items():
        if not p.is_file():
            raise FileNotFoundError(f'нет файла {p.name} в {raw_dir}')
    comp = _read(paths['companies'])
    persons = _read(paths['persons'])
    pay = _read(paths['payments'])
    pay['amt'] = pd.to_numeric(pay.PAY_AMT, errors='coerce')
    pay['cnt'] = pd.to_numeric(pay.PAY_CNT, errors='coerce')

    dup = comp.SYNTHETIC_U.duplicated(keep=False)
    ambiguous_ids = set(comp.loc[dup, 'SYNTHETIC_U'])
    uniq = comp.loc[~dup].set_index('SYNTHETIC_U')
    comp['rev'] = pd.to_numeric(comp.REVENUE_COMPANY, errors='coerce')
    uniq_rev = pd.to_numeric(uniq.REVENUE_COMPANY, errors='coerce')

    # Позиция по выручке внутри класса ОКВЭД (первые 5 знаков, напр. 46.71) среди компаний выборки
    okved_cls = uniq.MAINOKVED_CODE.str.slice(0, 5)
    rank_df = pd.DataFrame({'cls': okved_cls, 'rev': uniq_rev}).dropna()
    rank_df['rank'] = rank_df.groupby('cls').rev.rank(ascending=False, method='min')
    cls_size = rank_df.groupby('cls').size()

    group_sizes = comp.groupby('GROUP_ID').SYNTHETIC_U.nunique()
    group_rev = comp.drop_duplicates('SYNTHETIC_U').groupby('GROUP_ID').rev.sum(min_count=1)

    selected = sorted(set(uniq_rev[uniq_rev >= min_revenue].index) | {i for i in ambiguous_ids
                      if comp.loc[comp.SYNTHETIC_U == i, 'rev'].max() >= min_revenue})
    sel = set(selected)
    rel = pay[pay.PAYER.isin(sel) | pay.BENEFICIARY.isin(sel)].copy()
    prs = persons[persons.SYNTHETIC_U.isin(sel)].copy()
    person_companies = persons.groupby('SYNTHETIC_F').SYNTHETIC_U.apply(lambda s: sorted(set(s)))

    def cp_attrs(cid):
        if cid in uniq.index:
            r = uniq.loc[cid]
            return {'okved_code': _val(r.MAINOKVED_CODE), 'okved_name': _val(r.MAINOKVED_NAME),
                    'region': _val(r.REGION), 'fts_countries': _val(r.FTS_COUNTRY_NAME), 'in_profile': True,
                    'sectors': sectors_for_okved(_val(r.MAINOKVED_CODE))}
        return {'okved_code': None, 'okved_name': None, 'region': None, 'fts_countries': None,
                'in_profile': cid in ambiguous_ids, 'sectors': []}

    attrs_cache: dict[str, dict] = {}

    def attrs(cid):
        if cid not in attrs_cache:
            attrs_cache[cid] = cp_attrs(cid)
        return attrs_cache[cid]

    def side(df, key_self, key_other, total_amt):
        """Агрегаты одной стороны платежей (исходящие или входящие) без самопереводов."""
        ext = df[df[key_other] != df[key_self]]
        by_cp = ext.groupby(key_other).agg(amt=('amt', 'sum'), cnt=('cnt', 'sum')).sort_values('amt', ascending=False)
        amt_total = float(by_cp.amt.sum()) if len(by_cp) else 0.0
        top = []
        for cid, row in by_cp.head(top_n).iterrows():
            a = attrs(cid)
            top.append({'company_id': cid, 'amt': float(row.amt), 'cnt': _num(row.cnt),
                        'share': round(float(row.amt) / amt_total, 4) if amt_total > 0 else None,
                        'okved_code': a['okved_code'], 'okved_name': a['okved_name'], 'region': a['region'],
                        'in_profile': a['in_profile']})
        sectors, regions, countries, unknown = {}, {}, {}, 0.0
        for cid, row in by_cp.iterrows():
            a = attrs(cid)
            amt = float(row.amt) if pd.notna(row.amt) else 0.0
            if not a['sectors']:
                unknown += amt
            for s in a['sectors'][:1]:  # основной сектор контрагента, чтобы не учитывать сумму дважды
                sectors[s] = sectors.get(s, 0.0) + amt
            if a['region']:
                regions[a['region']] = regions.get(a['region'], 0.0) + amt
            if a['fts_countries']:
                for c in str(a['fts_countries']).split(','):
                    c = c.strip()
                    if c:
                        countries[c] = countries.get(c, 0.0) + amt

        def dist(d):
            if amt_total <= 0:
                return []
            return [{'key': k, 'label': label(k) if k in sectors else k, 'share': round(v / amt_total, 4)}
                    for k, v in sorted(d.items(), key=lambda x: -x[1])[:8]]
        return {
            'amount': amt_total, 'count': _num(by_cp.cnt.sum()) if len(by_cp) else 0,
            'counterparties': int(len(by_cp)),
            'top5_share': round(float(by_cp.amt.head(5).sum()) / amt_total, 4) if amt_total > 0 else None,
            'max_share': round(float(by_cp.amt.iloc[0]) / amt_total, 4) if amt_total > 0 else None,
            'unknown_profile_share': round(unknown / amt_total, 4) if amt_total > 0 else None,
            'sectors': [dict(x, label=label(x['key'])) for x in dist(sectors)],
            'regions': dist(regions), 'fts_countries': dist(countries), 'top': top,
            'missing_amount_rows': int(df.amt.isna().sum()),
        }

    profiles = []
    for cid in selected:
        status = 'ambiguous' if cid in ambiguous_ids else 'matched'
        observed, missing = {}, []
        if status == 'matched':
            r = uniq.loc[cid]
            for f, title in OBSERVED_FIELDS.items():
                v = r.get(f)
                if f in PRODUCT_FIELDS or f in ('NEGATIVEMARK', 'FTS_FLAG'):
                    val = _flag(v)
                elif f == 'REVENUE_COMPANY':
                    val = _num(v)
                else:
                    val = _val(v)
                if val is None:
                    missing.append(f)
                observed[f] = {'value': val, 'title': title, 'source': f'{FILES["companies"]}:{f}'}
        else:
            missing = list(OBSERVED_FIELDS)
            for f, title in OBSERVED_FIELDS.items():
                observed[f] = {'value': None, 'title': title, 'source': f'{FILES["companies"]}:{f}'}
        okved = observed['MAINOKVED_CODE']['value']
        sectors = sectors_for_okved(okved)
        own_out = rel[rel.PAYER == cid]
        own_in = rel[rel.BENEFICIARY == cid]
        out_side = side(own_out, 'PAYER', 'BENEFICIARY', None)
        in_side = side(own_in, 'BENEFICIARY', 'PAYER', None)
        self_amt = float(own_out[own_out.BENEFICIARY == cid].amt.sum())

        gid = observed['GROUP_ID']['value']
        group = None
        if gid:
            members = comp.loc[comp.GROUP_ID == gid].drop_duplicates('SYNTHETIC_U')
            msec = {}
            for code in members.MAINOKVED_CODE.dropna():
                for s in sectors_for_okved(code)[:1]:
                    msec[s] = msec.get(s, 0) + 1
            group = {
                'group_id': gid, 'size': int(group_sizes.get(gid, 1)),
                'revenue_sum': _num(group_rev.get(gid)),
                'member_sectors': [{'key': k, 'label': label(k), 'companies': v}
                                   for k, v in sorted(msec.items(), key=lambda x: -x[1])[:6]],
                'note': 'Сумма выручки участников группы из датасета, не консолидированная отчётность.',
            }

        rank = None
        if status == 'matched' and cid in rank_df.index:
            cls = rank_df.loc[cid, 'cls']
            rank = {'okved_class': cls, 'rank': int(rank_df.loc[cid, 'rank']), 'of': int(cls_size[cls]),
                    'note': 'Место по выручке среди компаний выборки с тем же классом ОКВЭД. Это не доля рынка.'}

        p_rows = prs[prs.SYNTHETIC_U == cid]
        shared = set()
        for f in p_rows.SYNTHETIC_F.dropna().unique():
            shared.update(x for x in person_companies.get(f, []) if x != cid)
        regions = [r for r in p_rows.RC_NAME.dropna().unique() if r not in PERSON_MARKERS]

        products = {f: observed[f]['value'] for f in PRODUCT_FIELDS}
        revenue = observed['REVENUE_COMPANY']['value']
        okved_name = observed['MAINOKVED_NAME']['value'] or 'вид деятельности не указан'
        profiles.append({
            'company_id': cid,
            'display_name': f'Компания {cid}',
            'subtitle': okved_name,
            'profile_status': status,
            'segment': 'Крупный бизнес (выручка ≥ 15 млрд)' if (revenue or 0) >= 15e9 else 'Выручка 5–15 млрд (расширенная выборка для сравнения)',
            'sectors': [{'key': s, 'label': label(s)} for s in sectors],
            'observed': observed,
            'products': products,
            'missing_fields': missing,
            'derived': {
                'revenue_rank': rank,
                'group': group,
                'payments_out': out_side,
                'payments_in': in_side,
                'self_payments_amount': self_amt,
                'persons': {'linked_persons': int(p_rows.SYNTHETIC_F.nunique()), 'regions': regions[:10],
                            'companies_via_shared_persons': sorted(shared)[:20],
                            'note': 'Связь физлица с компанией не означает владение или руководство.'},
            },
            'data_notes': [
                'Период и единицы платежей в данных не указаны: суммы — объём в единицах датасета.',
                'Регион — регион регистрации, а не все регионы присутствия.',
            ] + (['ID встречается в справочнике несколько раз — атрибуты не выбраны (ambiguous).'] if status == 'ambiguous' else []),
        })

    return {
        'version': hashlib.sha256(json.dumps([p['company_id'] for p in profiles]).encode()
                                  + ''.join(_sha(p) for p in paths.values()).encode()).hexdigest()[:12],
        'min_revenue': min_revenue,
        'source_files': {k: {'file': p.name, 'sha256': _sha(p), 'rows': int(len({'companies': comp, 'persons': persons, 'payments': pay}[k]))}
                         for k, p in paths.items()},
        'profiles': profiles,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--raw', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--min-revenue', type=float, default=15e9)
    a = ap.parse_args()
    result = build_profiles(a.raw, a.min_revenue)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    print(f'профилей: {len(result["profiles"])}, версия {result["version"]}')


if __name__ == '__main__':
    main()
