"""A03: структурированное событие из новости.

Базовый извлекатель — прозрачные правила (лексикон по стеммам, без догадок): тип события,
затронутые отрасли и каналы влияния, регионы, участники, направление изменения, даты,
подтверждающие фрагменты. При доступной LLM агент уточняет событие моделью-экстрактором
(см. agent.py), а результат проходит ту же схему и ограничения перечислений.
"""
import re
from datetime import datetime

from .sectors import SECTORS
from .textproc import looks_like_injection, sentences, stem, tokens

EXTRACTOR_VERSION = 'rules-1.2'

# тип события: метка, стеммы-триггеры (title считается с весом 2), каналы влияния, базовая макрозначимость, темы банка
EVENT_TYPES = {
    'key_rate': ('Ключевая ставка и ДКП', ['ключев ставк', 'ставк цб', 'ставк банк росси', 'денежно-кредитн', 'дкп',
                 'ключевую ставк', 'смягчен', 'ужесточен'],
                 {'cost_of_debt': 1.0, 'liquidity_yield': 0.8, 'construction_cycle': 0.4, 'consumer_demand': 0.3}, 0.85,
                 ['key_rate', 'credit', 'bonds']),
    'inflation': ('Инфляция и цены', ['инфляц', 'ипц', 'дефляц', 'потребительск цен', 'рост цен', 'подорожан', 'индекс цен'],
                  {'consumer_demand': 0.6, 'payroll': 0.4, 'cost_of_debt': 0.5, 'fuel_costs': 0.2}, 0.6, ['inflation']),
    'fx': ('Курс рубля и валюты', ['курс рубл', 'курс доллар', 'курс юан', 'курс евр', 'валют', 'девальвац', 'укреплен рубл',
                                   'ослаблен рубл'], {'foreign_trade': 1.0, 'metals_prices': 0.2}, 0.6, ['fx']),
    'fuel_energy': ('Топливо и энергоносители', ['нефт', 'бензин', 'дизел', 'топлив', 'нефтепродукт', 'газ ', 'электроэнерг',
                                                  'нпз', 'urals', 'brent', 'опек'], {'fuel_costs': 1.0, 'foreign_trade': 0.2}, 0.45,
                    ['fuel', 'commodities']),
    'metals': ('Металлы и сырьё', ['стал', 'металл', 'алюмин', 'никел', 'мед ', 'руд', 'металлург', 'прокат'],
               {'metals_prices': 1.0, 'foreign_trade': 0.2}, 0.25, ['metals', 'commodities']),
    'gold': ('Золото и драгметаллы', ['золот', 'драгметалл', 'серебр'], {'financial_markets': 0.4}, 0.15, ['gold']),
    'agri': ('Агрорынок и продовольствие', ['зерн', 'пшениц', 'урожа', 'сельхоз', 'агро', 'продовольств', 'молок', 'мяс',
                                            'рыб', 'сахар', 'посевн'], {'agri_prices': 1.0, 'consumer_demand': 0.2}, 0.3, ['agri']),
    'consumer_demand': ('Потребительский спрос и розница', ['потребител спрос', 'потреблен', 'розничн', 'ритейл', 'торгов сет',
                                                           'продаж', 'маркетплейс', 'покупател'],
                        {'consumer_demand': 1.0}, 0.45, ['consumption', 'retail']),
    'labor_market': ('Рынок труда', ['рынок труда', 'безработиц', 'зарплат', 'занятост', 'кадров', 'дефицит кадр', 'мрот',
                                     'оплат труда'], {'payroll': 1.0, 'consumer_demand': 0.3}, 0.5, ['labor_market']),
    'gdp_macro': ('Экономический рост', ['ввп', 'экономическ рост', 'рост экономик', 'промпроизводств', 'рецесс',
                                        'деловая активн', 'pmi'], {'consumer_demand': 0.4, 'cost_of_debt': 0.2}, 0.55, ['gdp', 'industry']),
    'budget_tax': ('Бюджет и налоги', ['бюджет', 'налог', 'ндс', 'минфин', 'дефицит бюджет', 'госрасход', 'пошлин'],
                   {'state_budget': 0.9, 'payroll': 0.2, 'foreign_trade': 0.2}, 0.5, ['budget']),
    'credit_market': ('Кредитный и долговой рынок', ['кредитован', 'кредит', 'заемщик', 'облигац', 'офз', 'доходност',
                                                     'займ', 'рефинансир', 'максимальн процентн ставк'],
                      {'cost_of_debt': 0.9, 'liquidity_yield': 0.5}, 0.45, ['credit', 'bonds']),
    'trade_sanctions': ('Внешняя торговля и санкции', ['санкц', 'экспорт', 'импорт', 'таможен', 'вэд', 'параллельн импорт',
                                                        'эмбарго', 'лиценз минфин сша', 'ограничен'],
                        {'foreign_trade': 1.0}, 0.4, ['trade']),
    'real_estate': ('Строительство и недвижимость', ['ипотек', 'застройщ', 'жилищн строительств', 'девелоп', 'недвижим',
                                                     'ввод жиль', 'стройк'], {'construction_cycle': 1.0, 'cost_of_debt': 0.3},
                    0.3, ['construction']),
    'logistics': ('Транспорт и логистика', ['логистик', 'перевоз', 'ржд', 'грузоперевоз', 'порт', 'фрахт', 'авиа',
                                            'логистическ центр', 'склад'], {'fuel_costs': 0.3, 'foreign_trade': 0.3}, 0.25,
                  ['logistics']),
    'regulation': ('Регулирование', ['закон', 'законопроект', 'регулир', 'требован', 'правительств утверд', 'постановлен',
                                     'маркировк', 'лицензи', 'госдум', 'запрет'], {}, 0.3, []),
    'financial_sector': ('Финансовый сектор', ['коммерческ банк', 'кредитн организац', 'страхов', 'брокер', 'инсайдерск',
                                               'манипулирован', 'отозван лицензи', 'банковск сектор'],
                         {'financial_markets': 0.8}, 0.2, ['bonds']),
}

