"""Вторая автоматическая разметка 100 пар eval моделью (LLM как независимый разметчик) и сравнение с автометками.

Запуск из корня репозитория (ключ и адрес шлюза — из окружения или .env: LLM_BASE_URL, LLM_API_KEY):

    python3 eval/llm_annotate.py annotate   # eval/labels_llm.csv (ответы кэшируются в LLM_ANNOTATE_CACHE)
    python3 eval/llm_annotate.py compare    # согласие с автометками + метрики → eval/results_llm.json

Модели передаются только наблюдаемые данные: профиль компании из CSV (ОКВЭД, регион, выручка, продукты банка,
ФТС, агрегаты платежей) и текст новости из снимка. Не передаются: автометка и её обоснование, score, level,
компоненты ранжирования, каналы чувствительности и механизмы сервиса. Рубрика — правила спорных случаев
из docs/evaluation_report.md §5. Это не ручная разметка: модель может разделять систематические ошибки.
"""
import csv
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'eval'))
import evaluate as ev  # noqa: E402  (настраивает sys.path на ai/ и DATA_DIR)

from app.profiles import ProfileStore  # noqa: E402
from app.storage import MemoryStore  # noqa: E402

LABELS_LLM_CSV = ROOT / 'eval' / 'labels_llm.csv'
RESULTS_LLM_JSON = ROOT / 'eval' / 'results_llm.json'
CACHE_DIR = Path(os.environ.get('LLM_ANNOTATE_CACHE') or ROOT / '.cache' / 'llm_annotate')
MODEL = os.environ.get('LLM_ANNOTATE_MODEL', 'qwen/qwen3.6-35b-a3b')
PROMPT_VERSION = 'annot-v1'
MAX_CALLS = 150

PRODUCTS = {'CL_PRODUCT_RKO_MARK': 'расчётный счёт (РКО)', 'CL_PRODUCT_GAR_MARK': 'банковские гарантии',
            'CL_PRODUCT_LOA_MARK': 'кредит', 'CL_PRODUCT_LEA_MARK': 'лизинг', 'CL_PRODUCT_DEP_MARK': 'депозит',
            'CL_PRODUCT_ZPP_MARK': 'зарплатный проект', 'FACTORING_MARK': 'факторинг'}

SYSTEM = """Ты — аналитик корпоративного банка. Оцени, насколько новость значима для бизнеса конкретной компании.
Используй только данные профиля и текст новости, без внешних знаний о статье и компании.

Шкала:
2 — значимо: событие напрямую меняет выручку, маржу или спрос основного вида деятельности по ОКВЭД,
    или бьёт по подтверждённому продукту компании (ключевая ставка при наличии кредита или лизинга;
    курс валют при отметке ФТС).
1 — косвенно: макро- или отраслевой фон через подтверждённый или типичный для ОКВЭД канал без прямого эффекта;
    рынок компании, но другой регион; новость о чужой компании, которая служит прецедентом для отрасли;
    механизм типичен для отрасли, но не подтверждён данными; гипотетические заявления («может», «рассматривает»).
0 — нерелевантно: механизма влияния на эту компанию в данных нет; другая товарная группа или другой подсектор;
    иностранный рынок без связи с компанией; новость о чужой компании без отраслевого сигнала; событие не о бизнесе.
Направление ВЭД (экспорт/импорт) не известно — курс оценивай по значимости, а не по знаку эффекта.

Ответ — только JSON: {"label": 0|1|2, "reason": "одно-два предложения: какой признак профиля и какой факт новости"}"""


def load_env() -> dict:
    env = {}
    path = ROOT / '.env'
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for k in ('LLM_BASE_URL', 'LLM_API_KEY'):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def _ssl_ctx():
    for ca in (os.environ.get('LLM_CA_FILE'), '/etc/ssl/cert.pem'):
        if ca and Path(ca).is_file():
            return ssl.create_default_context(cafile=ca)
    return ssl.create_default_context()


def _fmt_share(items, n=3):
    return ', '.join(f'{x["label"]} {x["share"]:.0%}' for x in (items or [])[:n] if x.get('share', 0) >= 0.01) or 'нет данных'


