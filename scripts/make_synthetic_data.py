#!/usr/bin/env python3
"""Синтетические данные в формате организаторов (для запуска без закрытых CSV).

Компании, люди и платежи полностью выдуманы (seed фиксирован), ID начинаются с U_9 / F_9,
чтобы не пересекаться с обезличенными ID кейса. Набор покрывает сценарии демо:
разные отрасли, кредитная нагрузка, ВЭД, неполный и неоднозначный профиль.

  python3 scripts/make_synthetic_data.py --out data/synthetic
"""
import argparse
import csv
import random
from pathlib import Path

COMPANY_COLS = ['SYNTHETIC_U', 'ORG_TYPE', 'OKFS_NAME', 'COMPANY_AGE_YEARS_GRADATION', 'ECO_MARK_LABEL',
                'MAINOKVED_CODE', 'MAINOKVED_NAME', 'NEGATIVEMARK', 'AMOUNT_WORKERS_FNS_GRADATION',
                'AMOUNT_WORKERS_SPARK_GRADATION', 'CL_TYPE', 'CL_PRODUCT_RKO_MARK', 'CL_PRODUCT_GAR_MARK',
                'CL_PRODUCT_LOA_MARK', 'CL_PRODUCT_LEA_MARK', 'CL_PRODUCT_DEP_MARK', 'CL_PRODUCT_ZPP_MARK',
                'FTS_FLAG', 'FTS_COUNTRY_NAME', 'FACTORING_MARK', 'REVENUE_COMPANY', 'GROUP_ID', 'CITY', 'REGION']

# id, ОКВЭД, название, выручка, регион, город, продукты (rko,gar,loa,lea,dep,zpp,fact), фтс, страны, работники, группа
ANCHORS = [
    ('U_9000001', '47.11', 'Торговля розничная преимущественно пищевыми продуктами, напитками и табачными изделиями в неспециализированных магазинах',
     48e9, 'Москва', 'г. Москва', (1, 1, 1, 1, 0, 1, 1), 1, 'КИТАЙ, ТУРЦИЯ', 'Более 251', 'group_900001'),
    ('U_9000002', '47.11', 'Торговля розничная преимущественно пищевыми продуктами, напитками и табачными изделиями в неспециализированных магазинах',
     21e9, 'Новосибирская область', 'г. Новосибирск', (1, 0, 0, 0, 1, 1, 0), 0, '', 'Более 251', 'group_900002'),
    ('U_9000003', '46.71', 'Торговля оптовая твердым, жидким и газообразным топливом и подобными продуктами',
     67e9, 'Республика Татарстан', 'г. Казань', (1, 1, 1, 0, 1, 0, 0), 1, 'КАЗАХСТАН, УЗБЕКИСТАН', '101-250', 'group_900003'),
    ('U_9000004', '41.20', 'Строительство жилых и нежилых зданий',
     33e9, 'Санкт-Петербург', 'г. Санкт-Петербург', (1, 1, 1, 1, 0, 1, 0), 0, '', 'Более 251', 'group_900003'),
    ('U_9000005', '10.51', 'Производство молока (кроме сырого) и молочной продукции',
     19e9, 'Воронежская область', 'г. Воронеж', (1, 0, 1, 1, 0, 1, 1), 1, 'БЕЛАРУСЬ', 'Более 251', 'group_900005'),
    ('U_9000006', '46.72', 'Торговля оптовая металлами и металлическими рудами',
     26e9, 'Челябинская область', 'г. Челябинск', (1, 0, 0, 0, 1, 0, 0), 1, 'КИТАЙ, ТУРЦИЯ, ИНДИЯ', '16-100', 'group_900006'),
    ('U_9000007', '62.01', 'Разработка компьютерного программного обеспечения',
     16e9, 'Москва', 'г. Москва', (1, 0, 0, 0, 1, 1, 0), 0, '', '101-250', 'group_900007'),
]
SMALL_OKVED = [
    ('46.38', 'Торговля оптовая прочими пищевыми продуктами'), ('49.41', 'Деятельность автомобильного грузового транспорта'),
    ('10.89', 'Производство прочих пищевых продуктов'), ('68.20', 'Аренда и управление собственным или арендованным недвижимым имуществом'),
    ('46.71', 'Торговля оптовая твердым, жидким и газообразным топливом'), ('23.61', 'Производство изделий из бетона'),
    ('24.10', 'Производство чугуна, стали и ферросплавов'), ('01.41', 'Разведение молочного крупного рогатого скота'),
    ('52.10', 'Деятельность по складированию и хранению'), ('62.02', 'Деятельность консультативная в области компьютерных технологий'),
    ('46.73', 'Торговля оптовая лесоматериалами, строительными материалами'), ('35.11', 'Производство электроэнергии'),
]
REGIONS = [('Москва', 'г. Москва'), ('Московская область', 'г. Химки'), ('Санкт-Петербург', 'г. Санкт-Петербург'),
           ('Свердловская область', 'г. Екатеринбург'), ('Краснодарский край', 'г. Краснодар'), ('Ростовская область', 'г. Ростов-на-Дону')]
