"""A07: инструменты агента — единый интерфейс (имя, схема аргументов, результат), allowlist.

Каждый инструмент: проверяет аргументы до выполнения, возвращает ToolResult со статусом
ok | empty | error, кратким описанием результата и source_id добавленных доказательств.
Инструменты только читают данные; ни один не выполняет внешних команд и не меняет состояние,
поэтому текст новости не может «запустить» действие (даже если в нём есть инструкции).
"""
from dataclasses import dataclass, field
from datetime import timedelta

from . import events as ev_mod
from .events import parse_dt
from .mechanisms import candidates
from .ranking import score
from .textproc import similarity

GRAPH_KEYS = ['payments_out.sectors', 'payments_in.sectors', 'payments_out.fts_countries', 'payments_out.top5_share',
              'payments_in.top5_share', 'payments_out.counterparties', 'payments_in.counterparties', 'group', 'revenue_rank',
              'persons']


@dataclass
class ToolResult:
    status: str
    summary: str
    data: object = None
    source_ids: list = field(default_factory=list)


class ToolError(Exception):
    pass


class Tools:
    """Реестр. ctx — общий контекст анализа (компания, новость, событие, доказательства)."""

    SPEC = {
        'get_company_profile': {'title': 'Профиль компании', 'args': {'company_id': str},
                                'desc': 'Прямые наблюдения профиля (ОКВЭД, выручка, продукты, ВЭД, регион) с источниками'},
        'get_graph_context': {'title': 'Граф связей (1 шаг)', 'args': {'company_id': str},
                              'desc': 'Отрасли/регионы/страны контрагентов по платежам, группа, связанные лица'},
        'get_news': {'title': 'Новость', 'args': {'news_id': str}, 'desc': 'Текст и метаданные новости'},
        'extract_event': {'title': 'Структурирование события', 'args': {'news_id': str},
                          'desc': 'Тип события, отрасли, регионы, направление, участники, цитаты'},
        'score_relevance': {'title': 'Оценка значимости для компании', 'args': {'company_id': str, 'news_id': str},
                            'desc': 'Объяснимый score и причины'},
        'search_bank_analytics': {'title': 'Поиск позиции Альфа-Банка', 'args': {'query': str},
                                  'desc': 'Фрагменты аналитики банка с документом, страницей и датой'},
        'find_related_news': {'title': 'Сообщения других источников', 'args': {'news_id': str},
                              'desc': 'Похожие публикации о том же событии (для сверки фактов)'},
        'match_mechanisms': {'title': 'Механизмы влияния', 'args': {'company_id': str},
                             'desc': 'Применимые цепочки событие → признак клиента → последствие'},
    }

    def __init__(self, profiles, bank, store, ctx: dict, evidence):
        self.profiles, self.bank, self.store, self.ctx, self.ev = profiles, bank, store, ctx, evidence

    def call(self, name: str, args: dict) -> ToolResult:
        spec = self.SPEC.get(name)
        if not spec:
            raise ToolError(f'инструмент {name} не разрешён')
        clean = {}
        for k, typ in spec['args'].items():
            v = args.get(k)
            if not isinstance(v, typ) or not str(v).strip():
                raise ToolError(f'{name}: неверный аргумент {k}')
            clean[k] = str(v).strip()[:300]
        # граница доступа: инструменты работают только с компанией и новостью текущего анализа
        if 'company_id' in clean and clean['company_id'] != self.ctx['company_id']:
            raise ToolError('доступ к другой компании запрещён')
        if 'news_id' in clean and clean['news_id'] != self.ctx['news_id']:
            raise ToolError('доступ к другой новости запрещён')
        return getattr(self, name)(**clean)

    # --- инструменты ---
    def get_company_profile(self, company_id):
        p = self.profiles.get(company_id)
        if not p:
            return ToolResult('error', 'компания не найдена')
        ids = []
        for f, o in p['observed'].items():
            if o['value'] is not None:
                ids.append(self.ev.add({'type': 'profile', 'id': f'P:{f}', 'title': o['title'], 'value': o['value'],
                                        'origin': o['source']}))
        self.ctx['profile'] = p
        missing = len(p['missing_fields'])
        return ToolResult('ok', f'{p["subtitle"]}; полей с данными {len(ids)}, пропусков {missing}; '
                          f'каналы: {", ".join(c["label"] for c in p["channels"].values()) or "нет"}', None, ids)

    def get_graph_context(self, company_id):
        ids = []
        for key in GRAPH_KEYS:
            f = self.profiles.fact(company_id, f'G:{key}')
            if f and f['value'] not in (None, [], {}):
                ids.append(self.ev.add(f))
        d = self.profiles.get(company_id)['derived']
        po, pi = d['payments_out'], d['payments_in']
        if not po['counterparties'] and not pi['counterparties']:
            return ToolResult('empty', 'платёжных связей в данных нет', None, ids)
        return ToolResult('ok', f'получателей {po["counterparties"]}, плательщиков {pi["counterparties"]}; '
                          f'группа: {(d["group"] or {}).get("size", "—")} комп.', None, ids)

    def get_news(self, news_id):
        n = self.store.get_news(news_id)
        if not n:
            return ToolResult('error', 'новость не найдена')
        self.ctx['news'] = n
        sid = self.ev.add({'type': 'news', 'id': f'N:{n["id"]}', 'title': n['title'], 'url': n['url'],
                           'source_name': n['source_name'], 'published_at': n['published_at'],
                           'text': (n.get('content') or n.get('summary') or '')[:4000]})
        return ToolResult('ok', f'{n["source_name"]}: {n["title"][:100]}', None, [sid])

    def extract_event(self, news_id):
        e = ev_mod.extract_event(self.ctx['news'], self.profiles.regions)
        self.ctx['event'] = e
        status = 'ok' if e['business_relevant'] else 'empty'
        return ToolResult(status, f'{e["event_label"]}; отрасли: {", ".join(e["sector_labels"]) or "—"}; '
                          f'направление: {e["direction"] or "не указано"}', e, [f'N:{news_id}'])

    def score_relevance(self, company_id, news_id):
        cov, _ = self.bank.coverage(ev_mod.bank_query(self.ctx['event'], self.ctx['news']),
                                    as_of=str(self.ctx['news'].get('published_at') or '')[:10] or None)
        r = score(self.ctx['profile'], self.ctx['event'], cov, self.ctx['news'].get('published_at'))
        self.ctx['relevance'] = r
        return ToolResult('ok', f'score {r["score"]} ({r["level"]}); {r["why_short"]}', r,
                          [e for c in r['components'] for e in c['evidence']])

    def search_bank_analytics(self, query):
        as_of = str(self.ctx['news'].get('published_at') or '')[:10] or None
        seen = {h['chunk_id'] for h in self.ctx.setdefault('bank_hits', [])}
        hits = self.bank.search(query, k=6, topics=self.ctx.get('event', {}).get('bank_topics'), as_of=as_of, exclude=seen)
        ids = []
        for h in hits:
            self.ctx['bank_hits'].append(h)
            ids.append(self.ev.add({'type': 'bank', 'id': h['source_id'], 'doc_id': h['doc_id'], 'doc_title': h['doc_title'],
                                    'page': h['page'], 'url': h['url'], 'published_at': h['published_at'],
                                    'text': h['text'], 'warning': h['warning'], 'score': h['score']}))
        if not hits:
            return ToolResult('empty', 'релевантных фрагментов не найдено', [], [])
        self.ctx['bank_hits'].sort(key=lambda h: -h['score'])
        return ToolResult('ok', '; '.join(f'«{h["doc_title"][:50]}» стр.{h["page"]} ({h["score"]})' for h in hits[:3]), hits, ids)

    def find_related_news(self, news_id):
        n = self.ctx['news']
        dt = parse_dt(n.get('published_at'))
        since = (dt - timedelta(days=4)).isoformat() if dt else None
        related = []
        for other in self.store.list_news(since_iso=since, limit=400):
            if other['id'] == n['id']:
                continue
            od = parse_dt(other.get('published_at'))
            if dt and od and abs((od - dt).total_seconds()) > 4 * 86400:
                continue
            sim = similarity(n['title'], other['title'])
            if sim >= 0.3:
                related.append((sim, other))
        related.sort(key=lambda x: -x[0])
        ids = []
        out = []
        for sim, o in related[:4]:
            ids.append(self.ev.add({'type': 'news', 'id': f'N:{o["id"]}', 'title': o['title'], 'url': o['url'],
                                    'source_name': o['source_name'], 'published_at': o['published_at'],
                                    'text': (o.get('content') or o.get('summary') or '')[:2000]}))
            out.append({'news_id': o['id'], 'title': o['title'], 'source_name': o['source_name'], 'url': o['url'],
                        'published_at': o['published_at'], 'similarity': round(sim, 2)})
        self.ctx['related_news'] = out
        if not out:
            return ToolResult('empty', 'других сообщений о событии не найдено', [], [])
        return ToolResult('ok', f'найдено {len(out)}: ' + ', '.join(o['source_name'] for o in out), out, ids)

    def match_mechanisms(self, company_id):
        m = candidates(self.ctx['event'], self.ctx['profile'])
        self.ctx['mechanisms'] = m
        if not m:
            return ToolResult('empty', 'применимых механизмов не найдено', [], [])
        return ToolResult('ok', '; '.join(f'{x["channel_label"]} → {x["kind"]}' for x in m), m,
                          [b for x in m for b in x['basis']])

    def catalog(self) -> list[dict]:
        return [{'name': k, 'title': v['title'], 'args': list(v['args']), 'description': v['desc']} for k, v in self.SPEC.items()]