def profile_text(p: dict) -> str:
    o = {k: v.get('value') for k, v in p['observed'].items()}
    d = p.get('derived') or {}
    prods = [name for k, name in PRODUCTS.items() if (p.get('products') or {}).get(k) == 1]
    lines = [
        f'ОКВЭД: {o.get("MAINOKVED_CODE")} — {o.get("MAINOKVED_NAME")}',
        f'Регион регистрации: {o.get("REGION") or "не указан"}',
        f'Годовая выручка (единицы датасета): {o.get("REVENUE_COMPANY")}',
        f'Работников (ФНС): {o.get("AMOUNT_WORKERS_FNS_GRADATION") or "не указано"}',
        f'Продукты в банке: {", ".join(prods) or "нет данных о продуктах"}',
        f'Отметка ФТС (внешнеэкономическая деятельность): {"да" if o.get("FTS_FLAG") == 1 else "нет"}'
        + (f'; страны: {o.get("FTS_COUNTRY_NAME")}' if o.get('FTS_COUNTRY_NAME') else ''),
    ]
    for key, title in (('payments_out', 'Исходящие платежи'), ('payments_in', 'Входящие платежи')):
        x = d.get(key)
        if x:
            lines.append(f'{title}: контрагентов {x.get("counterparties")}; отрасли известных контрагентов — '
                         f'{_fmt_share(x.get("sectors"))}; регионы — {_fmt_share(x.get("regions"))}; '
                         f'страны ФТС контрагентов — {_fmt_share(x.get("fts_countries"))}')
    g = d.get('group') or {}
    if g.get('size'):
        lines.append(f'Группа компаний: {g["size"]} участн.')
    return '\n'.join(lines)


def news_text(n: dict) -> str:
    body = (n.get('content') or n.get('summary') or '').strip()
    return (f'Источник: {n.get("source_name")}; дата: {str(n.get("published_at"))[:10]}\n'
            f'Заголовок: {n["title"]}\nТекст: {body[:1800] or "(в снимке только заголовок)"}')


def call_llm(env: dict, messages: list[dict]) -> tuple[dict, dict]:
    base = env['LLM_BASE_URL'].rstrip('/')
    url = base if base.endswith('/chat/completions') else base + '/chat/completions'
    body = {'model': MODEL, 'messages': messages, 'temperature': 0, 'max_tokens': 300,
            'reasoning': {'enabled': False}, 'response_format': {'type': 'json_object'}}
    last = None
    for attempt in range(8):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST', headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {env["LLM_API_KEY"]}'})
        try:
            with urllib.request.urlopen(req, timeout=90, context=_ssl_ctx()) as r:
                data = json.loads(r.read().decode())
            text = data['choices'][0]['message'].get('content') or ''
            from app.llm import extract_json
            obj = extract_json(text)
            if isinstance(obj, dict) and obj.get('label') in (0, 1, 2, '0', '1', '2'):
                return {'label': int(obj['label']), 'reason': str(obj.get('reason', '')).strip()}, data.get('usage') or {}
            last = f'bad output: {text[:120]!r}'
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}'
            if e.code == 400 and ('response_format' in body or 'reasoning' in body):
                body = {k: v for k, v in body.items() if k not in ('response_format', 'reasoning')}
                continue
            if e.code in (401, 403):
                break
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError, OSError) as e:
            last = type(e).__name__
        time.sleep(min(30, 3 * (attempt + 1)))
    raise RuntimeError(f'LLM call failed: {last}')


def annotate() -> int:
    env = load_env()
    if not env.get('LLM_BASE_URL') or not env.get('LLM_API_KEY'):
        raise SystemExit('нужны LLM_BASE_URL и LLM_API_KEY (в .env или окружении)')
    labels = ev.load_labels()
    store = MemoryStore()
    store.load_snapshot(ev.SNAPSHOT)
    profiles = ProfileStore.load()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    rows, calls, usage = [], 0, Counter()
    for r in labels:
        p, n = profiles.get(r['company_id']), store.get_news(r['news_id'])
        if p is None or n is None:
            print(f'{r["pair_id"]}: пропуск (нет профиля или новости)')
            continue
        messages = [{'role': 'system', 'content': SYSTEM},
                    {'role': 'user', 'content': f'ПРОФИЛЬ КОМПАНИИ\n{profile_text(p)}\n\nНОВОСТЬ\n{news_text(n)}'}]
        key = hashlib.sha256(json.dumps([MODEL, PROMPT_VERSION, messages], ensure_ascii=False).encode()).hexdigest()
        cpath = CACHE_DIR / f'{key}.json'
        if cpath.is_file():
            res = json.loads(cpath.read_text(encoding='utf-8'))
        else:
            if calls >= MAX_CALLS:
                raise SystemExit(f'достигнут лимит {MAX_CALLS} вызовов')
            calls += 1
            res, u = call_llm(env, messages)
            usage.update({k: v for k, v in u.items() if isinstance(v, int)})
            cpath.write_text(json.dumps(res, ensure_ascii=False), encoding='utf-8')
        rows.append({'pair_id': r['pair_id'], 'company_id': r['company_id'], 'news_id': r['news_id'],
                     'llm_label': res['label'], 'llm_reason': res['reason'], 'model': MODEL,
                     'prompt_version': PROMPT_VERSION})
        print(f'{r["pair_id"]:<4} auto {r["label"]} llm {res["label"]}  {n["title"][:70]}')
    with LABELS_LLM_CSV.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f'\n{len(rows)} пар → {LABELS_LLM_CSV.relative_to(ROOT)}; новых вызовов {calls}; '
          f'токены {dict(usage) or "—"}')
    return 0


