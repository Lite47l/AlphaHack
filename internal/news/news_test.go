package news

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"os"
	"strings"
	"testing"
	"time"
)

func TestNormalizeURL(t *testing.T) {
	cases := []struct{ in, want string }{
		{"", ""},
		{"not a url", ""},
		{"  HTTPS://WWW.Example.COM/News/1/  ", "https://www.example.com/News/1"},
		{"https://example.com/a?utm_source=rss&utm_medium=x&id=5#top", "https://example.com/a?id=5"},
		{"https://example.com/a?utm-campaign=1&fbclid=2&gclid=3&yclid=4", "https://example.com/a"},
		{"https://example.com/?b=2&a=1", "https://example.com/?a=1&b=2"},
		{"https://example.com", "https://example.com/"},
		{"https://www.cbr.ru/press/PR/?file=23102026_133000key.htm", "https://www.cbr.ru/press/PR?file=23102026_133000key.htm"},
	}
	for _, c := range cases {
		if got := NormalizeURL(c.in); got != c.want {
			t.Errorf("NormalizeURL(%q) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestParseRSSFixture(t *testing.T) {
	data, err := os.ReadFile("testdata/feed.xml")
	if err != nil {
		t.Fatal(err)
	}
	items, err := ParseRSS(data, "Тест", 100)
	if err != nil {
		t.Fatalf("ParseRSS: %v", err)
	}
	if len(items) != 4 {
		for _, it := range items {
			t.Logf("%q %q", it.Title, it.URL)
		}
		t.Fatalf("got %d items, want 4 (no-link item skipped, duplicate URL merged)", len(items))
	}

	cbr := items[0]
	if cbr.URL != "https://www.cbr.ru/press/PR?file=23102026_133000key.htm" {
		t.Errorf("cbr url = %q", cbr.URL)
	}
	wantSummary := "Совет директоров Банка России 23 октября 2026 года принял решение сохранить ключевую ставку на уровне 14,00% годовых.\nИнфляция 5–6%."
	if cbr.Summary != wantSummary {
		t.Errorf("cbr summary = %q\nwant %q", cbr.Summary, wantSummary)
	}
	if strings.ContainsAny(cbr.Summary, "<>") || strings.Contains(cbr.Summary, "alert") {
		t.Errorf("summary contains HTML/script: %q", cbr.Summary)
	}
	wantTime := time.Date(2026, 10, 23, 10, 30, 0, 0, time.UTC)
	if !cbr.PublishedAt.Equal(wantTime) {
		t.Errorf("cbr published_at = %v, want %v", cbr.PublishedAt, wantTime)
	}
	if cbr.SourceName != "Тест" || cbr.Origin != OriginCollector || cbr.Content != "" {
		t.Errorf("cbr meta = %+v", cbr)
	}

	rbc := items[1]
	if rbc.Title != "Компании нарастили экспорт" {
		t.Errorf("rbc title = %q (namespaced title must not override)", rbc.Title)
	}
	if rbc.Summary != "Краткий анонс новости" {
		t.Errorf("rbc summary = %q", rbc.Summary)
	}
	if rbc.Content != "Первый абзац полного текста.\nВторой — абзац." {
		t.Errorf("rbc content = %q", rbc.Content)
	}

	yx := items[2]
	if yx.URL != "https://example.com/news/1" || yx.Summary != "Полный текст из Яндекс-формата." || yx.Content != "" {
		t.Errorf("yandex item = %+v", yx)
	}
	if !yx.PublishedAt.Equal(time.Date(2026, 10, 5, 9, 0, 0, 0, time.UTC)) {
		t.Errorf("yandex published_at = %v", yx.PublishedAt)
	}

	enc := items[3]
	if enc.URL != "https://example.com/news/2" || enc.Summary != "Анонс" || enc.Content != "Абзац один.\nАбзац два." {
		t.Errorf("content:encoded item = %+v", enc)
	}
}

func TestParseRSSMaxItemsAndGarbage(t *testing.T) {
	data, _ := os.ReadFile("testdata/feed.xml")
	items, err := ParseRSS(data, "x", 2)
	if err != nil || len(items) != 2 {
		t.Fatalf("maxItems: got %d items, err %v", len(items), err)
	}
	if items, err := ParseRSS([]byte("<html><body>not a feed</body></html>"), "x", 10); err != nil || len(items) != 0 {
		t.Fatalf("garbage: got %d items, err %v", len(items), err)
	}
}

func TestParseRSSWindows1251(t *testing.T) {
	// «Привет» в windows-1251.
	title := []byte{0xCF, 0xF0, 0xE8, 0xE2, 0xE5, 0xF2}
	doc := append([]byte(`<?xml version="1.0" encoding="windows-1251"?><rss><channel><item><title>`), title...)
	doc = append(doc, []byte(`</title><link>https://example.com/x</link></item></channel></rss>`)...)
	items, err := ParseRSS(doc, "x", 10)
	if err != nil || len(items) != 1 || items[0].Title != "Привет" {
		t.Fatalf("cp1251: %+v, err %v", items, err)
	}
}

func TestParseFeedDate(t *testing.T) {
	msk := time.FixedZone("", 3*3600)
	want := time.Date(2026, 10, 23, 13, 30, 0, 0, msk)
	for _, s := range []string{
		"Fri, 23 Oct 2026 13:30:00 +0300",
		"Fri, 23 Oct 2026 13:30:00 MSK",
		"Fri, 23 Oct 2026 10:30:00 GMT",
		"23 Oct 2026 13:30:00 +0300",
		"2026-10-23T13:30:00+03:00",
		"2026-10-23T10:30:00Z",
		"  Fri,  23 Oct 2026   13:30:00 +0300 ",
	} {
		if got := ParseFeedDate(s); !got.Equal(want) {
			t.Errorf("ParseFeedDate(%q) = %v, want %v", s, got, want)
		}
	}
	if !ParseFeedDate("вчера").IsZero() {
		t.Error("unparseable date must be zero")
	}
}

func TestCleanHTMLAndTruncate(t *testing.T) {
	got := CleanHTML(`<div>Привет,&nbsp;<b>мир</b>!<br/>Строка&#160;2<style>p{}</style></div>`)
	if got != "Привет, мир !\nСтрока 2" {
		t.Errorf("CleanHTML = %q", got)
	}
	if s := TruncateRunes("один два три четыре", 9); s != "один два…" {
		t.Errorf("TruncateRunes = %q", s)
	}
}

func TestIsPublicAddr(t *testing.T) {
	blocked := []string{
		"127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "0.0.0.0",
		"100.64.0.1", "224.0.0.1", "255.255.255.255", "::1", "fe80::1", "fc00::1", "ff02::1", "::",
		"::ffff:127.0.0.1", "::ffff:10.0.0.1",
	}
	for _, s := range blocked {
		if IsPublicAddr(netip.MustParseAddr(s)) {
			t.Errorf("%s must be blocked", s)
		}
	}
	for _, s := range []string{"8.8.8.8", "95.163.0.1", "2a00:1450:4001::1"} {
		if !IsPublicAddr(netip.MustParseAddr(s)) {
			t.Errorf("%s must be allowed", s)
		}
	}
}

func TestNewPageFetcherExtraAllowed(t *testing.T) {
	extra, err := ParseCIDRList("240.0.0.0/4, 127.0.0.0/8")
	if err != nil {
		t.Fatal(err)
	}
	f := NewPageFetcher(extra...)
	if !f.allow(netip.MustParseAddr("240.0.0.48")) {
		t.Error("fake-IP range must be allowed when configured")
	}
	if f.allow(netip.MustParseAddr("127.0.0.1")) || f.allow(netip.MustParseAddr("10.0.0.1")) {
		t.Error("loopback/private must stay blocked regardless of FETCH_ALLOW_CIDRS")
	}
	if NewPageFetcher().allow(netip.MustParseAddr("240.0.0.48")) {
		t.Error("reserved range must be blocked by default")
	}
	if _, err := ParseCIDRList("nonsense"); err == nil {
		t.Error("invalid CIDR must fail")
	}
}

func TestPageFetcherBlocksPrivateAndSchemes(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, "<html><title>secret</title></html>")
	}))
	defer srv.Close()

	f := NewPageFetcher()
	for _, u := range []string{
		srv.URL,
		strings.Replace(srv.URL, "127.0.0.1", "localhost", 1),
		"ftp://example.com/file",
		"file:///etc/passwd",
		"http://user:pass@example.com/",
		"http://[::1]/",
		"http://169.254.169.254/latest/meta-data/",
	} {
		_, err := f.Fetch(context.Background(), u)
		if !errors.Is(err, ErrForbiddenURL) {
			t.Errorf("Fetch(%q) err = %v, want ErrForbiddenURL", u, err)
		}
	}
}

