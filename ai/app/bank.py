"""A05: поиск по аналитике Альфа-Банка (retrieve_bank_context).

Минимальный поиск без внешней embedding-модели: BM25 по стеммированным токенам с
расширением запроса синонимами. Каждый результат несёт координаты источника
(документ, страница, фрагмент), дату и предупреждение об устаревании.
Документы банка не подменяются материалами из интернета.
"""
import json
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path

from .config import settings
from .textproc import sentences, tokens

VIEW_MARKERS = re.compile(r'\b(мы ожида|ожидаем|мы полага|полагаем|считаем|прогноз|наш взгляд|по нашим оценкам|наш базовый|сохраняем|меняем наш)', re.I)

SYNONYMS = {
    'ставк': ['ключев', 'дкп', 'цб', 'процент'],
    'ключев': ['ставк', 'дкп'],
    'инфляц': ['цен', 'ипц', 'дефляц'],
    'кредит': ['кредитован', 'заемщик', 'долг', 'ставк'],
    'потреблен': ['спрос', 'розничн', 'оборот'],
    'спрос': ['потреблен', 'розничн'],
    'труд': ['зарплат', 'безработиц', 'занятост', 'персонал'],
    'зарплат': ['труд', 'доход', 'оплат'],
    'бензин': ['топлив', 'дизел', 'нефт'],
    'топлив': ['бензин', 'дизел', 'нефт'],
    'нефт': ['топлив', 'urals', 'сырь'],
    'курс': ['рубл', 'валют', 'доллар', 'юан'],
    'рубл': ['курс', 'валют'],
    'облигац': ['офз', 'доходност', 'долгов'],
    'офз': ['облигац', 'доходност'],
    'золот': ['драгмет', 'унци'],
    'стал': ['металл', 'металлург'],
    'металл': ['стал', 'металлург'],
    'ввп': ['рост', 'экономик', 'промпроизводств'],
    'импорт': ['торговл', 'внешн', 'экспорт'],
    'экспорт': ['импорт', 'внешн', 'урожа'],
    'бюджет': ['минфин', 'дефицит', 'расход'],
    'ипотек': ['жиль', 'строительств', 'кредит'],
}


# Порог BM25 по заголовку для флага «есть аналитика банка» в ленте (подобран по ленте U_1595/U_34911:
# ставка/курс/инфляция/кредит ≥12, случайные совпадения — «алименты», «троян в приложении АЗС» — 7–11).
TOPICAL_MIN_SCORE = 12.0


