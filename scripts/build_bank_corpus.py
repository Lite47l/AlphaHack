#!/usr/bin/env python3
"""O06/A05: сборка корпуса аналитики Альфа-Банка из OCR-разметки страниц.

PDF из кейса — сканы без текстового слоя. Текст распознаётся скриптом
scripts/ocr_vision.swift (Apple Vision, ru+en) в JSON вида
{"<doc>__pNN.png": [{"x","y","w","h","t"}, ...]}, затем этот скрипт:

1. восстанавливает порядок чтения (полноширинные строки + колонки);
2. убирает колонтитулы и юридический дисклеймер;
3. режет текст на фрагменты с привязкой к документу и странице;
4. помечает фрагменты, похожие на распознанные таблицы (quality=table_like) —
   их содержание не исправляется и не дополняется.

Запуск:
  python3 scripts/build_bank_corpus.py --ocr ocr_boxes.json --out data/bank_corpus/corpus.json
"""
import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

# Реестр документов (Y03). Названия — как в Приложении 2 кейса; дата — из шапки документа.
DOCS = {
    'ALFA-Macro_Insights-Policy_Rate_11Sep': {
        'doc_id': 'alfa-key-rate-2026-09-11',
        'title': 'Ключевая ставка ЦБ РФ: ставка без изменения на 14,0%, риторика стала жестче',
        'published_at': '2026-09-11', 'kind': 'macro', 'drive_id': '1shHG89LtMgHT1_uEebHmQSFZe_zbeq7-',
        'topics': ['key_rate', 'inflation', 'credit'],
    },
    'Inflation_tracker_02': {
        'doc_id': 'alfa-inflation-2026-09-02',
        'title': 'Инфляция 25–31 августа: основные выводы',
        'published_at': '2026-09-02', 'kind': 'macro', 'drive_id': '19iW3Ph8_wO0HHQY7Ik4lTfC3jRc9gjWV',
        'topics': ['inflation', 'fuel', 'key_rate'],
    },
    'ALFA-7M26': {
        'doc_id': 'alfa-macrostat-7m26-2026-09-07',
        'title': 'Макростатистика 7М26: данные по рынку труда не подтверждают охлаждения экономики',
        'published_at': '2026-09-07', 'kind': 'macro', 'drive_id': '1HZDq3WGRFdzgm1TZ5hWL23Q3I9c2Eq64',
        'topics': ['labor_market', 'consumption', 'gdp', 'key_rate'],
    },
    'ALFA-macro_stat1H26': {
        'doc_id': 'alfa-macrostat-1h26-2026-07-31',
        'title': 'Макростатистика 1П26: слабый рост 1П26 смещает прогноз роста ВВП на 0,1% за год',
        'published_at': '2026-07-31', 'kind': 'macro', 'drive_id': '1khcHwoS0FkG9p_0J4XoHGaGq3B4V0ime',
        'topics': ['gdp', 'industry', 'trade', 'budget'],
    },
    'ALFA-consumption': {
        'doc_id': 'alfa-consumption-2026-08-05',
        'title': 'Потребление на пике',
        'published_at': '2026-08-05', 'kind': 'macro', 'drive_id': '1riR1lhsb6EY1MwGMxdBlS_tI5ed9mIiz',
        'topics': ['consumption', 'retail', 'credit', 'labor_market'],
    },
    'FI_Strategy_3Q26_22072026': {
        'doc_id': 'alfa-fi-strategy-3q26-2026-07-22',
        'title': 'Тактический взгляд на 3-й квартал 2026 года: время собирать камни',
        'published_at': '2026-07-22', 'kind': 'debt_market', 'drive_id': '1hq3Fhyz9ce_sRyGUQB1MdoHeQdfAJfhK',
        'topics': ['bonds', 'key_rate', 'credit', 'fx'],
    },
    'Бонд_Бриф_14092026': {
        'doc_id': 'alfa-bond-brief-2026-09-14',
        'title': 'Бонд Бриф: итоги недели',
        'published_at': '2026-09-14', 'kind': 'debt_market', 'drive_id': '1bPzix_332N2CyMY0tqCHuYtGsfJWnFGv',
        'topics': ['bonds', 'key_rate', 'credit'],
    },
    'Gold_digest_August26': {
        'doc_id': 'alfa-gold-digest-2026-08',
        'title': 'Обзор рынка золота, август 2026',
        'published_at': '2026-09-01', 'kind': 'commodities', 'drive_id': '1a7TXOCHARfKzUR0hn9Cm9gQSrIldxTDE',
        'topics': ['gold', 'commodities', 'fx'],
        'date_note': 'В документе указан месяц (август 2026); точная дата публикации не указана.',
    },
    'ALFA_Russian_Steels_1К21PreviewUpdate_15Apr2021': {
        'doc_id': 'alfa-russian-steel-2021-04-15',
        'title': 'Commodities performance: Российская сталь — ралли цен продолжается (прогноз за 1К21)',
        'published_at': '2021-04-15', 'kind': 'commodities', 'drive_id': '1yLCBrIoyIsubLTEBvBHh6io48ysnW-wn',
        'topics': ['metals', 'commodities', 'export'],
        'date_note': 'Материал 2021 года: использовать только как отраслевой фон, не как текущую позицию банка.',
    },
}