SECTOR_LEXICON = {
    'fuel_energy': ['нефт', 'бензин', 'дизел', 'топлив', 'нефтепродукт', 'газпром', 'нпз', 'энерг', 'электроэнерг', 'азс'],
    'metals_mining': ['стал', 'металл', 'металлург', 'руд', 'алюмин', 'никел', 'уголь', 'добыч', 'горнодоб'],
    'agri_food': ['зерн', 'пшениц', 'урожа', 'агро', 'сельхоз', 'продовольств', 'продукт питан', 'молок', 'мяс', 'рыб'],
    'retail': ['розничн', 'ритейл', 'торгов сет', 'магазин', 'маркетплейс', 'ozon', 'wildberri', 'x5', 'магнит'],
    'wholesale': ['оптов', 'дистрибуц', 'дистрибьют'],
    'construction': ['строител', 'застройщ', 'стройк', 'девелоп', 'стройматериал', 'цемент', 'жилищн строительств'],
    'real_estate': ['недвижим', 'ипотек', 'аренд', 'жиль'],
    'transport': ['логистик', 'перевоз', 'ржд', 'грузов', 'порт', 'авиа', 'железнодорож', 'фрахт', 'склад'],
    'finance': ['коммерческ банк', 'страхов', 'брокер', 'облигац', 'кредитн организац', 'нко', 'банковск сектор'],
    'auto': ['автомоб', 'автопроизвод', 'автоваз', 'автодилер', 'автокредит'],
    'chemicals': ['хими', 'удобрен', 'пластик', 'полимер'],
    'machinery': ['машиностро', 'станк', 'оборудован'],
    'electronics': ['электрон', 'микросхем', 'полупроводник'],
    'it_telecom': ['ит-', 'софт', 'программн обеспечен', 'цифров', 'связ', 'телеком', 'искусствен интеллект', 'ии '],
    'hospitality': ['ресторан', 'гостиниц', 'туризм', 'турист', 'общепит'],
    'pharma_health': ['фарм', 'лекарств', 'медицин'],
    'utilities': ['жкх', 'водоснабжен', 'коммунальн'],
}
MACRO_EVENT_TYPES = {'key_rate', 'inflation', 'fx', 'gdp_macro', 'budget_tax', 'labor_market', 'credit_market'}
NON_BUSINESS = ['футбол', 'хокке', 'матч', 'чемпионат', 'олимпи', 'фигурист', 'боксер', 'теннис', 'актер', 'актрис',
                'певиц', 'певец', 'фильм', 'сериал', 'погибш', 'теракт', 'задержал', 'суд приговор', 'протест', 'выбор']
