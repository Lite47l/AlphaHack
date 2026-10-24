#!/usr/bin/env bash
# Smoke-тест поднятого стека (docker compose up --build): сквозной сценарий жюри через шлюз.
#   ./scripts/smoke_test.sh [base_url]     (по умолчанию http://localhost:3000 — через nginx фронтенда)
set -euo pipefail
BASE="${1:-http://localhost:3000}"
API="$BASE/api/v1"
C1="${SMOKE_COMPANY:-U_1595}"
C2="${SMOKE_OTHER_COMPANY:-U_8167}"
pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; exit 1; }
json() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }

echo "Smoke-тест: $BASE"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/")" = 200 ] && pass "UI отдаётся" || fail "UI недоступен"
curl -sf "$BASE/api/v1/system/status" >/dev/null || curl -sf "${BASE%:*}:8080/ready" >/dev/null || fail "API недоступен"
MODE=$(curl -sf "$API/system/status" | json "d['mode']+' / '+d['data_source']+' / профилей '+str(d['profiles'])")
pass "AI-сервис: $MODE"
N=$(curl -sf "$API/news?limit=5" | json "len(d['items'])"); [ "$N" -gt 0 ] && pass "новости в БД" || fail "нет новостей"
FEED=$(curl -sf "$API/companies/$C1/feed?limit=5&include_filtered=true")
echo "$FEED" | json "len(d['items'])" | grep -qv '^0$' && pass "персональная лента $C1" || fail "пустая лента"
NID=$(echo "$FEED" | json "d['items'][0]['news_id']")
REL=$(curl -sf "$API/relevance?news_id=$NID&company_ids=$C1,$C2" | json "' vs '.join(f\"{r['company_id']}={r['relevance']['score']}\" for r in d['results'])")
pass "одна новость — разная значимость: $REL"
CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/insights" -H 'Content-Type: application/json' -H "X-Client-Id: $C2" -d "{\"company_id\":\"$C1\",\"news_id\":\"$NID\"}")
[ "$CODE" = 403 ] && pass "чужой контекст клиента → 403" || fail "ожидали 403, получили $CODE"
IID=$(curl -sf -X POST "$API/insights" -H 'Content-Type: application/json' -H "X-Client-Id: $C1" -d "{\"company_id\":\"$C1\",\"news_id\":\"$NID\"}" | json "d['insight_id']")
for _ in $(seq 1 120); do
  ST=$(curl -sf "$API/insights/$IID" -H "X-Client-Id: $C1" | json "d['status']")
  [ "$ST" = completed ] || [ "$ST" = failed ] && break
  sleep 2
done
[ "$ST" = completed ] || fail "инсайт: $ST"
curl -sf "$API/insights/$IID" -H "X-Client-Id: $C1" | json "'режим '+d['result']['mode']+', валидация '+str(d['result']['validation']['passed'])+', позиция банка '+d['result']['bank_view']['status']+', источников '+str(len(d['result']['sources']))" | sed 's/^/  ✓ инсайт: /'
STEPS=$(curl -sf "$API/insights/$IID/trace" -H "X-Client-Id: $C1" | json "len(d['steps'])"); [ "$STEPS" -gt 5 ] && pass "трассировка: $STEPS шагов" || fail "нет трассировки"
ANS=$(curl -sf -X POST "$API/insights/$IID/chat" -H 'Content-Type: application/json' -H "X-Client-Id: $C1" -d '{"question":"На чём основан вывод?"}' | json "len(d['message']['content'])")
[ "$ANS" -gt 0 ] && pass "уточняющий вопрос" || fail "пустой ответ чата"
curl -sf "$API/metrics/summary" | json "'мониторинг: инсайтов '+str(d['insights_total'])+', доля прошедших валидацию '+str(d['validation_pass_rate'])" | sed 's/^/  ✓ /'
echo "Готово."
