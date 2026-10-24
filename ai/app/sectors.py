"""Отраслевая таксономия: ОКВЭД → укрупнённые сектора, общие для профилей компаний и событий.

Сектор назначается по самому длинному совпавшему префиксу кода ОКВЭД. Таксономия
одна для всех отраслей — правила ранжирования не зашиты под конкретный сегмент.
"""

SECTORS = {
    'fuel_energy': 'Топливо и энергетика',
    'metals_mining': 'Металлы и добыча',
    'agri_food': 'Агро и продукты питания',
    'consumer_goods': 'Потребительские товары',
    'retail': 'Розничная торговля',
    'wholesale': 'Оптовая торговля',
    'construction': 'Строительство и стройматериалы',
    'real_estate': 'Недвижимость',
    'transport': 'Транспорт и логистика',
    'finance': 'Финансы и холдинги',
    'auto': 'Автомобили и запчасти',
    'chemicals': 'Химия и пластмассы',
    'machinery': 'Машиностроение и оборудование',
    'electronics': 'Электроника и электрооборудование',
    'it_telecom': 'IT и связь',
    'hospitality': 'Общепит, гостиницы и досуг',
    'business_services': 'Бизнес-услуги',
    'utilities': 'ЖКХ и инфраструктура',
    'pharma_health': 'Фармацевтика и медицина',
    'public': 'Госсектор и образование',
}

# префикс ОКВЭД → сектора (самый длинный префикс имеет приоритет)
OKVED_MAP = {
    '01': ['agri_food'], '02': ['agri_food'], '03': ['agri_food'],
    '05': ['metals_mining', 'fuel_energy'], '06': ['fuel_energy'], '07': ['metals_mining'], '08': ['metals_mining', 'construction'],
    '09': ['fuel_energy', 'metals_mining'],
    '10': ['agri_food', 'consumer_goods'], '11': ['agri_food', 'consumer_goods'], '12': ['consumer_goods'],
    '13': ['consumer_goods'], '14': ['consumer_goods'], '15': ['consumer_goods'], '16': ['construction'],
    '17': ['consumer_goods'], '18': ['business_services'], '19': ['fuel_energy'], '20': ['chemicals'],
    '21': ['pharma_health'], '22': ['chemicals'], '23': ['construction'], '24': ['metals_mining'],
    '25': ['metals_mining', 'machinery'], '26': ['electronics'], '27': ['electronics', 'machinery'],
    '28': ['machinery'], '29': ['auto', 'machinery'], '30': ['machinery', 'transport'], '31': ['consumer_goods'],
    '32': ['consumer_goods'], '33': ['machinery'], '35': ['fuel_energy', 'utilities'], '36': ['utilities'],
    '37': ['utilities'], '38': ['utilities'], '39': ['utilities'],
    '41': ['construction'], '42': ['construction', 'utilities'], '43': ['construction'],
    '45': ['auto'], '45.1': ['auto', 'retail'], '45.3': ['auto', 'wholesale'],
    '46': ['wholesale'], '46.1': ['wholesale', 'business_services'],
    '46.2': ['wholesale', 'agri_food'], '46.3': ['wholesale', 'agri_food', 'consumer_goods'],
    '46.4': ['wholesale', 'consumer_goods'], '46.46': ['wholesale', 'pharma_health'],
    '46.5': ['wholesale', 'electronics', 'it_telecom'], '46.6': ['wholesale', 'machinery'],
    '46.71': ['wholesale', 'fuel_energy'], '46.72': ['wholesale', 'metals_mining'],
    '46.73': ['wholesale', 'construction'], '46.75': ['wholesale', 'chemicals'], '46.9': ['wholesale'],
    '47': ['retail', 'consumer_goods'], '47.3': ['retail', 'fuel_energy'], '47.73': ['retail', 'pharma_health'],
    '49': ['transport'], '50': ['transport'], '51': ['transport'], '52': ['transport'], '53': ['transport'],
    '55': ['hospitality'], '56': ['hospitality', 'consumer_goods'],
    '58': ['it_telecom'], '59': ['it_telecom'], '60': ['it_telecom'], '61': ['it_telecom'], '62': ['it_telecom'],
    '63': ['it_telecom'], '64': ['finance'], '65': ['finance'], '66': ['finance'], '68': ['real_estate'],
    '69': ['business_services'], '70': ['business_services', 'finance'], '71': ['business_services'],
    '71.12': ['business_services', 'construction'], '72': ['business_services'], '73': ['business_services'],
    '74': ['business_services'], '75': ['business_services'], '77': ['business_services'],
    '78': ['business_services'], '79': ['hospitality'], '80': ['business_services'], '81': ['business_services'],
    '82': ['business_services'], '84': ['public'], '85': ['public'], '86': ['pharma_health'],
    '87': ['pharma_health'], '88': ['pharma_health'], '90': ['hospitality'], '91': ['hospitality'],
    '92': ['hospitality'], '93': ['hospitality'], '94': ['public'], '95': ['business_services'], '96': ['business_services'],
}


def sectors_for_okved(code: str | None) -> list[str]:
    if not code:
        return []
    code = code.strip()
    best = ''
    for prefix in OKVED_MAP:
        if (code == prefix or code.startswith(prefix + '.') or code.startswith(prefix)) and len(prefix) > len(best):
            if code.startswith(prefix):
                best = prefix
    return list(OKVED_MAP.get(best, []))


def label(sector: str) -> str:
    return SECTORS.get(sector, sector)
