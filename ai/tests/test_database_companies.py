from app.profiles import ProfileStore
from app.data_build import build_profiles
from pathlib import Path


def test_database_companies_keep_ids_and_missing_fields():
    data = build_profiles(Path(__file__).resolve().parents[2] / 'data' / 'synthetic', 15e9)
    profiles = ProfileStore(data, 'synthetic:test')
    cid = '75ad1adb-7c36-4101-bd17-7c782a620c2f'
    profiles.add_database_companies([{'id': cid, 'name': 'Компания из основной БД',
                                     'industry': 'Технологии', 'description': 'Описание из базы'}])
    p = profiles.get(cid)
    assert p['display_name'] == 'Компания из основной БД'
    assert p['observed']['REVENUE_COMPANY']['value'] is None
    assert p['products']['CL_PRODUCT_LOA_MARK'] is None
    assert 'REVENUE_COMPANY' in p['missing_fields']
    assert profiles.summary(p)['completeness'] == 'incomplete'
    assert profiles.search(cid)[1] == 1
    assert p['data_notes'] == ['Описание из базы', 'Финансовые поля и ОКВЭД в основной БД отсутствуют.']
