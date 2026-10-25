#!/usr/bin/env python3
"""Контрольная выгрузка реальных новостей из RSS для офлайн-прогона и тестов.

Скрипт только собирает и сэмплирует то, что реально пришло из RSS-лент:
ничего не дописывает, не перефразирует и не придумывает. Отбор по ключевым
словам ниже — это способ набрать тестовую выборку с перекосом в экономику и
бизнес (плюс небизнесовый «шум» для проверки фильтрации), а НЕ классификатор
продукта.

Что делает:
1. загружает RSS-ленты (stdlib, User-Agent браузера, таймаут 20 с, повторы);
   ошибка одного источника не роняет запуск — она попадает в сводку;
2. парсит <item>: title, link, description, pubDate и, если есть, полный текст
   (yandex:full-text, content:encoded, rbc_news:full-text);
3. чистит HTML и сущности, приводит дату к ISO 8601 с таймзоной,
   удаляет дубли по нормализованному URL;
4. отбирает публикации за последние --days дней: все пресс-релизы и события
   Банка России за период, несколько межисточниковых «кластеров» одного
   события (для проверки дедупликации), --nonbiz небизнесовых новостей
   (спорт, культура, происшествия) и экономику/бизнес до --target записей;
5. пишет JSON {generated_at, sources[], items[]} (UTF-8, ensure_ascii=False,
   items отсортированы по дате по убыванию).

Запуск:
  python3 scripts/fetch_news_snapshot.py --out data/news_snapshot.json
  # сохранить сырые ленты для воспроизводимого офлайн-прогона:
  python3 scripts/fetch_news_snapshot.py --save-raw /path/raw
  # повторить отбор офлайн на сохранённых лентах с той же опорной датой:
  python3 scripts/fetch_news_snapshot.py --from-raw /path/raw --now 2026-10-24T20:20:00+03:00
"""
import argparse
import email.utils
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

MSK = timezone(timedelta(hours=3))
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
TIMEOUT = 20
SUMMARY_MAX = 4000

# (название ленты в сводке, издание для items[].source_name, URL)
FEEDS = [
    ('Банк России — пресс-релизы', 'Банк России', 'https://www.cbr.ru/rss/RssPress'),
    ('Банк России — события и комментарии', 'Банк России', 'https://www.cbr.ru/rss/eventrss'),
    ('РБК — главные новости (full)', 'РБК', 'https://rssexport.rbc.ru/rbcnews/news/30/full.rss'),
    ('Ведомости — экономика', 'Ведомости', 'https://www.vedomosti.ru/rss/rubric/economics'),
    ('Ведомости — бизнес', 'Ведомости', 'https://www.vedomosti.ru/rss/rubric/business'),
    ('Ведомости — новости', 'Ведомости', 'https://www.vedomosti.ru/rss/news'),
    ('Коммерсантъ — экономика', 'Коммерсантъ', 'https://www.kommersant.ru/RSS/section-economics.xml'),
    ('Коммерсантъ — бизнес', 'Коммерсантъ', 'https://www.kommersant.ru/RSS/section-business.xml'),
    ('Коммерсантъ — лента новостей', 'Коммерсантъ', 'https://www.kommersant.ru/RSS/news.xml'),
    ('Лента.ру — экономика', 'Лента.ру', 'https://lenta.ru/rss/news/economics'),
    ('Banki.ru — лента новостей', 'Banki.ru', 'https://www.banki.ru/xml/news.rss'),
    ('РИА Новости — лента', 'РИА Новости', 'https://ria.ru/export/rss2/archive/index.xml'),
]