func TestPageFetcherChecksRedirectTargets(t *testing.T) {
	// Разрешаем только 127.0.0.1 (имитация «публичного» сервера), а редирект ведёт на 127.0.0.2.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, port, _ := net.SplitHostPort(r.Host)
		http.Redirect(w, r, "http://127.0.0.2:"+port+"/internal", http.StatusFound)
	}))
	defer srv.Close()

	only := netip.MustParseAddr("127.0.0.1")
	f := newPageFetcher(func(a netip.Addr) bool { return a == only })
	_, err := f.Fetch(context.Background(), srv.URL+"/start")
	if !errors.Is(err, ErrForbiddenURL) {
		t.Fatalf("redirect to blocked IP: err = %v, want ErrForbiddenURL", err)
	}
}

func TestPageFetcherExtractsContent(t *testing.T) {
	long := strings.Repeat("Компания объявила о росте выручки и планах инвестиций. ", 2)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		fmt.Fprintf(w, `<html><head><title> Заголовок &amp; новость </title>
<meta content="Описание из OG" property="og:description">
<script>var p = "<p>не текст</p>";</script></head>
<body><p>Короткий</p><p class="x">%s</p><p>Второй абзац с достаточно длинным текстом для извлечения.</p></body></html>`, long)
	}))
	defer srv.Close()

	f := newPageFetcher(func(netip.Addr) bool { return true })
	page, err := f.Fetch(context.Background(), srv.URL)
	if err != nil {
		t.Fatal(err)
	}
	if page.Title != "Заголовок & новость" || page.Description != "Описание из OG" {
		t.Errorf("page = %+v", page)
	}
	wantText := strings.TrimSpace(long) + "\nВторой абзац с достаточно длинным текстом для извлечения."
	if page.Text != wantText {
		t.Errorf("text = %q\nwant %q", page.Text, wantText)
	}
}

