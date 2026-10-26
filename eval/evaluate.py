"""Офлайн-оценка персонализации ленты на разметке eval/labels*.csv (L08; метки автоматические, см. docs/evaluation_report.md).

Запуск из корня репозитория (нужны зависимости ai/requirements.txt, в первую очередь pandas):

    python3 eval/evaluate.py            # таблица в stdout + eval/results.json
    python3 eval/evaluate.py --labels-from llm   # эталон — вторая разметка моделью (eval/labels_llm.csv), без записи

Что делает:
  1. читает eval/labels.csv (пары компания × новость, метка 0/1/2, split dev/holdout) и, если есть,
     eval/labels_fresh.csv (split fresh — разметка, сделанная после правок ядра, до расчёта их score);
  2. для каждой пары считает score текущим ранжировщиком ai/app/ranking.py так же, как лента
     (rules-извлечение события → покрытие аналитикой банка → score), с фиксированным «сейчас» =
     generated_at снимка новостей, чтобы свежесть не зависела от дня запуска;
  3. считает Precision@3 (label ≥ 1 и строго label = 2) и nDCG@5 по каждой компании и в среднем,
     отдельно для dev / holdout / all; то же — для baseline'ов;
  4. пишет eval/results.json с метриками и разбором по каждой паре (компоненты score).

Метрики tie-aware: при равных score берётся матожидание по всем порядкам внутри группы равных
(иначе baseline «только макрозначимость» зависел бы от порядка строк в CSV).
Профили грузятся так же, как в сервисе: ProfileStore.load() (сырые CSV из data/raw или RAW_DATA_DIR, порог
SEGMENT_MIN_REVENUE, кэш в STATE_DIR); если сырых данных нет — data/generated/profiles.json, а пары с компаниями,
которых там нет, пропускаются с предупреждением (метрики тогда считаются по меньшему набору).
Код в ai/ не меняется — только импортируется. Другую версию ядра можно оценить так:
    git archive HEAD ai | tar -x -C /tmp/before && EVAL_AI_DIR=/tmp/before/ai python3 eval/evaluate.py
(результат перезапишет eval/results.json — после этого перезапустите без EVAL_AI_DIR).
"""
import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('DATA_DIR', str(ROOT / 'data'))
os.environ['DATABASE_URL'] = ''  # только память, без БД
sys.path.insert(0, os.environ.get('EVAL_AI_DIR') or str(ROOT / 'ai'))  # EVAL_AI_DIR — прогон другой версии ядра

from app.bank import BankCorpus  # noqa: E402
from app.events import EXTRACTOR_VERSION, bank_query, extract_event, parse_dt  # noqa: E402
from app.profiles import ProfileStore, channels_for  # noqa: E402
from app.ranking import WEIGHTS, score  # noqa: E402
from app.storage import MemoryStore  # noqa: E402

LABELS_CSV = ROOT / 'eval' / 'labels.csv'
LABELS_FRESH_CSV = ROOT / 'eval' / 'labels_fresh.csv'  # разметка после правок ядра, split=fresh
LABELS_LLM_CSV = ROOT / 'eval' / 'labels_llm.csv'  # вторая автоматическая разметка моделью (eval/llm_annotate.py)
RESULTS_JSON = ROOT / 'eval' / 'results.json'
SNAPSHOT = ROOT / 'data' / 'news_snapshot.json'
SYNTH_DIR = ROOT / 'data' / 'synthetic'
SPLITS = ('dev', 'holdout', 'all', 'fresh')  # all = dev + holdout; fresh — отдельно


def in_split(split: str, sp: str) -> bool:
    return split == sp or (sp == 'all' and split in ('dev', 'holdout'))


# ------------------------------------------------------------------ tie-aware метрики
def _groups(scored: list[tuple[float, int]]) -> list[list[int]]:
    """[(score, label)] → группы меток с равным score, по убыванию score."""
    out, cur, last = [], [], None
    for s, lab in sorted(scored, key=lambda x: -x[0]):
        if last is not None and abs(s - last) > 1e-12:
            out.append(cur)
            cur = []
        cur.append(lab)
        last = s
    if cur:
        out.append(cur)
    return out


def precision_at_k(scored, k: int, min_label: int) -> float:
    """Ожидаемая доля релевантных (label ≥ min_label) в топ-k при случайном порядке внутри равных score."""
    k = min(k, len(scored))
    if not k:
        return 0.0
    hits, pos = 0.0, 0
    for g in _groups(scored):
        take = min(len(g), k - pos)
        if take <= 0:
            break
        rel = sum(1 for lab in g if lab >= min_label)
        hits += take * rel / len(g)
        pos += take
    return hits / k