# Дополнительные CA-бандлы: /etc/ssl/cert.pem на macOS не содержит часть корней
# (например, HARICA у cbr.ru). Проверка сертификатов НЕ отключается.
EXTRA_CA_CANDIDATES = [
    '/opt/homebrew/etc/ca-certificates/cert.pem',
    '/usr/local/etc/ca-certificates/cert.pem',
    '/opt/homebrew/etc/openssl@3/cert.pem',
    '/usr/local/etc/openssl@3/cert.pem',
    ssl.get_default_verify_paths().openssl_cafile,
    str(Path(__file__).resolve().parent.parent / 'Russian_Trusted_Root_CA.cer'),
]

# --- Ключевые слова для сэмплирования (не классификатор продукта) -------------
BIZ_TOPICS = {
    'key_rate': r'ключев\w* ставк|денежно-кредитн|\bЦБ\b|Банк[а-я]* России|Набиуллин|регулятор|ставк[аиуе] ЦБ',
    'inflation': r'инфляц|подорожа|рост цен|цены на|цен на|индекс потребительск|дефляц',
    'fx': r'курс[а-я]* (рубля|доллара|евро|юаня)|\bрубл[ья]\b|доллар|\bюан|валют',
    'oil_fuel': r'нефт|бензин|топлив|дизел|\bАЗС|Brent|Urals|ОПЕК|газопровод|\bСПГ\b|\bгаз[аеу]?\b|Газпром|Роснефть|Лукойл',
    'metals': r'металл|\bсталь\b|сталелит|нержавеющ|алюмин|никел|\bмед[ьи]\b|золот|Норникел|Северстал|\bММК\b|НЛМК|Русал|\bугол[ья]\b|\bугля\b|угольн',
    'agro': r'зерн|пшениц|урожа|агро|сельхоз|аграри|удобрен|\bсахар|масличн|подсолнечн|молок|мяс[ао]\b|картофел|овощ',
    'retail': r'розниц|ритейл|маркетплейс|Wildberries|Ozon|потребител|\bX5\b|Магнит|продаж|\bспрос|покупател|торгов[а-я]* сет',
    'labor': r'зарплат|заработн|безработ|рын[а-я]* труда|кадров|вакан|работодател|сотрудник|занятост|пенси',
    'budget_tax': r'бюджет|налог|\bНДС\b|НДФЛ|Минфин|\bФНС\b|пошлин|акциз|госдолг',
    'credit_bonds': r'кредит|облигац|\bОФЗ\b|заем|займ|\bдолг(?!о)|депозит|вклад|дефолт|Мосбирж|бирж|котировк|ценн[а-я]* бумаг|фондов[а-я]* (рын|индекс)|\bIPO\b|дивиденд|банк',
    'sanctions_trade': r'санкц|экспорт|импорт|внешнеторгов|параллельн[а-я]* импорт|эмбарго|ограничени[яй] на (ввоз|вывоз)',
    'logistics': r'логист|перевоз|\bРЖД\b|груз|\bпорт[ауеы]?\b|контейнер|авиакомпани|авиаперевоз|транспорт|грузовик|фур[аы]\b',
    'construction_mortgage': r'ипотек|застройщ|жиль[ея]|строител|девелоп|недвижим|квартир|новостро',
    'companies': r'\bПАО\b|выручк|прибыл|убыт|отчетност|сделк|банкрот|акционер|Сбер|ВТБ|Аэрофлот|Яндекс|АвтоВАЗ|холдинг|компани[ияюй]',
}
NONBIZ_TOPICS = {
    'sport': r'футбол|хоккей|матч|чемпионат|турнир|сборн[а-я]* (России|по)|тренер|\bРПЛ\b|\bКХЛ\b|\bНХЛ\b|олимпи|фигурист|теннис|Гран-при|спортсмен|УЕФА|ФИФА|баскетбол|волейбол|биатлон|боксер|\bUFC\b|забил|вратар|плей-офф',
    'culture': r'\bфильм|кино|театр|музе[йяе]|выставк|спектакл|концерт|певиц|певец|актер|актрис|режиссер|сериал|писател|фестивал|рэпер|музыкант|балет|опер[аыу]\b|премия «',
    'incident': r'\bДТП\b|авари[яи]|пожар|погиб|пострадал|задержа|убийств|убил|происшеств|взрыв|обрушени|затоплен|катастроф|утону|\bМЧС\b|землетрясен|ураган|спасател|похищ|напал',
}
NONBIZ_RSS_CATEGORIES = {
    'sport': ('спорт',), 'culture': ('культура', 'искусство', 'кино'),
    'incident': ('происшествия', 'проишествия', 'инциденты'),
}
BIZ_RE = {k: re.compile(v, re.I) for k, v in BIZ_TOPICS.items()}
NONBIZ_RE = {k: re.compile(v, re.I) for k, v in NONBIZ_TOPICS.items()}
# Темы, которые сами по себе слишком общие, чтобы считать новость «бизнесовой».
WEAK_TOPICS = {'companies', 'labor'}


