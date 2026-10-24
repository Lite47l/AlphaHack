# API-контракт v1 (T02)

Версия контракта: **1.0** (2026-10-24). Изменения — только через PR с обновлением этого файла.

## Топология

```
browser ──► web (nginx :3000, SPA + прокси /api) ──► backend (Go :8080, шлюз) ──► ai (FastAPI :8000)
                                                         │                           │
                                                         └──────── PostgreSQL ◄──────┘
```

- Все запросы браузера идут на `/api/v1/...` того же origin (nginx проксирует на `backend:8080`).
- Go-шлюз сам обслуживает: `/health`, `/ready`, `/api/v1/news*`, `/api/v1/knowledge`.
- Go-шлюз **проксирует в AI** (`AI_URL`, по умолчанию `http://ai:8000`) без изменения пути все запросы с префиксами:
  `/api/v1/companies`, `/api/v1/insights`, `/api/v1/relevance`, `/api/v1/bank`, `/api/v1/system`, `/api/v1/metrics`.
- Шлюз передаёт/создаёт `X-Request-Id` и пробрасывает заголовки `X-Client-Id`, `X-User-Role`.
- Формат ошибок везде: `{"error": "текст"}` + HTTP-код. Даты — ISO 8601 с таймзоной. ID новостей — UUID (из таблицы `news`), ID компаний — `SYNTHETIC_U` из датасета (например `U_57706`).

### Заголовки контекста пользователя

| Заголовок | Значение | Назначение |
|---|---|---|
| `X-Client-Id` | `company_id` выбранного клиента | Граница доступа: инсайт/чат компании A недоступен в контексте компании B → 403 |
| `X-User-Role` | `cfo` (по умолчанию), `ceo`, `treasurer`, `accountant` | Роль пользователя (влияет на формулировки действий) |

## Новости (Go)

### `GET /api/v1/news?limit=20&offset=0`
`{"items":[News], "limit":20, "offset":0}`

```json
News = {
  "id": "7d1c...-uuid", "title": "Банк России сохранил ключевую ставку на уровне 14,00%",
  "summary": "Очищенный текст анонса/описания (без HTML)", "content": "Полный текст, если есть, иначе \"\"",
  "url": "https://www.cbr.ru/press/pr/?file=...", "source_name": "Банк России",
  "published_at": "2026-10-23T13:30:00+03:00", "fetched_at": "2026-10-24T18:00:00Z",
  "origin": "collector | snapshot | user"
}
```

### `GET /api/v1/news/{id}` → `News` | 404

### `POST /api/v1/news` — пользовательская новость (проверка на ранее не показанных новостях)
Тело: `{"title": "...", "text": "...", "url": "https://..."}`. Обязательно `text` **или** `url`.
Если передан только `url`, шлюз сам загружает страницу (таймаут 10 с, только http/https, запрет приватных/loopback адресов, ≤2 МБ) и извлекает `<title>`, `og:description` и текст абзацев.
Ответ `201` → `News` с `origin:"user"`, `source_name:"Добавлено пользователем"` (или домен URL). Повтор того же URL → `200` с существующей записью.

### `POST /api/v1/news/import` → `{"results":[{"source","fetched","inserted","error?"}]}`
Также импорт выполняется фоново по таймеру `NEWS_IMPORT_INTERVAL` (по умолчанию 30m) и один раз при старте.

### `GET /api/v1/knowledge` — реестр документов банка (`{"items":[{id,title,institution,document_url,published_at}]}`)

## Компании (AI)

### `GET /api/v1/companies?query=&limit=50&offset=0`
```json
{"items":[CompanySummary], "total":115, "limit":50, "offset":0, "data_source":"real | generated | synthetic"}
CompanySummary = {
  "company_id":"U_102920", "display_name":"Компания U_102920",
  "subtitle":"Торговля оптовая прочими пищевыми продуктами, включая рыбу...",
  "okved_code":"46.38", "region":"Санкт-Петербург", "revenue":54767620000, "cl_type":"CLIENT",
  "sectors":[{"key":"wholesale","label":"Оптовая торговля"}], "profile_status":"matched | ambiguous",
  "completeness":"complete | incomplete", "key_missing":["REGION"],
  "top_channels":["Стоимость заёмного финансирования","Внешнеэкономическая деятельность и курс"]
}
```

