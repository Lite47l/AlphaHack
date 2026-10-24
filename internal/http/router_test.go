package http

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"
)

type seenRequest struct {
	Method, Path, RawQuery, Body       string
	RequestID, ClientID, Role, Forward string
}

func newTestRouter(t *testing.T, aiURL string, perMinute int) http.Handler {
	t.Helper()
	u, err := url.Parse(aiURL)
	if err != nil {
		t.Fatal(err)
	}
	logger := slog.New(slog.NewJSONHandler(io.Discard, nil))
	return NewRouter(nil, logger, Options{AIURL: u, RateLimitPerMinute: perMinute})
}

func TestProxyRoutesToAI(t *testing.T) {
	var mu sync.Mutex
	var seen []seenRequest
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		mu.Lock()
		seen = append(seen, seenRequest{
			Method: r.Method, Path: r.URL.Path, RawQuery: r.URL.RawQuery, Body: string(body),
			RequestID: r.Header.Get("X-Request-Id"), ClientID: r.Header.Get("X-Client-Id"),
			Role: r.Header.Get("X-User-Role"), Forward: r.Header.Get("X-Forwarded-For"),
		})
		mu.Unlock()
		w.Header().Set("X-Request-Id", "upstream-should-be-dropped")
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusAccepted)
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer upstream.Close()
	h := newTestRouter(t, upstream.URL, 100)

	cases := []struct{ method, target, body string }{
		{http.MethodGet, "/api/v1/companies?query=%D0%BE%D0%BF%D1%82&limit=5", ""},
		{http.MethodGet, "/api/v1/companies/U_102920/feed?limit=20&days=45", ""},
		{http.MethodPost, "/api/v1/insights", `{"company_id":"U_1","news_id":"n"}`},
		{http.MethodGet, "/api/v1/insights/abc/trace", ""},
		{http.MethodPost, "/api/v1/insights/abc/chat", `{"question":"?"}`},
		{http.MethodGet, "/api/v1/relevance?news_id=x&company_ids=U_1,U_2", ""},
		{http.MethodGet, "/api/v1/bank/search?q=%D1%81%D1%82%D0%B0%D0%B2%D0%BA%D0%B0&k=5", ""},
		{http.MethodGet, "/api/v1/system/status", ""},
		{http.MethodGet, "/api/v1/metrics/summary", ""},
	}
	for i, c := range cases {
		var body io.Reader
		if c.body != "" {
			body = strings.NewReader(c.body)
		}
		req := httptest.NewRequest(c.method, c.target, body)
		req.Header.Set("X-Client-Id", "U_1")
		req.Header.Set("X-User-Role", "cfo")
		if i == 0 {
			req.Header.Set("X-Request-Id", "req-123")
		}
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)

		if rec.Code != http.StatusAccepted {
			t.Fatalf("%s %s: status %d body %s", c.method, c.target, rec.Code, rec.Body.String())
		}
		if got := rec.Header().Values("X-Request-Id"); len(got) != 1 {
			t.Errorf("%s: X-Request-Id values = %v", c.target, got)
		}
		mu.Lock()
		s := seen[len(seen)-1]
		mu.Unlock()
		wantURL, _ := url.Parse(c.target)
		if s.Method != c.method || s.Path != wantURL.Path || s.RawQuery != wantURL.RawQuery || s.Body != c.body {
			t.Errorf("%s: upstream saw %+v", c.target, s)
		}
		if s.ClientID != "U_1" || s.Role != "cfo" || s.RequestID == "" || s.RequestID != rec.Header().Get("X-Request-Id") {
			t.Errorf("%s: headers not forwarded: %+v (resp id %q)", c.target, s, rec.Header().Get("X-Request-Id"))
		}
		if i == 0 && s.RequestID != "req-123" {
			t.Errorf("incoming X-Request-Id not preserved: %q", s.RequestID)
		}
	}
}

func TestGatewayDoesNotProxyOwnRoutes(t *testing.T) {
	hit := false
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { hit = true }))
	defer upstream.Close()
	h := newTestRouter(t, upstream.URL, 100)

	for _, target := range []string{"/health", "/api/v1/unknown", "/api/v1/companiesX"} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, target, nil))
		if target == "/health" && rec.Code != http.StatusOK {
			t.Errorf("/health status %d", rec.Code)
		}
		if target != "/health" && rec.Code != http.StatusNotFound {
			t.Errorf("%s status %d, want 404", target, rec.Code)
		}
	}
	if hit {
		t.Error("gateway routes must not reach AI")
	}
}