# Какие сектора контрагентов типичны для якорной компании (для правдоподобного графа)
SUPPLY = {
    'U_9000001': ['46.38', '10.89', '49.41', '68.20', '52.10'], 'U_9000002': ['46.38', '10.89', '49.41', '52.10'],
    'U_9000003': ['46.71', '49.41', '52.10', '35.11'], 'U_9000004': ['23.61', '46.73', '24.10', '49.41'],
    'U_9000005': ['01.41', '49.41', '52.10', '10.89'], 'U_9000006': ['24.10', '49.41', '52.10'],
    'U_9000007': ['62.02', '68.20'],
}


def row(cid, okved, name, revenue, region, city, products, fts, countries, workers, group, rnd, cl='CLIENT'):
    rko, gar, loa, lea, dep, zpp, fact = products
    return {
        'SYNTHETIC_U': cid, 'ORG_TYPE': 'КОММ_ОРГ', 'OKFS_NAME': 'ЧАСТНАЯ СОБСТВЕННОСТЬ',
        'COMPANY_AGE_YEARS_GRADATION': rnd.choice(['8-15', '16-25', '4-7']),
        'ECO_MARK_LABEL': rnd.choice(['Оптимизация', 'Бизнес в новой реальности', 'Стремительный рост']),
        'MAINOKVED_CODE': okved, 'MAINOKVED_NAME': name, 'NEGATIVEMARK': '0.0',
        'AMOUNT_WORKERS_FNS_GRADATION': workers, 'AMOUNT_WORKERS_SPARK_GRADATION': workers if rnd.random() < 0.5 else '',
        'CL_TYPE': cl, 'CL_PRODUCT_RKO_MARK': f'{rko}.0', 'CL_PRODUCT_GAR_MARK': f'{gar}.0',
        'CL_PRODUCT_LOA_MARK': f'{loa}.0', 'CL_PRODUCT_LEA_MARK': f'{lea}.0', 'CL_PRODUCT_DEP_MARK': f'{dep}.0',
        'CL_PRODUCT_ZPP_MARK': f'{zpp}.0', 'FTS_FLAG': f'{fts}.0', 'FTS_COUNTRY_NAME': countries,
        'FACTORING_MARK': f'{fact}.0', 'REVENUE_COMPANY': f'{revenue:.1f}', 'GROUP_ID': group, 'CITY': city, 'REGION': region,
    }