# --- Загрузка ----------------------------------------------------------------
def make_ssl_context(extra_cafiles=()):
    if os.path.exists('/etc/ssl/cert.pem'):
        ctx = ssl.create_default_context(cafile='/etc/ssl/cert.pem')
    else:
        ctx = ssl.create_default_context()
    loaded = []
    for path in list(EXTRA_CA_CANDIDATES) + list(extra_cafiles):
        if path and os.path.isfile(path) and path not in loaded:
            try:
                ctx.load_verify_locations(cafile=path)
                loaded.append(path)
            except (ssl.SSLError, OSError):
                pass
    return ctx, loaded


def fetch(url, ctx, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': UA,
                'Accept': 'application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5',
                'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.5',
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError, ssl.SSLError) as e:  # noqa: PERF203
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def slug(url):
    return re.sub(r'[^A-Za-z0-9]+', '_', url.split('://', 1)[-1]).strip('_') + '.xml'


# --- Парсинг -----------------------------------------------------------------
def local(tag):
    return tag.rsplit('}', 1)[-1].split(':')[-1].lower()


_BLOCK_TAGS = re.compile(r'<\s*(br|/p|p|/div|div|/li|li|/h\d|h\d|tr|/tr)\b[^>]*>', re.I)


def clean_text(raw):
    if not raw:
        return ''
    s = raw
    # Иногда HTML приходит дважды экранированным (&lt;p&gt;) — раскрываем один раз.
    if '&lt;' in s and '<' not in s:
        s = html.unescape(s)
    s = re.sub(r'<!--.*?-->', ' ', s, flags=re.S)
    s = re.sub(r'<(script|style)\b.*?</\1>', ' ', s, flags=re.S | re.I)
    s = _BLOCK_TAGS.sub('\n', s)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(html.unescape(s))
    s = s.replace(' ', ' ').replace('​', '').replace('﻿', '')
    s = re.sub(r'[ \t\r\f\v]+', ' ', s)
    s = re.sub(r' *\n[ \n]*', '\n', s).strip()
    s = re.sub(r'\n+', ' ', s)  # summary — одной строкой
    return re.sub(r' {2,}', ' ', s).strip()


def truncate(s, n=SUMMARY_MAX):
    if len(s) <= n:
        return s
    cut = s[:n - 1]
    sp = cut.rfind(' ')
    if sp > n * 0.8:
        cut = cut[:sp]
    return cut.rstrip(' ,;:-—') + '…'


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        dt = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)  # русскоязычные ленты без зоны — московское время
    return dt


def normalize_url(url):
    url = (url or '').strip()
    if not url:
        return ''
    p = urllib.parse.urlsplit(url)
    scheme = 'https' if p.scheme in ('http', 'https', '') else p.scheme
    host = p.netloc.lower()
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
         if not k.lower().startswith(('utm_', 'from', 'yclid', 'fbclid', 'rss'))]
    path = p.path.rstrip('/') or '/'
    return urllib.parse.urlunsplit((scheme, host, path, urllib.parse.urlencode(q), ''))