# ------------------------------------------------------------------ согласие
def kappa(a: list[int], b: list[int], weighted: bool) -> float:
    k, n = 3, len(a)
    obs = [[0] * k for _ in range(k)]
    for x, y in zip(a, b):
        obs[x][y] += 1
    ra, rb = [sum(r) for r in obs], [sum(obs[i][j] for i in range(k)) for j in range(k)]
    w = [[((i - j) ** 2 / (k - 1) ** 2) if weighted else (0 if i == j else 1) for j in range(k)] for i in range(k)]
    o = sum(w[i][j] * obs[i][j] for i in range(k) for j in range(k)) / n
    e = sum(w[i][j] * ra[i] * rb[j] for i in range(k) for j in range(k)) / n / n
    return round(1 - o / e, 4) if e else 1.0


def agreement(pairs: list[dict]) -> dict:
    a, b = [p['auto'] for p in pairs], [p['llm'] for p in pairs]
    cm = [[0] * 3 for _ in range(3)]
    for x, y in zip(a, b):
        cm[x][y] += 1
    return {'pairs': len(pairs), 'exact': round(sum(x == y for x, y in zip(a, b)) / len(a), 4),
            'within_1': round(sum(abs(x - y) <= 1 for x, y in zip(a, b)) / len(a), 4),
            'kappa': kappa(a, b, False), 'kappa_quadratic': kappa(a, b, True),
            'confusion_auto_rows_llm_cols': cm,
            'auto_dist': dict(sorted(Counter(a).items())), 'llm_dist': dict(sorted(Counter(b).items()))}


def compare() -> int:
    auto = {r['pair_id']: r for r in ev.load_labels()}
    with LABELS_LLM_CSV.open(encoding='utf-8') as f:
        llm = {r['pair_id']: int(r['llm_label']) for r in csv.DictReader(f)}
    pairs = [{'pair_id': k, 'split': r['split'], 'auto': r['label'], 'llm': llm[k], 'company_id': r['company_id'],
              'news_title': r['news_title']} for k, r in auto.items() if k in llm]
    agree = {'all_100': agreement(pairs)}
    for sp in ('dev', 'holdout', 'fresh'):
        xs = [p for p in pairs if p['split'] == sp]
        if xs:
            agree[sp] = agreement(xs)
    far = [p for p in pairs if abs(p['auto'] - p['llm']) == 2]

    variants = {'auto': ('auto', None), 'llm': ('llm', None), 'agreed_only': ('auto', 'agree')}
    metrics = {}
    for name, (src, filt) in variants.items():
        out = ev.run(labels_from=src, only_agreed=(filt == 'agree'), write=False)
        metrics[name] = {m: v['mean'] for m, v in out['metrics'].items()}
        metrics[name]['_pairs'] = len(out['pairs'])
    res = {'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'), 'model': MODEL,
           'prompt_version': PROMPT_VERSION, 'agreement': agree,
           'disagree_by_2': [{k: p[k] for k in ('pair_id', 'company_id', 'news_title', 'auto', 'llm')} for p in far],
           'metrics_by_reference': metrics}
    RESULTS_LLM_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')

    a = agree['all_100']
    print(f'Согласие LLM ({MODEL}) с автометками: {a["pairs"]} пар, совпадение {a["exact"]:.0%}, '
          f'±1 {a["within_1"]:.0%}, kappa {a["kappa"]}, квадратичная kappa {a["kappa_quadratic"]}')
    for sp in ('dev', 'holdout', 'fresh'):
        if sp in agree:
            x = agree[sp]
            print(f'  {sp:<8} {x["pairs"]:>3} пар  совпадение {x["exact"]:.0%}  kappa {x["kappa"]}  '
                  f'квадр. {x["kappa_quadratic"]}')
    print('Матрица (строки — автометка 0/1/2, столбцы — LLM):', a['confusion_auto_rows_llm_cols'])
    print(f'Расхождение на 2 ступени: {len(far)}')
    for p in far:
        print(f'  {p["pair_id"]} {p["company_id"]} auto {p["auto"]} llm {p["llm"]}  {p["news_title"][:70]}')
    print('\nМетрики (среднее по компаниям) при разных эталонах:')
    print(f'{"эталон":<13}{"метод":<22}{"split":<9}{"pairs":>6}{"P@3≥1":>8}{"P@3=2":>8}{"nDCG@5":>8}')
    for name, ms in metrics.items():
        for m in ('current', 'baseline_macro_only', 'baseline_freshness', 'baseline_random'):
            for sp in ('dev', 'holdout', 'fresh'):
                v = ms[m].get(sp) or {}
                if v.get('companies'):
                    print(f'{name:<13}{m:<22}{sp:<9}{v["pairs"]:>6}{v["p@3_rel"]:>8.3f}{v["p@3_strict"]:>8.3f}'
                          f'{v["ndcg@5"]:>8.3f}')
    print(f'\nresults -> {RESULTS_LLM_JSON.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'annotate':
        raise SystemExit(annotate())
    if cmd == 'compare':
        raise SystemExit(compare())
    raise SystemExit(__doc__)