def ndcg_at_k(scored, k: int) -> float:
    """nDCG@k, gain = 2^label − 1; для равных score — средний gain группы на каждой её позиции."""
    def disc(i):
        return 1.0 / math.log2(i + 2)
    dcg, pos = 0.0, 0
    for g in _groups(scored):
        avg_gain = sum(2 ** lab - 1 for lab in g) / len(g)
        for _ in g:
            if pos >= k:
                break
            dcg += avg_gain * disc(pos)
            pos += 1
    ideal = sorted((2 ** lab - 1 for _, lab in scored), reverse=True)[:k]
    idcg = sum(g * disc(i) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


# ------------------------------------------------------------------ данные
def load_labels(labels_from: str = 'auto', only_agreed: bool = False) -> list[dict]:
    """Пары eval. labels_from='llm' — метка из eval/labels_llm.csv вместо автометки;
    only_agreed — только пары, где автометка и метка LLM совпали."""
    rows = []
    for path in (LABELS_CSV, LABELS_FRESH_CSV):
        if path.is_file():
            with path.open(encoding='utf-8') as f:
                rows += list(csv.DictReader(f))
    for r in rows:
        r['label'] = int(r['label'])
    if labels_from == 'auto' and not only_agreed:
        return rows
    with LABELS_LLM_CSV.open(encoding='utf-8') as f:
        llm = {r['pair_id']: int(r['llm_label']) for r in csv.DictReader(f)}
    rows = [r for r in rows if r['pair_id'] in llm and (not only_agreed or llm[r['pair_id']] == r['label'])]
    if labels_from == 'llm':
        for r in rows:
            r['label'] = llm[r['pair_id']]
    return rows


def main() -> int:
    labels_from = 'llm' if '--labels-from=llm' in sys.argv or sys.argv[-2:] == ['--labels-from', 'llm'] else 'auto'
    run(labels_from=labels_from, write=labels_from == 'auto', verbose=True)
    return 0


def run(labels_from: str = 'auto', only_agreed: bool = False, write: bool = True, verbose: bool = False) -> dict:
    labels = load_labels(labels_from, only_agreed)
    snap = json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    now = parse_dt(snap['generated_at'])
    store = MemoryStore()
    store.load_snapshot(SNAPSHOT)
    profiles = ProfileStore.load()
    bank = BankCorpus.load(ROOT / 'data' / 'bank_corpus' / 'corpus.json')

    event_cache, cov_cache = {}, {}

    def event_of(n):
        if n['id'] not in event_cache:
            e = extract_event(n, profiles.regions)
            event_cache[n['id']] = e
            cov_cache[n['id']] = bank.coverage(bank_query(e, n), as_of=str(n['published_at'])[:10])[0] \
                if e['business_relevant'] else 0.0
        return event_cache[n['id']], cov_cache[n['id']]

    pairs, skipped = [], []
    for r in labels:
        n = store.get_news(r['news_id'])
        p = profiles.get(r['company_id'])
        if n is None:
            raise SystemExit(f'{r["pair_id"]}: news not found in snapshot ({r["news_id"]})')
        if p is None:
            skipped.append(r['pair_id'])
            continue
        e, cov = event_of(n)
        rel = score(p, e, cov, n['published_at'], now=now)
        age_days = (now - parse_dt(n['published_at'])).total_seconds() / 86400
        pairs.append({
            **{k: r[k] for k in ('pair_id', 'company_id', 'news_id', 'news_title', 'label', 'split')},
            'published_at': n['published_at'],
            'score': rel['score'], 'level': rel['level'], 'confidence': rel['confidence'],
            'event_type': e['event_type'], 'event_sectors': e['sectors'], 'event_channels': e['channels'],
            'event_regions': e['regions'], 'macro_importance': e['macro_importance'], 'bank_coverage': round(cov, 3),
            'components': {c['key']: c['value'] for c in rel.get('components', [])},
            'why_short': rel['why_short'],
            # baselines
            'b_freshness': -age_days,                                   # свежее выше
            'b_macro': float(e['macro_importance']),                    # «только макрозначимость», без профиля
            'b_random': 0.0,                                            # все равны → матожидание случайного порядка
        })
    methods = {'current': 'score', 'baseline_freshness': 'b_freshness', 'baseline_macro_only': 'b_macro',
               'baseline_random': 'b_random'}
    by_company = defaultdict(list)
    for x in pairs:
        by_company[x['company_id']].append(x)

    metrics = {}
    for m, field in methods.items():
        per_company = {}
        for cid, xs in by_company.items():
            sc = [(x[field], x['label']) for x in xs]
            per_company[cid] = {'split': xs[0]['split'], 'n': len(xs),
                                'p@3_rel': round(precision_at_k(sc, 3, 1), 4),
                                'p@3_strict': round(precision_at_k(sc, 3, 2), 4),
                                'ndcg@5': round(ndcg_at_k(sc, 5), 4)}
        agg = {}
        for sp in SPLITS:
            cs = [v for v in per_company.values() if in_split(v['split'], sp)]
            agg[sp] = {k: round(sum(c[k] for c in cs) / len(cs), 4) for k in ('p@3_rel', 'p@3_strict', 'ndcg@5')} \
                if cs else {}
            agg[sp]['companies'] = len(cs)
            agg[sp]['pairs'] = sum(c['n'] for c in cs)
        metrics[m] = {'per_company': per_company, 'mean': agg}

    # «показано в ленте» = level != none (как в FeedService.feed) — бинарный взгляд на фильтр
    feed_view = {}
    for sp in SPLITS:
        xs = [x for x in pairs if in_split(x['split'], sp)]
        shown = [x for x in xs if x['level'] != 'none']
        rel = [x for x in xs if x['label'] >= 1]
        strict = [x for x in xs if x['label'] == 2]
        feed_view[sp] = {
            'shown': len(shown), 'pairs': len(xs),
            'precision_shown_rel': round(sum(1 for x in shown if x['label'] >= 1) / len(shown), 4) if shown else None,
            'recall_rel': round(sum(1 for x in rel if x['level'] != 'none') / len(rel), 4) if rel else None,
            'recall_strict': round(sum(1 for x in strict if x['level'] != 'none') / len(strict), 4) if strict else None,
            'hidden_label2': [x['pair_id'] for x in strict if x['level'] == 'none'],
            'shown_label0': [x['pair_id'] for x in shown if x['label'] == 0],
        }

    # ошибки: пары, где порядок резко расходится с разметкой внутри компании
    errors = []
    for cid, xs in by_company.items():
        ranked = sorted(xs, key=lambda x: -x['score'])
        for i, x in enumerate(ranked):
            x['rank'] = i + 1
            if x['label'] == 0 and i < 3:
                errors.append({'type': 'false_up', **_err(x)})
            if x['label'] == 2 and i >= 3:
                errors.append({'type': 'missed', **_err(x)})

    robustness = robustness_check(store, now, event_of)

    # эталонный сценарий продакта T2: решение ЦБ по ставке 23.10 — high для U_1595 (кредит+лизинг),
    # low/medium для U_8167 (без кредитов). Проверяем все сообщения о решении в снимке.
    t2 = []
    for n in store.list_news(limit=1000):
        if 'ключев' in n['title'].lower() and 'ставк' in n['title'].lower() and n['published_at'][:10] == '2026-10-23':
            e, cov = event_of(n)
            row = {'title': n['title'], 'event_type': e['event_type']}
            for cid in ('U_1595', 'U_8167'):
                p = profiles.get(cid)
                if p:
                    r = score(p, e, cov, n['published_at'], now=now)
                    row[cid] = {'score': r['score'], 'level': r['level']}
            row['ok'] = (row.get('U_1595', {}).get('level') == 'high'
                         and row.get('U_8167', {}).get('level') in ('low', 'medium'))
            t2.append(row)

    out = {'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
           'labels_files': [str(x.relative_to(ROOT)) for x in (LABELS_CSV, LABELS_FRESH_CSV) if x.is_file()],
           'ai_dir': os.environ.get('EVAL_AI_DIR') or 'ai', 'now_for_freshness': snap['generated_at'],
           'profiles_source': profiles.source.replace(str(ROOT) + '/', ''), 'profiles_version': profiles.version,
           'profiles_count': len(profiles.profiles), 'min_revenue': profiles.meta.get('min_revenue'),
           'extractor': EXTRACTOR_VERSION, 'skipped_pairs': skipped, 't2_check': t2, 'weights': WEIGHTS,
           'metrics': metrics, 'feed_view': feed_view, 'errors': errors, 'pairs': pairs,
           'robustness': robustness}
    if labels_from != 'auto' or only_agreed:
        out['labels_from'] = labels_from + (' (only agreed)' if only_agreed else '')
    if write:
        RESULTS_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    if not verbose:
        return out
    print(f'profiles: {profiles.source} ({len(profiles.profiles)} компаний, version {profiles.version}); '
          f'extractor {EXTRACTOR_VERSION}; пропущено пар: {len(skipped)} {skipped or ""}')
    print_report(metrics, feed_view, errors, robustness)
    print('\nЭталон T2 (ставка ЦБ 23.10: U_1595 → high, U_8167 → low/medium):')
    for row in t2:
        print(f'  {"OK  " if row["ok"] else "FAIL"} {row["title"][:70]:<70} U_1595 {row.get("U_1595")}  U_8167 {row.get("U_8167")}')
    print(f'\nresults -> {RESULTS_JSON.relative_to(ROOT) if write else "(не записано: другой эталон)"}')
    return out


def _err(x):
    return {k: x[k] for k in ('pair_id', 'company_id', 'news_title', 'label', 'rank', 'score', 'level',
                              'event_type', 'event_sectors', 'components', 'why_short')}


def robustness_check(store, now, event_of):
    """Неполный (U_9000008) и неоднозначный (U_9000009) синтетический профиль: score по всем новостям снимка
    не падает; фиксируем предупреждения, уверенность и топ-3."""
    try:
        from app.data_build import build_profiles
        from app.config import settings
        data = build_profiles(SYNTH_DIR, settings.min_revenue)
    except Exception as e:  # pragma: no cover
        return {'error': repr(e)}
    res = {}
    news = store.list_news(limit=1000)
    for p in data['profiles']:
        if p['company_id'] not in ('U_9000008', 'U_9000009'):
            continue
        p['channels'] = channels_for(p)
        scored = []
        for n in news:
            e, cov = event_of(n)
            r = score(p, e, cov, n['published_at'], now=now)
            scored.append((r['score'], n['title'], r))
        scored.sort(key=lambda x: -x[0])
        top = scored[0][2]
        res[p['company_id']] = {
            'profile_status': p['profile_status'], 'missing_fields': len(p['missing_fields']),
            'channels': {k: v['strength'] for k, v in p['channels'].items()},
            'scored_news': len(scored), 'shown_level_not_none': sum(1 for s in scored if s[2]['level'] != 'none'),
            'confidence_top': top['confidence'], 'warnings_top': top['profile_warnings'],
            'top3': [{'title': t, 'score': s, 'why_short': r['why_short']} for s, t, r in scored[:3]],
        }
    return res


def print_report(metrics, feed_view, errors, robustness):
    print('Оценка персонализации ленты (eval/labels.csv)')
    print('=' * 96)
    hdr = f'{"method":<32}{"split":<9}{"comp":>5}{"pairs":>6}{"P@3 (≥1)":>11}{"P@3 (=2)":>11}{"nDCG@5":>9}'
    print(hdr)
    print('-' * len(hdr))
    for m, v in metrics.items():
        for sp in SPLITS:
            a = v['mean'][sp]
            if not a.get('companies'):
                continue
            print(f'{m:<32}{sp:<9}{a["companies"]:>5}{a["pairs"]:>6}{a["p@3_rel"]:>11.3f}{a["p@3_strict"]:>11.3f}'
                  f'{a["ndcg@5"]:>9.3f}')
    print('\nПо компаниям (current vs baseline_macro_only vs baseline_freshness), nDCG@5 / P@3(≥1):')
    for cid, c in metrics['current']['per_company'].items():
        b = metrics['baseline_macro_only']['per_company'][cid]
        f = metrics['baseline_freshness']['per_company'][cid]
        print(f'  {cid:<10} {c["split"]:<8} current {c["ndcg@5"]:.3f}/{c["p@3_rel"]:.2f}   '
              f'macro {b["ndcg@5"]:.3f}/{b["p@3_rel"]:.2f}   fresh {f["ndcg@5"]:.3f}/{f["p@3_rel"]:.2f}')
    print('\nФильтр ленты (level != none считается «показано»):')
    for sp, v in feed_view.items():
        print(f'  {sp:<8} shown {v["shown"]}/{v["pairs"]}  precision(≥1) {v["precision_shown_rel"]}  '
              f'recall(≥1) {v["recall_rel"]}  recall(=2) {v["recall_strict"]}  '
              f'скрыты label=2: {v["hidden_label2"]}  показаны label=0: {v["shown_label0"]}')
    print('\nОшибки ранжирования (label=0 в топ-3 / label=2 вне топ-3):')
    for e in errors:
        comps = ' '.join(f'{k}={v:g}' for k, v in e['components'].items() if v)
        print(f'  [{e["type"]:<8}] {e["pair_id"]} {e["company_id"]:<9} rank {e["rank"]} label {e["label"]} '
              f'score {e["score"]:.3f} {e["event_type"]:<15} {e["news_title"][:60]}  | {comps}')
    print('\nУстойчивость (синтетические неполные профили):')
    for cid, r in robustness.items():
        if not isinstance(r, dict) or 'top3' not in r:
            print(f'  {cid}: {r}')
            continue
        print(f'  {cid} status={r["profile_status"]} missing={r["missing_fields"]} channels={r["channels"]} '
              f'shown={r["shown_level_not_none"]}/{r["scored_news"]} confidence={r["confidence_top"]}')
        print(f'     warnings: {r["warnings_top"]}')
        for t in r['top3']:
            print(f'     {t["score"]:.3f}  {t["title"][:80]}')


if __name__ == '__main__':
    raise SystemExit(main())