def absolutize(link, base):
    return urllib.parse.urljoin(base, link) if link else link


def parse_feed(data, feed_url):
    if data.startswith(b'\xef\xbb\xbf'):
        data = data[3:]
    data = data.lstrip()
    root = ET.fromstring(data)
    out = []
    for item in root.iter():
        if local(item.tag) not in ('item', 'entry'):
            continue
        f = {'title': '', 'link': '', 'description': '', 'full': '', 'date': '', 'category': []}
        for ch in item:
            name = local(ch.tag)
            text = ''.join(ch.itertext()) if len(ch) else (ch.text or '')
            if name == 'title' and not f['title']:
                f['title'] = text
            elif name == 'link' and not f['link']:
                f['link'] = (ch.get('href') or text).strip()
            elif name == 'guid' and not f['link'] and (text or '').startswith('http'):
                f['link'] = text.strip()
            elif name in ('description', 'summary', 'synopsis') and not f['description'].strip():
                f['description'] = text
            elif name in ('full-text', 'encoded', 'content') and len(text) > len(f['full']):
                f['full'] = text
            elif name in ('pubdate', 'published', 'updated', 'date') and not f['date']:
                f['date'] = text
            elif name == 'category' and text.strip():
                f['category'].append(text.strip())
        f['link'] = absolutize(f['link'], feed_url)
        out.append(f)
    return out


# --- Отбор -------------------------------------------------------------------
def topics_of(it):
    lead = it['summary'][:600]
    title_biz = [k for k, rx in BIZ_RE.items() if rx.search(it['title'])]
    lead_biz = [k for k, rx in BIZ_RE.items() if rx.search(lead) and k not in title_biz]
    # Бизнес-кандидат: сильная тема в заголовке или >=2 сильные темы в лиде.
    if set(title_biz) - WEAK_TOPICS or len(set(lead_biz) - WEAK_TOPICS) >= 2:
        biz = title_biz + lead_biz
    else:
        biz = []
    nb = [k for k, rx in NONBIZ_RE.items() if rx.search(it['title'])]
    cats = ' '.join(it['_cats']).lower()
    for k, words in NONBIZ_RSS_CATEGORIES.items():
        if any(w in cats for w in words) and k not in nb:
            nb.append(k)
    return biz, title_biz, nb


STOP = set('который которые также после более может могут будет были было этого этом году года '
           'россии российских российские заявил заявила сообщил сообщила сообщили рассказал '
           'стало стали время через между против всего около новые новый'.split())


def stems(title):
    words = re.findall(r'[а-яёa-z0-9]+', title.lower().replace('ё', 'е'))
    return {w[:6] for w in words if len(w) >= 4 and w not in STOP} | \
           {w for w in words if re.fullmatch(r'\d+[.,]?\d*', w) and len(w) >= 2}


def find_clusters(items, min_shared=3, min_jacc=0.28):
    """Пары/группы публикаций одного события из РАЗНЫХ изданий (по сходству заголовков)."""
    st = [stems(it['title']) for it in items]
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i]['source_name'] == items[j]['source_name']:
                continue
            a, b = st[i], st[j]
            inter = len(a & b)
            if inter >= min_shared and inter / max(1, len(a | b)) >= min_jacc:
                dt = abs((items[i]['_dt'] - items[j]['_dt']).total_seconds())
                if dt <= 3 * 86400:
                    parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i in range(len(items)):
        groups[find(i)].append(i)
    clusters = []
    for idx in groups.values():
        if len({items[i]['source_name'] for i in idx}) >= 2:
            clusters.append([items[i] for i in idx])
    clusters.sort(key=lambda c: (-len({x['source_name'] for x in c}), -max(x['_dt'] for x in c).timestamp()))
    return clusters