def main(out: Path):
    rnd = random.Random(20261024)
    out.mkdir(parents=True, exist_ok=True)
    companies = [row(*a, rnd=rnd) for a in ANCHORS]
    # Неполный профиль: крупная выручка, но нет ОКВЭД-названия, работников, продуктов и региона
    inc = row('U_9000008', '46.90', '', 17e9, '', '', (0, 0, 0, 0, 0, 0, 0), 0, '', '', 'group_900008', rnd, cl='PROSPECT')
    for f in ('MAINOKVED_NAME', 'AMOUNT_WORKERS_FNS_GRADATION', 'AMOUNT_WORKERS_SPARK_GRADATION', 'ECO_MARK_LABEL',
              'CL_PRODUCT_LOA_MARK', 'CL_PRODUCT_DEP_MARK', 'CL_PRODUCT_ZPP_MARK', 'CITY', 'REGION'):
        inc[f] = ''
    companies.append(inc)
    # Неоднозначный ID: две разные строки профиля с одним SYNTHETIC_U
    amb = ANCHORS[5]
    companies.append(row('U_9000009', '46.90', 'Торговля оптовая неспециализированная', 18e9, 'Москва', 'г. Москва',
                         (1, 0, 0, 0, 0, 0, 0), 0, '', '16-100', 'group_900009', rnd))
    companies.append(row('U_9000009', '41.20', 'Строительство жилых и нежилых зданий', 15.5e9, 'Тверская область', 'г. Тверь',
                         (1, 1, 1, 0, 0, 0, 0), 0, '', '101-250', 'group_900009', rnd))
    del amb
    smalls = []
    for i in range(80):
        okved, name = rnd.choice(SMALL_OKVED)
        region, city = rnd.choice(REGIONS)
        cid = f'U_91{i:05d}'
        fts = 1 if rnd.random() < 0.2 else 0
        smalls.append(cid)
        group = rnd.choice(['group_900003', 'group_900001']) if i < 4 else f'group_91{i:05d}'
        companies.append(row(cid, okved, name, rnd.uniform(5e7, 4e9), region, city,
                             tuple(int(rnd.random() < p) for p in (0.7, 0.1, 0.3, 0.2, 0.2, 0.3, 0.05)),
                             fts, rnd.choice(['КИТАЙ', 'ТУРЦИЯ', 'БЕЛАРУСЬ']) if fts else '',
                             rnd.choice(['Менее 15', '16-100', '101-250']), group, rnd, cl=rnd.choice(['CLIENT', 'PROSPECT'])))
    by_okved = {}
    for c in companies:
        by_okved.setdefault(c['MAINOKVED_CODE'], []).append(c['SYNTHETIC_U'])
    payments = []
    for a in ANCHORS + [('U_9000008',)]:
        cid = a[0]
        for okv in SUPPLY.get(cid, ['46.38', '49.41']):
            for sup in rnd.sample(by_okved.get(okv, smalls), k=min(3, len(by_okved.get(okv, smalls)))):
                payments.append({'BENEFICIARY': sup, 'PAYER': cid, 'PAY_AMT': f'{rnd.randint(50, 4000) * 1_000_000:.1f}',
                                 'PAY_CNT': str(rnd.randint(5, 900))})
        for buyer in rnd.sample(smalls, 6):
            payments.append({'BENEFICIARY': cid, 'PAYER': buyer, 'PAY_AMT': f'{rnd.randint(20, 2500) * 1_000_000:.1f}',
                             'PAY_CNT': str(rnd.randint(3, 400))})
        # контрагент без профиля в справочнике
        payments.append({'BENEFICIARY': f'U_99{rnd.randint(10000, 99999)}', 'PAYER': cid,
                         'PAY_AMT': f'{rnd.randint(10, 300) * 1_000_000:.1f}', 'PAY_CNT': str(rnd.randint(1, 50))})
    payments.append({'BENEFICIARY': 'U_9000003', 'PAYER': 'U_9000004', 'PAY_AMT': '1200000000.0', 'PAY_CNT': '40'})
    payments.append({'BENEFICIARY': 'U_9000001', 'PAYER': 'U_9000001', 'PAY_AMT': '500000000.0', 'PAY_CNT': '12'})  # самоперевод
    persons = []
    for i, cid in enumerate([a[0] for a in ANCHORS] * 2 + smalls[:20]):
        region = rnd.choice(['МОСКОВСКИЙ', 'СИБИРСКИЙ', 'ПРИВОЛЖСКИЙ', 'Не определено'])
        persons.append({'SYNTHETIC_F': f'F_9{i % 18:05d}', 'CITY_NAME': rnd.choice(['Москва', 'Казань', 'Неопределенный город']),
                        'RC_NAME': region, 'SYNTHETIC_U': cid})

    def write(name, cols, rows):
        with (out / name).open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=cols, delimiter=';')
            w.writeheader()
            w.writerows(rows)
    write('df_Uid_data_hack.csv', COMPANY_COLS, companies)
    write('df_Uid_payment_hack.csv', ['BENEFICIARY', 'PAYER', 'PAY_AMT', 'PAY_CNT'], payments)
    write('df_Fid_Uid_link_hack.csv', ['SYNTHETIC_F', 'CITY_NAME', 'RC_NAME', 'SYNTHETIC_U'], persons)
    print(f'компаний: {len(companies)}, платежей: {len(payments)}, связей физлиц: {len(persons)} → {out}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default='data/synthetic', type=Path)
    main(ap.parse_args().out)