DIRECTION = {
    'hold': ['сохранил', 'сохранить', 'оставил', 'без изменен', 'неизменн', 'пауз'],
    'up': ['повыс', 'вырос', 'рост', 'увелич', 'подорож', 'ускор', 'рекорд', 'ослаблен рубл'],
    'down': ['сниз', 'сократ', 'упал', 'подешев', 'замедл', 'укреплен рубл', 'дефляц'],
}
PARTICIPANTS = ['Банк России', 'ЦБ', 'Минфин', 'Росстат', 'Правительство', 'Минэкономразвития', 'ФАС', 'ФНС', 'Госдума',
                'ОПЕК', 'ФРС', 'Минпромторг', 'Минсельхоз', 'РЖД']
FED_DISTRICTS = {'московск': 'Центральный ФО', 'сибирск': 'Сибирский ФО', 'приволжск': 'Приволжский ФО',
                 'уральск': 'Уральский ФО', 'южн': 'Южный ФО', 'северо-запад': 'Северо-Западный ФО',
                 'дальневосточн': 'Дальневосточный ФО', 'северо-кавказ': 'Северо-Кавказский ФО'}


def _stems(phrase: str) -> list[str]:
    return [stem(w) for w in re.findall(r'[a-zа-яё0-9-]+', phrase.lower())]


def _count(stem_list: list[str], text_stems: list[str]) -> int:
    """Число вхождений фразы (последовательности префиксов стеммов) в тексте."""
    n = len(stem_list)
    if not n:
        return 0
    hits = 0
    for i in range(len(text_stems) - n + 1):
        if all(text_stems[i + j].startswith(stem_list[j]) for j in range(n)):
            hits += 1
    return hits


def _region_index(regions: list[str]) -> dict[str, str]:
    idx = {}
    for r in regions:
        key = [s for s in _stems(r) if s not in ('област', 'край', 'республик', 'автоном', 'округ', 'г')]
        if key:
            idx[' '.join(key)] = r
    return idx