def select(pool, target, nonbiz_n, dup_clusters, max_share):
    chosen, seen = [], set()

    def take(it, reason):
        if it['_key'] in seen:
            return False
        seen.add(it['_key'])
        it['_reason'] = reason
        chosen.append(it)
        return True

    by_recency = sorted(pool, key=lambda x: (-x['_dt'].timestamp(), x['_key']))

    # 1. Все публикации Банка России за период (пресс-релизы и события).
    for it in by_recency:
        if it['source_name'] == 'Банк России':
            take(it, 'cbr')

    # 2. Кластеры одного события из разных изданий (для проверки дедупликации).
    biz_pool = [it for it in by_recency if it['_biz'] and not it['_nb']]
    n_cl = 0
    for cl in find_clusters(biz_pool):
        if n_cl >= dup_clusters:
            break
        per_src = {}
        for it in sorted(cl, key=lambda x: (-len(x['summary']), x['_key'])):
            per_src.setdefault(it['source_name'], it)
        for it in list(per_src.values())[:4]:
            take(it, 'dup_cluster')
        n_cl += 1

    # 3. Небизнесовые новости, поровну по spor/culture/incident, разные издания.
    nb_pool = [it for it in by_recency if it['_nb'] and not it['_title_biz']]
    buckets = {k: [it for it in nb_pool if it['_nb'][0] == k] for k in NONBIZ_TOPICS}
    src_cnt = Counter()
    got = 0
    while got < nonbiz_n and any(buckets.values()):
        for k in NONBIZ_TOPICS:
            if got >= nonbiz_n or not buckets[k]:
                continue
            buckets[k].sort(key=lambda x: (src_cnt[x['source_name']], -x['_dt'].timestamp(), x['_key']))
            it = buckets[k].pop(0)
            if take(it, 'nonbiz'):
                src_cnt[it['source_name']] += 1
                got += 1

    # 4. Экономика/бизнес: round-robin по темам с ограничением доли издания.
    strong = [it for it in biz_pool if set(it['_biz']) - WEAK_TOPICS]
    weak = [it for it in biz_pool if not set(it['_biz']) - WEAK_TOPICS]
    topic_q = {k: [it for it in strong if k in it['_biz']] for k in BIZ_TOPICS}
    for q in topic_q.values():  # сначала с текстом и свежие
        q.sort(key=lambda x: (not x['summary'], -x['_dt'].timestamp(), x['_key']))
    src_total = Counter(it['source_name'] for it in chosen)
    cap = max(10, int(target * max_share))
    progress = True
    while len(chosen) < target and progress:
        progress = False
        for k in BIZ_TOPICS:
            if len(chosen) >= target:
                break
            q = topic_q[k]
            while q:
                it = q.pop(0)
                if it['_key'] in seen or src_total[it['source_name']] >= cap:
                    continue
                take(it, 'biz')
                src_total[it['source_name']] += 1
                progress = True
                break
    # Добор общими экономическими новостями, если тематических не хватило.
    for it in strong + weak:
        if len(chosen) >= target:
            break
        if it['_key'] not in seen and src_total[it['source_name']] < cap:
            take(it, 'biz')
            src_total[it['source_name']] += 1
    return chosen