class BankCorpus:
    def __init__(self, data: dict):
        self.version = data['version']
        self.extraction = data.get('extraction', '')
        self.docs = {d['doc_id']: d for d in data['documents']}
        self.chunks = {c['chunk_id']: c for c in data['chunks']}
        self._ids = list(self.chunks)
        self._tf = []
        self._df = Counter()
        for cid in self._ids:
            c = self.chunks[cid]
            doc = self.docs[c['doc_id']]
            toks = tokens(c['text']) + tokens(doc['title'])  # заголовок помогает тематическому поиску
            tf = Counter(toks)
            self._tf.append((tf, len(toks)))
            self._df.update(tf.keys())
        self._avgdl = sum(n for _, n in self._tf) / max(1, len(self._tf))
        self._title_tokens = {d: set(tokens(doc['title'])) for d, doc in self.docs.items()}

    @classmethod
    def load(cls, path: Path | None = None) -> 'BankCorpus':
        path = path or settings.data_dir / 'bank_corpus' / 'corpus.json'
        return cls(json.loads(Path(path).read_text(encoding='utf-8')))

    def _idf(self, t: str) -> float:
        n = len(self._ids)
        df = self._df.get(t, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def expand(self, query: str) -> list[str]:
        base = tokens(query)
        extra = []
        for t in base:
            for k, syn in SYNONYMS.items():
                if t.startswith(k[:6]) or (len(t) >= 4 and k.startswith(t)):
                    extra += syn
        return base + [tokens(s)[0] if tokens(s) else s for s in extra]

    def search(self, query: str, k: int = 5, topics: list[str] | None = None, as_of: str | None = None,
               min_score: float = 2.5, exclude: set[str] | None = None) -> list[dict]:
        q = self.expand(query)
        if not q:
            return []
        qc = Counter(q)
        base = set(tokens(query))
        scored = []
        for i, cid in enumerate(self._ids):
            if exclude and cid in exclude:
                continue
            tf, dl = self._tf[i]
            s = 0.0
            for t, qw in qc.items():
                f = tf.get(t, 0)
                if not f:
                    continue
                s += qw * self._idf(t) * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * dl / self._avgdl))
            c = self.chunks[cid]
            doc = self.docs[c['doc_id']]
            if VIEW_MARKERS.search(c['text']):
                s *= 1.25  # фрагмент содержит позицию/прогноз банка
            if c['quality'] != 'text':
                s *= 0.5  # распознанные таблицы — слабое доказательство
            title_overlap = len(base & self._title_tokens[c['doc_id']]) / max(1, len(base))
            s *= 1 + 0.8 * title_overlap  # совпадение с темой документа важнее случайного упоминания
            if topics and set(topics) & set(doc['topics']):
                s *= 1.4
            if as_of:
                try:
                    age = (date.fromisoformat(as_of[:10]) - date.fromisoformat(doc['published_at'])).days
                    if age >= 0:
                        s *= 1 + 0.3 * math.exp(-age / 60)  # при прочих равных — более свежая позиция банка
                except ValueError:
                    pass
            if s > 0:
                scored.append((s, cid))
        scored.sort(reverse=True)
        out, per_doc = [], Counter()
        for s, cid in scored:
            if s < min_score or len(out) >= k:
                break
            c = self.chunks[cid]
            if per_doc[c['doc_id']] >= 2:  # разнообразие источников
                continue
            per_doc[c['doc_id']] += 1
            out.append(self.hit(cid, s, query, as_of))
        return out

    def hit(self, cid: str, score: float, query: str, as_of: str | None = None) -> dict:
        c = self.chunks[cid]
        doc = self.docs[c['doc_id']]
        age_days = None
        if as_of:
            try:
                age_days = (date.fromisoformat(as_of[:10]) - date.fromisoformat(doc['published_at'])).days
            except ValueError:
                age_days = None
        warning = doc.get('date_note', '')
        if age_days is not None and age_days > 120:
            warning = (warning + ' ' if warning else '') + f'Материал опубликован за {age_days} дн. до события — позиция могла измениться.'
        qt = set(self.expand(query))

        def sent_score(s):
            view = 2 if VIEW_MARKERS.search(s) else 0  # предпочитаем позицию/прогноз банка пересказу фактов
            return len(qt & set(tokens(s))) + view - (3 if len(s) < 40 else 0)
        best = sorted(sentences(c['text']), key=lambda s: -sent_score(s))
        return {
            'source_id': f'B:{cid}', 'chunk_id': cid, 'doc_id': c['doc_id'], 'doc_title': doc['title'],
            'published_at': doc['published_at'], 'page': c['page'], 'url': doc['url'], 'score': round(score, 2),
            'quality': c['quality'], 'text': c['text'], 'key_sentence': best[0] if best else c['text'][:300],
            'age_days': age_days, 'warning': warning.strip(),
        }

    def coverage(self, query: str, as_of: str | None = None) -> tuple[float, list[dict]]:
        hits = self.search(query, k=3, as_of=as_of)
        if not hits:
            return 0.0, []
        top = hits[0]['score']
        return min(1.0, top / 25.0), hits

    def topical_hits(self, title: str, topics: list[str], as_of: str | None = None,
                     min_score: float = TOPICAL_MIN_SCORE) -> list[dict]:
        """Фрагменты аналитики, которые действительно про событие: документ размечен темой события
        (topics корпуса ∩ bank_topics события) и фрагмент заметно совпадает с заголовком новости.
        Поиск — только по заголовку: служебные слова типа события не «притягивают» любой документ темы."""
        if not topics:
            return []
        hits = self.search(title, k=5, as_of=as_of, min_score=min_score)
        return [h for h in hits if set(self.docs[h['doc_id']]['topics']) & set(topics)]

    def documents(self) -> list[dict]:
        return sorted(self.docs.values(), key=lambda d: d['published_at'], reverse=True)