def extract_event(news: dict, regions: list[str] | None = None) -> dict:
    title = news.get('title') or ''
    body = news.get('content') or news.get('summary') or ''
    text = f'{title}. {body}'
    t_title = tokens(title, drop_stop=False)
    t_body = tokens(body, drop_stop=False)
    low = text.lower()

    scores = {}
    for et, (_, triggers, _, _, _) in EVENT_TYPES.items():
        s = 0.0
        for trig in triggers:
            st = _stems(trig)
            s += 2.0 * _count(st, t_title) + 0.5 * min(3, _count(st, t_body))
        if s:
            scores[et] = s
    sec_scores = {}
    for sec, words in SECTOR_LEXICON.items():
        s = 0.0
        for w in words:
            st = _stems(w)
            s += 2.0 * _count(st, t_title) + 0.5 * min(3, _count(st, t_body))
        if s >= 0.5:
            sec_scores[sec] = s
    non_business = sum(_count(_stems(w), t_title + t_body) for w in NON_BUSINESS)

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    business_signal = (ranked[0][1] if ranked else 0) + sum(sec_scores.values()) * 0.5
    if not ranked and not sec_scores:
        event_type = 'non_business'
    elif non_business >= 1 and business_signal < 2.5:
        event_type = 'non_business'
    elif ranked and ranked[0][1] >= 1.0:
        event_type = ranked[0][0]
    elif sec_scores:
        event_type = 'industry'
    else:
        event_type = 'non_business'

    secondary = [et for et, s in ranked[1:4] if s >= 1.0]
    if event_type in MACRO_EVENT_TYPES:
        # длинные макро-релизы мимоходом упоминают многие отрасли; отраслевую привязку берём только из заголовка
        sec_scores = {sec: s for sec, s in sec_scores.items()
                      if any(_count(_stems(w), t_title) for w in SECTOR_LEXICON[sec])}
    channels: dict[str, float] = {}
    for et in [event_type] + secondary:
        if et in EVENT_TYPES:
            w = 1.0 if et == event_type else 0.5
            for ch, v in EVENT_TYPES[et][2].items():
                channels[ch] = round(max(channels.get(ch, 0), v * w), 3)

    direction = None
    for d, words in DIRECTION.items():
        if any(w in low for w in words):
            direction = d
            break

    region_hits = []
    idx = _region_index(regions or [])
    all_stems = t_title + t_body
    for key, name in idx.items():
        if _count(key.split(), all_stems):
            region_hits.append(name)
    districts = [v for k, v in FED_DISTRICTS.items() if f'{k} федеральн' in low]

    participants = [p for p in PARTICIPANTS if re.search(rf'(?<![А-Яа-яё]){re.escape(p)}(?![а-яё])', text)]
    participants += [m.strip() for m in re.findall(r'«([^»]{2,40})»', text)][:5]

    evidence = []
    trig_stems = []
    if event_type in EVENT_TYPES:
        trig_stems = [_stems(t) for t in EVENT_TYPES[event_type][1]]
    for s in sentences(text)[:12]:
        if looks_like_injection(s):
            continue
        st = tokens(s, drop_stop=False)
        if any(_count(ts, st) for ts in trig_stems) or re.search(r'\d', s):
            evidence.append({'quote': s[:400], 'source_id': f'N:{news.get("id", "")}'})
        if len(evidence) >= 3:
            break
    event_date = None
    m = re.search(r'\((\d{2})\.(\d{2})\.(20\d{2})\)', title)
    if m:
        event_date = f'{m.group(3)}-{m.group(2)}-{m.group(1)}'

    label = EVENT_TYPES[event_type][0] if event_type in EVENT_TYPES else (
        'Отраслевое событие' if event_type == 'industry' else 'Не относится к бизнесу')
    importance = EVENT_TYPES[event_type][3] if event_type in EVENT_TYPES else (0.2 if event_type == 'industry' else 0.0)
    return {
        'event_type': event_type,
        'event_label': label,
        'secondary_types': secondary,
        'sectors': [s for s, _ in sorted(sec_scores.items(), key=lambda x: -x[1])][:4],
        'sector_labels': [SECTORS[s] for s, _ in sorted(sec_scores.items(), key=lambda x: -x[1])][:4],
        'channels': channels,
        'direction': direction,
        'regions': region_hits[:5],
        'federal_districts': districts,
        'participants': participants[:8],
        'published_at': news.get('published_at'),
        'event_date': event_date,
        'macro_importance': importance,
        'bank_topics': EVENT_TYPES[event_type][4] if event_type in EVENT_TYPES else [],
        'evidence': evidence,
        'business_relevant': event_type != 'non_business',
        'extractor': EXTRACTOR_VERSION,
        'suspicious_instructions': looks_like_injection(text),
        'unknown': [f for f, v in (('event_date', event_date), ('regions', region_hits), ('direction', direction)) if not v],
    }


def bank_query(event: dict, news: dict) -> str:
    """Запрос в аналитику банка: тип события + ключевые слова заголовка."""
    parts = [news.get('title', '')]
    if event['event_type'] in EVENT_TYPES:
        parts.append(EVENT_TYPES[event['event_type']][0])
    parts += event.get('sector_labels', [])[:2]
    return ' '.join(parts)


def parse_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