# --- main --------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default='data/news_snapshot.json')
    ap.add_argument('--days', type=float, default=14, help='окно публикаций, дней назад от --now')
    ap.add_argument('--target', type=int, default=200, help='целевое число публикаций в выгрузке')
    ap.add_argument('--nonbiz', type=int, default=25, help='сколько небизнесовых новостей оставить')
    ap.add_argument('--dup-clusters', type=int, default=8, help='сколько межисточниковых кластеров одного события включить')
    ap.add_argument('--max-source-share', type=float, default=0.3, help='макс. доля одного издания в бизнес-доборе')
    ap.add_argument('--now', help='опорное время ISO 8601 (для воспроизводимого офлайн-отбора)')
    ap.add_argument('--save-raw', help='каталог, куда сохранить сырые ленты')
    ap.add_argument('--from-raw', help='каталог с ранее сохранёнными лентами (без сети)')
    ap.add_argument('--cafile', action='append', default=[], help='доп. CA-бандл (можно несколько)')
    args = ap.parse_args()

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(MSK).replace(microsecond=0)
    if now.tzinfo is None:
        now = now.replace(tzinfo=MSK)
    since = now - timedelta(days=args.days)

    ctx = None
    if not args.from_raw:
        ctx, loaded = make_ssl_context(args.cafile)
        print(f'CA: /etc/ssl/cert.pem + {len(loaded)} доп. бандл(ов)', file=sys.stderr)
    if args.save_raw:
        Path(args.save_raw).mkdir(parents=True, exist_ok=True)

    sources, pool, by_key = [], [], {}
    for feed_name, publisher, url in FEEDS:
        rec = {'name': feed_name, 'url': url, 'fetched': 0, 'kept': 0, 'error': None}
        sources.append(rec)
        try:
            if args.from_raw:
                data = (Path(args.from_raw) / slug(url)).read_bytes()
            else:
                data = fetch(url, ctx)
                if args.save_raw:
                    (Path(args.save_raw) / slug(url)).write_bytes(data)
            raw_items = parse_feed(data, url)
        except Exception as e:  # noqa: BLE001 — ошибка одной ленты не роняет запуск
            rec['error'] = f'{type(e).__name__}: {e}'[:300]
            continue
        rec['fetched'] = len(raw_items)
        for f in raw_items:
            title = clean_text(f['title'])
            link = f['link']
            dt = parse_date(f['date'])
            if not title or not link or dt is None:
                continue
            key = normalize_url(link)
            if key in by_key:  # дубль по URL (напр. лента новостей и рубрика Коммерсанта)
                continue
            full = clean_text(f['full'])
            desc = clean_text(f['description'])
            summary = truncate(full if len(full) > len(desc) else desc)
            it = {'title': title, 'summary': summary, 'url': link, 'source_name': publisher,
                  'published_at': dt.isoformat(), '_dt': dt, '_key': key, '_feed': feed_name,
                  '_cats': f['category']}
            by_key[key] = it
            if since <= dt <= now + timedelta(hours=1):
                pool.append(it)

    for it in pool:
        it['_biz'], it['_title_biz'], it['_nb'] = topics_of(it)

    chosen = select(pool, args.target, args.nonbiz, args.dup_clusters, args.max_source_share)
    chosen.sort(key=lambda x: (-x['_dt'].timestamp(), x['_key']))
    kept = Counter(it['_feed'] for it in chosen)
    for rec in sources:
        rec['kept'] = kept.get(rec['name'], 0)

    out = {
        'generated_at': now.isoformat(),
        'sources': sources,
        'items': [{k: it[k] for k in ('title', 'summary', 'url', 'source_name', 'published_at')}
                  for it in chosen],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    # --- сводка ---
    print(f'\nОкно: {since.isoformat()} … {now.isoformat()}; в окне после дедупликации: {len(pool)}')
    print(f'{"лента":42} {"fetched":>7} {"kept":>5}  ошибка')
    for rec in sources:
        print(f'{rec["name"]:42} {rec["fetched"]:>7} {rec["kept"]:>5}  {rec["error"] or ""}')
    print(f'\nИтого в выгрузке: {len(chosen)} -> {args.out}')
    print('По причине отбора:', dict(Counter(it['_reason'] for it in chosen)))
    print('По изданиям:', dict(Counter(it['source_name'] for it in chosen)))
    tc = Counter()
    for it in chosen:
        if it['_reason'] != 'nonbiz':
            tc.update(it['_biz'])
    print('Темы (бизнес, ключевые слова):', dict(tc.most_common()))
    print('Небизнес:', dict(Counter(it['_nb'][0] for it in chosen if it['_reason'] == 'nonbiz')))
    print('Пустой summary:', sum(1 for it in chosen if not it['summary']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
