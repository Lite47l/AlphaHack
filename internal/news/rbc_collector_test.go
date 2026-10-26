package news

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestRBCCollectorPreservesFullTextForAgent(t *testing.T) {
	parser := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/parse" {
			t.Errorf("unexpected parser request: %s %s", r.Method, r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprint(w, `[{"title":"ЦБ снизил ключевую ставку","text":"Полный текст статьи РБК для анализа агентом","date":"2026-10-25T12:00:00","url":"https://www.rbc.ru/economics/25/10/2026/article?utm_source=test"}]`)
	}))
	defer parser.Close()
	t.Setenv("RBC_PARSER_URL", parser.URL)
	items, err := NewRBCCollector().Collect(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 {
		t.Fatalf("got %d articles", len(items))
	}
	if items[0].Content != "Полный текст статьи РБК для анализа агентом" {
		t.Errorf("full article missing from AI content: %+v", items[0])
	}
	if items[0].URL != "https://www.rbc.ru/economics/25/10/2026/article" {
		t.Errorf("URL not normalized: %s", items[0].URL)
	}
}