func TestPageFetcherSizeLimit(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Length", fmt.Sprint(3<<20))
		w.Header().Set("Content-Type", "text/html")
		_, _ = w.Write(make([]byte, 3<<20))
	}))
	defer srv.Close()
	f := newPageFetcher(func(netip.Addr) bool { return true })
	if _, err := f.Fetch(context.Background(), srv.URL); err == nil {
		t.Fatal("expected error for page larger than 2 MB")
	}
}

func TestRSSCollectorRetriesAndUserAgent(t *testing.T) {
	data, _ := os.ReadFile("testdata/feed.xml")
	calls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if !strings.Contains(r.UserAgent(), "Mozilla/5.0") {
			t.Errorf("user agent = %q", r.UserAgent())
		}
		if calls == 1 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		_, _ = w.Write(data)
	}))
	defer srv.Close()

	c := NewRSSCollector("Тест", srv.URL)
	c.backoff = time.Millisecond
	items, err := c.Collect(context.Background())
	if err != nil || len(items) != 4 || calls != 2 {
		t.Fatalf("items=%d err=%v calls=%d", len(items), err, calls)
	}

	notFound := httptest.NewServer(http.NotFoundHandler())
	defer notFound.Close()
	c2 := NewRSSCollector("404", notFound.URL)
	c2.backoff = time.Millisecond
	if _, err := c2.Collect(context.Background()); err == nil {
		t.Fatal("expected error for 404 feed")
	}
}

type fakeCollector struct {
	name  string
	items []News
	err   error
}

func (f fakeCollector) Name() string                            { return f.name }
func (f fakeCollector) Collect(context.Context) ([]News, error) { return f.items, f.err }

type fakeStore struct{ saved int }

func (s *fakeStore) SaveCollected(_ context.Context, items []News, _ string) (int, error) {
	s.saved += len(items)
	return len(items), nil
}

func TestImporterIsolatesSourceErrors(t *testing.T) {
	store := &fakeStore{}
	imp := &Importer{repo: store, collectors: []Collector{
		fakeCollector{name: "bad", err: errors.New("boom")},
		fakeCollector{name: "good", items: []News{{Title: "t", URL: "https://e.com/1"}}},
	}}
	res, err := imp.Import(context.Background())
	if err != nil || len(res) != 2 {
		t.Fatalf("res=%v err=%v", res, err)
	}
	if res[0].Error == "" || res[1].Error != "" || res[1].Inserted != 1 || store.saved != 1 {
		t.Fatalf("unexpected results: %+v", res)
	}
}

func TestReadSnapshot(t *testing.T) {
	path := t.TempDir() + "/snap.json"
	_ = os.WriteFile(path, []byte(`{"generated_at":"2026-10-24T19:00:00+03:00","items":[
		{"title":"Новость","summary":"текст","url":"https://e.com/a?utm_source=x","source_name":"Банк России","published_at":"2026-10-23T13:30:00+03:00"},
		{"title":"","url":"https://e.com/b"}]}`), 0o600)
	items, err := ReadSnapshot(path)
	if err != nil || len(items) != 1 {
		t.Fatalf("items=%v err=%v", items, err)
	}
	if items[0].Origin != OriginSnapshot || items[0].PublishedAt.IsZero() {
		t.Errorf("item = %+v", items[0])
	}
	if _, err := ReadSnapshot(t.TempDir() + "/missing.json"); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("missing file err = %v", err)
	}
}