### `GET /api/v1/companies/{company_id}` → `CompanyProfile` | 404
```json
{
  "summary": CompanySummary,
  "observed": {"MAINOKVED_CODE":{"value":"46.38","title":"Код основного ОКВЭД","source":"df_Uid_data_hack.csv:MAINOKVED_CODE"}, "...":{}},
  "products": {"CL_PRODUCT_LOA_MARK":1, "CL_PRODUCT_DEP_MARK":0, "...":null},
  "missing_fields": ["AMOUNT_WORKERS_SPARK_GRADATION"],
  "channels": [{"key":"cost_of_debt","label":"Стоимость заёмного финансирования","strength":0.95,
                "basis":["P:CL_PRODUCT_LOA_MARK","P:CL_PRODUCT_LEA_MARK"],"notes":["В банке есть кредитные продукты, лизинг"]}],
  "derived": {
    "revenue_rank": {"okved_class":"46.38","rank":1,"of":513,"note":"... не доля рынка"},
    "group": {"group_id":"group_133117_sb","size":3,"revenue_sum":84277808102,"member_sectors":[...],"note":"..."},
    "payments_out": {"amount":3405827000,"count":1281,"counterparties":52,"top5_share":0.77,"max_share":0.33,
                     "unknown_profile_share":0.92,"sectors":[{"key":"transport","label":"...","share":0.01}],
                     "regions":[{"key":"Москва","label":"Москва","share":0.1}],"fts_countries":[...],
                     "top":[{"company_id":"U_32499","amt":1129128000,"cnt":266,"share":0.33,"okved_code":null,"okved_name":null,"region":null,"in_profile":false}]},
    "payments_in": {"...": "так же"},
    "persons": {"linked_persons":0,"regions":[],"companies_via_shared_persons":[],"note":"..."}
  },
  "data_notes": ["Период и единицы платежей в данных не указаны...", "..."]
}
```

### `GET /api/v1/companies/{company_id}/feed?limit=20&days=45&include_filtered=false`
Персонализированная лента (ранжирование без LLM, быстро).
```json
{
  "company_id":"U_102920", "generated_at":"2026-10-24T18:00:00Z",
  "items":[FeedItem], "filtered":[FeedItem],
  "stats":{"news_considered":180,"shown":20,"filtered_non_business":95,"filtered_low_relevance":40}
}
FeedItem = {
  "news_id":"uuid", "title":"...", "summary":"...", "url":"...", "source_name":"РБК", "published_at":"...",
  "event": {"event_type":"key_rate","event_label":"Ключевая ставка и ДКП","sectors":["finance"],
            "sector_labels":["Финансы и холдинги"],"direction":"hold","regions":[]},
  "relevance": {
    "score":0.74, "level":"high | medium | low | none",
    "components":[{"key":"channel","label":"Каналы влияния на компанию","value":0.9,"weight":0.3,"contribution":0.27,
                   "reason":"Стоимость заёмного финансирования: в банке есть кредитные продукты, лизинг",
                   "evidence":["P:CL_PRODUCT_LOA_MARK"]}],
    "reasons":["Есть кредитные продукты — ставка влияет на стоимость долга", "..."],
    "why_short":"Есть кредит и лизинг: стоимость долга останется высокой",
    "confidence":"high | medium | low", "profile_warnings":["Неполный профиль: нет региона"]
  },
  "duplicates":[{"news_id":"uuid","title":"...","source_name":"Ведомости","url":"..."}],
  "bank_coverage":{"found":true,"docs":[{"doc_id":"alfa-key-rate-2026-09-11","title":"Ключевая ставка ЦБ РФ..."}]},
  "filtered_reason": null
}
```
`filtered_reason` (только в `filtered`): `"non_business"` | `"low_relevance"`.

### `GET /api/v1/relevance?news_id=<uuid>&company_ids=U_1,U_2`
Одна новость для нескольких компаний (демо «разная значимость»):
`{"news": News, "event": Event, "results":[{"company_id","display_name","subtitle","relevance": Relevance}]}`

## Инсайты (AI, агент)

### `POST /api/v1/insights`
Тело: `{"company_id":"U_102920","news_id":"uuid","role":"cfo","force":false}`; заголовок `X-Client-Id` должен совпадать с `company_id` (иначе 403).
Ответ `202`: `{"insight_id":"uuid","status":"queued | processing | completed","trace_id":"uuid","cached":false}`.
Повторный запрос с тем же ключом (компания, новость, роль, версии данных/промпта) возвращает готовый инсайт (`cached:true`), если не передан `force:true`.

