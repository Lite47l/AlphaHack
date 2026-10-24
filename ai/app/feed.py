"""Персонализированная лента: события новостей (кэш), склейка дублей, ранжирование под компанию."""
import threading
from datetime import datetime, timedelta, timezone

from .events import EXTRACTOR_VERSION, bank_query, extract_event, parse_dt
from .ranking import score
from .textproc import tokens


class FeedService:
    def __init__(self, profiles, bank, store):
        self.profiles, self.bank, self.store = profiles, bank, store
        self._events: dict[str, dict] = {}
        self._cov: dict[str, tuple[float, list]] = {}
        self._clusters: tuple[tuple, dict] | None = None
        self._lock = threading.Lock()

    def events_for(self, news: list[dict]) -> dict[str, dict]:
        missing = [n for n in news if n['id'] not in self._events]
        if missing:
            stored = self.store.get_events([n['id'] for n in missing], EXTRACTOR_VERSION)
            for n in missing:
                e = stored.get(n['id'])
                if e is None:
                    e = extract_event(n, self.profiles.regions)
                    self.store.put_event(n['id'], EXTRACTOR_VERSION, e)
                with self._lock:
                    self._events[n['id']] = e
        return {n['id']: self._events[n['id']] for n in news}

    def coverage(self, n: dict, e: dict) -> tuple[float, list]:
        if n['id'] not in self._cov:
            self._cov[n['id']] = self.bank.coverage(bank_query(e, n), as_of=str(n.get('published_at') or '')[:10] or None) \
                if e['business_relevant'] else (0.0, [])
        return self._cov[n['id']]

    def recent_news(self, days: int) -> list[dict]:
        news = self.store.list_news(limit=600)
        if not news:
            return []
        latest = max((parse_dt(n['published_at']) for n in news if parse_dt(n['published_at'])),
                     default=datetime.now(timezone.utc))
        # окно считается от самой свежей новости: офлайн-снимок не «устаревает» при демонстрации
        since = latest - timedelta(days=days)
        return [n for n in news if (parse_dt(n['published_at']) or latest) >= since]

    def clusters(self, news: list[dict]) -> dict[str, list[str]]:
        """Склейка сообщений об одном событии (похожие заголовки в пределах 3 дней). Первоисточники сохраняются."""
        key = tuple(n['id'] for n in news)
        if self._clusters and self._clusters[0] == key:
            return self._clusters[1]
        toks = {n['id']: set(tokens(n['title'])) for n in news}
        dates = {n['id']: parse_dt(n['published_at']) for n in news}
        parent: dict[str, str] = {}
        order = sorted(news, key=lambda n: (-(len(n.get('content') or n.get('summary') or '')), n['id']))
        reps: list[str] = []
        for n in order:
            nid, best = n['id'], None
            for r in reps:
                a, b = toks[nid], toks[r]
                if not a or not b:
                    continue
                sim = len(a & b) / len(a | b)
                close = not dates[nid] or not dates[r] or abs((dates[nid] - dates[r]).total_seconds()) < 3 * 86400
                if sim >= 0.45 and close:
                    best = r
                    break
            if best:
                parent[nid] = best
            else:
                reps.append(nid)
        groups = {r: [] for r in reps}
        for c, r in parent.items():
            groups[r].append(c)
        self._clusters = (key, groups)
        return groups

    def feed(self, company_id: str, limit: int = 20, days: int = 45, include_filtered: bool = False) -> dict | None:
        p = self.profiles.get(company_id)
        if not p:
            return None
        news = self.recent_news(days)
        by_id = {n['id']: n for n in news}
        events = self.events_for(news)
        groups = self.clusters(news)
        items, filtered = [], []
        stats = {'news_considered': len(news), 'clusters': len(groups), 'filtered_non_business': 0, 'filtered_low_relevance': 0}
        for rep, dups in groups.items():
            n, e = by_id[rep], events[rep]
            cov, hits = self.coverage(n, e)
            rel = score(p, e, cov, n['published_at'])
            item = self.item(n, e, rel, hits, [by_id[d] for d in dups])
            if not e['business_relevant']:
                stats['filtered_non_business'] += 1
                item['filtered_reason'] = 'non_business'
                filtered.append(item)
            elif rel['level'] == 'none':
                stats['filtered_low_relevance'] += 1
                item['filtered_reason'] = 'low_relevance'
                filtered.append(item)
            else:
                items.append(item)
        items = self.diversify(items)
        filtered.sort(key=lambda x: -x['relevance']['score'])
        stats['shown'] = min(limit, len(items))
        stats['significant'] = sum(1 for x in items if x['relevance']['level'] in ('high', 'medium'))
        return {'company_id': company_id, 'generated_at': datetime.now(timezone.utc).isoformat(), 'items': items[:limit],
                'filtered': filtered[:60] if include_filtered else [], 'stats': stats}

    @staticmethod
    def diversify(items: list[dict]) -> list[dict]:
        """Порядок ленты с учётом разнообразия: повтор того же типа события и отрасли слегка понижает позицию
        (score в карточке не меняется, это только порядок показа)."""
        pool = sorted(items, key=lambda x: -x['relevance']['score'])
        out, seen = [], {}
        while pool:
            def adj(x):
                k = (x['event']['event_type'], (x['event']['sectors'] or [''])[0])
                return x['relevance']['score'] * (0.9 ** seen.get(k, 0))
            best = max(pool, key=adj)
            pool.remove(best)
            k = (best['event']['event_type'], (best['event']['sectors'] or [''])[0])
            seen[k] = seen.get(k, 0) + 1
            out.append(best)
        return out

    @staticmethod
    def item(n, e, rel, hits, dups):
        return {
            'news_id': n['id'], 'title': n['title'], 'summary': (n.get('summary') or '')[:500], 'url': n['url'],
            'source_name': n['source_name'], 'published_at': n['published_at'], 'origin': n.get('origin'),
            'event': {k: e.get(k) for k in ('event_type', 'event_label', 'sectors', 'sector_labels', 'direction', 'regions')},
            'relevance': rel,
            'duplicates': [{'news_id': d['id'], 'title': d['title'], 'source_name': d['source_name'], 'url': d['url']} for d in dups],
            'bank_coverage': {'found': bool(hits) and rel['components'][-1]['value'] >= 0.35 if rel['components'] else False,
                              'docs': list({h['doc_id']: {'doc_id': h['doc_id'], 'title': h['doc_title']} for h in hits}.values())},
            'filtered_reason': None,
        }

    def relevance(self, news_id: str, company_ids: list[str]) -> dict | None:
        n = self.store.get_news(news_id)
        if not n:
            return None
        e = self.events_for([n])[n['id']]
        cov, _ = self.coverage(n, e)
        results = []
        for cid in company_ids[:6]:
            p = self.profiles.get(cid)
            if p:
                results.append({'company_id': cid, 'display_name': p['display_name'], 'subtitle': p['subtitle'],
                                'relevance': score(p, e, cov, n['published_at'])})
        return {'news': n, 'event': e, 'results': results}