BOILERPLATE = [
    re.compile(r'^(А|A)$'),
    re.compile(r'^центр макроэкономического анализа$', re.I),
    re.compile(r'^альфа[- ]?банк$', re.I),
    re.compile(r'^\d{1,2}$'),
]
DISCLAIMER_START = re.compile(r'(Альфа-Банк, 20\d\d|Все права защищены|Генеральная лицензия ЦБ|исключительной собственностью)', re.I)


def reading_order(rows):
    """Полноширинные строки разделяют страницу на полосы; внутри полосы колонки читаются слева направо."""
    rows = [r for r in rows if r['t'].strip()]
    rows.sort(key=lambda r: (round(r['y'], 3), r['x']))
    out, band = [], []

    def flush():
        if not band:
            return
        # Межколоночный промежуток — вертикаль, которую пересекает минимум строк полосы.
        # Колонки стоят почти вплотную, а выключенный по ширине текст дробится OCR на слова,
        # поэтому края строк сжимаются и допускается небольшое число пересечений (заголовки).
        def split(lines, lo, hi):
            best = None
            pos = lo + 0.15
            while pos < hi - 0.15:
                crossing = sum(1 for r in lines if r['x'] + 0.015 < pos < r['x'] + r['w'] - 0.015)
                left = sum(1 for r in lines if r['x'] + r['w'] / 2 < pos)
                if left >= 4 and len(lines) - left >= 4 and (best is None or crossing < best[0]):
                    best = (crossing, pos)
                pos += 0.005
            if best is None or best[0] > max(1, 0.08 * len(lines)):
                return [sorted(lines, key=lambda r: (round(r['y'] / 0.006), r['x']))]
            cut = best[1]
            return (split([r for r in lines if r['x'] + r['w'] / 2 < cut], lo, cut)
                    + split([r for r in lines if r['x'] + r['w'] / 2 >= cut], cut, hi))

        for column in split(band, 0.0, 1.0):
            out.extend(column)
        band.clear()

    for r in rows:
        if r['w'] > 0.55:
            flush()
            out.append(r)
        else:
            band.append(r)
    flush()
    return [r['t'].strip() for r in out]


def clean_lines(lines):
    kept = []
    for t in lines:
        if DISCLAIMER_START.search(t):
            break  # дисклеймер всегда в конце страницы
        if any(p.match(t.strip()) for p in BOILERPLATE):
            continue
        kept.append(t)
    return kept


def text_quality(text):
    words = re.findall(r'[А-Яа-яЁёA-Za-z]{3,}', text)
    tokens = text.split()
    if not tokens:
        return 'empty'
    return 'text' if len(words) / len(tokens) >= 0.45 else 'table_like'


def chunk_page(lines, target=700):
    text = ' '.join(lines)
    text = re.sub(r'-\s+(?=[а-яё])', '', text)  # переносы слов
    text = re.sub(r'\s+', ' ', text).strip()
    sentences = re.split(r'(?<=[.!?])\s+(?=[А-ЯЁA-Z«•])', text)
    chunks, cur = [], ''
    for s in sentences:
        if cur and len(cur) + len(s) > target:
            chunks.append(cur.strip())
            cur = ''
        cur += ' ' + s
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def build(ocr_path, out_path):
    ocr = json.loads(Path(ocr_path).read_text(encoding='utf-8'))
    pages = defaultdict(dict)
    for key, rows in ocr.items():
        stem, page = key.rsplit('__p', 1)
        pages[stem][int(page.split('.')[0])] = rows
    docs, chunks = [], []
    for stem, meta in DOCS.items():
        if stem not in pages:
            raise SystemExit(f'нет OCR для {stem}')
        doc_text = []
        for page in sorted(pages[stem]):
            lines = clean_lines(reading_order(pages[stem][page]))
            for i, c in enumerate(chunk_page(lines)):
                if len(c) < 60:
                    continue
                chunks.append({
                    'chunk_id': f"{meta['doc_id']}#p{page}-{i + 1}",
                    'doc_id': meta['doc_id'], 'page': page, 'text': c,
                    'quality': text_quality(c),
                })
                doc_text.append(c)
        docs.append({
            'doc_id': meta['doc_id'], 'title': meta['title'], 'institution': 'Альфа-Банк',
            'published_at': meta['published_at'], 'kind': meta['kind'], 'topics': meta['topics'],
            'pages': len(pages[stem]), 'file_name': f'{stem}.pdf',
            'url': f"https://drive.google.com/file/d/{meta['drive_id']}/view",
            'date_note': meta.get('date_note', ''),
            'text_sha256': hashlib.sha256('\n'.join(doc_text).encode()).hexdigest(),
        })
    corpus = {
        'version': hashlib.sha256(json.dumps(chunks, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12],
        'extraction': 'Apple Vision OCR (ru-RU, en-US), 200 dpi; таблицы и графики распознаются частично',
        'documents': docs, 'chunks': chunks,
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(corpus, ensure_ascii=False, indent=1), encoding='utf-8')
    bad = sum(c['quality'] != 'text' for c in chunks)
    print(f'документов: {len(docs)}, фрагментов: {len(chunks)}, table_like: {bad}, версия {corpus["version"]}')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--ocr', required=True)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    build(a.ocr, a.out)