### `GET /api/v1/insights/{insight_id}` (заголовок `X-Client-Id` обязателен для чужого контекста → 403)
```json
{
  "insight_id":"uuid", "company_id":"U_102920", "news_id":"uuid", "role":"cfo",
  "status":"queued | processing | completed | failed", "error":null,
  "trace_id":"uuid", "created_at":"...", "updated_at":"...",
  "progress":[{"step":3,"kind":"tool","name":"search_bank_analytics","status":"ok","title":"Поиск позиции банка"}],
  "result": Insight | null
}
Insight = {
  "mode":"llm | rules",                      // rules — LLM недоступна, вывод собран правилами (явно показывать в UI)
  "models":{"planner":"GLM-5.3-Flash","writer":"Qwen3.6-35B-A3B"}, "prompt_version":"insight-v1",
  "headline":"Ставка 14% сохраняет дорогой долг для компании с кредитом и лизингом",
  "relevance": Relevance,
  "event": Event,
  "what_happened":[Statement],                 // факты из новости, kind="fact"
  "why_it_matters":[Statement],                // связь с компанией, kind="client_link", ссылки на P:/G:
  "risks":[Statement], "opportunities":[Statement],   // kind="ai_conclusion" или "bank_view"
  "bank_view":{"status":"found | not_found | outdated", "statements":[BankStatement], "note":"..."},
  "ai_conclusions":[Statement],                // выводы модели/правил — визуально отдельно от позиции банка
  "actions":[Statement],                       // kind="action | question | scenario"
  "bank_offer": {"text":"...","product":"...","source_ids":["P:..."]} | null,   // нативное предложение банка, помечается
  "related_news":[{"news_id","title","source_name","url","published_at"}],
  "limitations":["Период платежей в данных не указан", "..."],
  "confidence":"high | medium | low",
  "validation":{"passed":true,"issues":[{"code":"unsupported_number","severity":"blocking | warning","message":"...","path":"risks[1]"}],"repairs":1},
  "sources":{ "<source_id>": Source }
}
Statement = {"text":"...", "source_ids":["N:uuid","B:chunk_id","P:FIELD","G:path"], "kind":"fact | client_link | ai_conclusion | bank_view | action | question | scenario", "confidence":"high|medium|low"}
BankStatement = {"text":"пересказ позиции банка","quote":"дословная цитата из фрагмента","source_ids":["B:chunk_id"],
                 "doc_title":"...","page":1,"published_at":"2026-09-11","warning":""}
Source =
  {"type":"news","id":"N:uuid","title":"...","url":"...","source_name":"...","published_at":"..."}
| {"type":"bank","id":"B:chunk_id","doc_id":"...","doc_title":"...","page":1,"url":"https://drive.google.com/...","published_at":"...","text":"фрагмент"}
| {"type":"profile","id":"P:FIELD","title":"Кредитные продукты","value":1,"origin":"df_Uid_data_hack.csv:CL_PRODUCT_LOA_MARK"}
| {"type":"graph","id":"G:payments_out.sectors","title":"...","value":<json>,"origin":"..."}
```
Префиксы source_id: `N:` новость, `B:` фрагмент аналитики банка, `P:` поле профиля, `G:` агрегат графа платежей/группы/физлиц.

### `GET /api/v1/insights/{insight_id}/trace` (трассировка по trace_id)
```json
{"trace_id":"uuid","insight_id":"uuid","kind":"insight | chat",
 "steps":[{"step":1,"kind":"plan | tool | check | llm | validate | repair | final","name":"get_company_profile",
           "title":"Профиль компании","status":"ok | empty | error | skipped","started_at":"...","duration_ms":12,
           "input":{"company_id":"U_1"},"output_summary":"...","source_ids":["P:..."],"notes":["..."],
           "tokens":{"prompt":0,"completion":0},"model":null}],
 "summary":{"mode":"llm | rules","tool_calls":7,"llm_calls":3,"tokens":{"prompt":5200,"completion":900},"duration_ms":8400,
            "plan":["get_company_profile","..."],"adaptations":["bank_search_retry: запрос переформулирован"]}}
```

### `POST /api/v1/insights/{insight_id}/chat`  тело `{"question":"Как это повлияет на обслуживание кредитов?"}`
```json
{"message":{"id":12,"role":"assistant","content":"...","statements":[Statement],"sources":{...},
            "trace_id":"uuid","mode":"llm | rules","created_at":"..."},
 "history":[{"id":11,"role":"user","content":"...","created_at":"..."}, "..."]}
```
`GET /api/v1/insights/{insight_id}/chat` → `{"messages":[...]}`. Вопрос относится к открытому инсайту; чат другой компании → 403.

### `POST /api/v1/insights/{insight_id}/feedback` `{"rating":1 | -1, "reason":"..."}` → `{"ok":true}`

## Справочное (AI)

- `GET /api/v1/bank/documents` → `{"items":[{"doc_id","title","published_at","kind","topics","pages","url","date_note"}], "corpus_version":"..."}`
- `GET /api/v1/bank/search?q=ключевая ставка&k=5` → `{"items":[BankHit]}`
- `GET /api/v1/system/status` → `{"data_source":"real|synthetic","profiles":115,"profiles_version":"...","corpus_version":"...","news_in_db":180,"llm":{"llm_enabled":false,...},"mode":"llm|rules"}`
- `GET /api/v1/metrics/summary` → мониторинг качества: число инсайтов, доля прошедших валидацию, доля найденной позиции банка, средняя задержка, токены за сутки, оценки пользователей.

## Снимок новостей `data/news_snapshot.json`

Контрольная выгрузка реальных публикаций для воспроизводимого запуска без сети (загружается Go при пустой таблице `news`):
```json
{"generated_at":"2026-10-24T19:00:00+03:00","items":[
  {"title":"...","summary":"очищенный текст","url":"https://...","source_name":"Банк России","published_at":"2026-10-23T13:30:00+03:00"}]}
```