func TestProxyAIUnavailable(t *testing.T) {
	upstream := httptest.NewServer(http.NotFoundHandler())
	addr := upstream.URL
	upstream.Close() // порт закрыт — соединение будет отклонено

	h := newTestRouter(t, addr, 100)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/companies", nil))
	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status %d, want 502", rec.Code)
	}
	var body map[string]string
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil || body["error"] != "AI-сервис недоступен" {
		t.Fatalf("body %q", rec.Body.String())
	}
}

func TestRateLimitOnInsightsAndChat(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusAccepted)
	}))
	defer upstream.Close()
	h := newTestRouter(t, upstream.URL, 3)

	do := func(method, target, ip string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, target, strings.NewReader(`{}`))
		req.RemoteAddr = ip + ":5555"
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		return rec
	}

	for i := 0; i < 3; i++ {
		if rec := do(http.MethodPost, "/api/v1/insights", "203.0.113.7"); rec.Code != http.StatusAccepted {
			t.Fatalf("request %d: status %d", i, rec.Code)
		}
	}
	rec := do(http.MethodPost, "/api/v1/insights", "203.0.113.7")
	if rec.Code != http.StatusTooManyRequests || rec.Header().Get("Retry-After") == "" {
		t.Fatalf("4th request: status %d", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), `"error"`) {
		t.Fatalf("429 body is not JSON error: %s", rec.Body.String())
	}
	// Другой IP и GET-запросы не ограничиваются.
	if rec := do(http.MethodPost, "/api/v1/insights", "198.51.100.1"); rec.Code != http.StatusAccepted {
		t.Fatalf("other ip: status %d", rec.Code)
	}
	for i := 0; i < 5; i++ {
		if rec := do(http.MethodGet, "/api/v1/insights/x", "203.0.113.7"); rec.Code != http.StatusAccepted {
			t.Fatalf("GET must not be limited: %d", rec.Code)
		}
	}
	// Чат ограничивается отдельно.
	for i := 0; i < 3; i++ {
		do(http.MethodPost, "/api/v1/insights/x/chat", "203.0.113.7")
	}
	if rec := do(http.MethodPost, "/api/v1/insights/x/chat", "203.0.113.7"); rec.Code != http.StatusTooManyRequests {
		t.Fatalf("chat: status %d, want 429", rec.Code)
	}
	// POST /api/v1/news тоже под лимитом: пустое тело → 400, после исчерпания лимита → 429.
	for i := 0; i < 3; i++ {
		if rec := do(http.MethodPost, "/api/v1/news", "192.0.2.10"); rec.Code != http.StatusBadRequest {
			t.Fatalf("news %d: status %d body %s", i, rec.Code, rec.Body.String())
		}
	}
	if rec := do(http.MethodPost, "/api/v1/news", "192.0.2.10"); rec.Code != http.StatusTooManyRequests {
		t.Fatalf("news: status %d, want 429", rec.Code)
	}
}

func TestRateLimiterRefill(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	l := newRateLimiter(20)
	l.now = func() time.Time { return now }
	for i := 0; i < 20; i++ {
		if ok, _ := l.allow("a"); !ok {
			t.Fatalf("request %d denied", i)
		}
	}
	ok, wait := l.allow("a")
	if ok || wait <= 0 || wait > 3*time.Second {
		t.Fatalf("21st: ok=%v wait=%v", ok, wait)
	}
	now = now.Add(3 * time.Second) // 20/мин = 1 токен за 3 с
	if ok, _ := l.allow("a"); !ok {
		t.Fatal("token must refill after 3s")
	}
	if ok, _ := l.allow("a"); ok {
		t.Fatal("only one token refilled")
	}
}

func TestClientIP(t *testing.T) {
	cases := []struct{ remote, xri, xff, want string }{
		{"203.0.113.5:1000", "1.2.3.4", "5.6.7.8", "203.0.113.5"}, // публичный собеседник: заголовкам не верим
		{"172.18.0.5:1000", "1.2.3.4", "", "1.2.3.4"},             // nginx в docker-сети
		{"172.18.0.5:1000", "", "9.9.9.9, 1.2.3.4", "1.2.3.4"},
		{"127.0.0.1:1000", "", "", "127.0.0.1"},
	}
	for _, c := range cases {
		r := httptest.NewRequest(http.MethodGet, "/", nil)
		r.RemoteAddr = c.remote
		if c.xri != "" {
			r.Header.Set("X-Real-IP", c.xri)
		}
		if c.xff != "" {
			r.Header.Set("X-Forwarded-For", c.xff)
		}
		if got := clientIP(r); got != c.want {
			t.Errorf("clientIP(%+v) = %q, want %q", c, got, c.want)
		}
	}
}
