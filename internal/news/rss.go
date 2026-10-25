package news

import (
	"bytes"
	"context"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Collector — источник публикаций для импорта.
type Collector interface {
	Name() string
	Collect(ctx context.Context) ([]News, error)
}

const (
	browserUserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
	maxFeedBytes     = 10 << 20
	maxFeedItems     = 100
	feedAttempts     = 3
)

// RSSCollector — универсальный коллектор RSS 2.0 (и простого Atom).
type RSSCollector struct {
	name     string
	url      string
	client   *http.Client
	maxItems int
	backoff  time.Duration
}

func NewRSSCollector(name, feedURL string) *RSSCollector {
	return &RSSCollector{
		name:     name,
		url:      feedURL,
		client:   &http.Client{Timeout: 20 * time.Second},
		maxItems: maxFeedItems,
		backoff:  time.Second,
	}
}

func (c *RSSCollector) Name() string { return c.name }

func (c *RSSCollector) Collect(ctx context.Context) ([]News, error) {
	body, err := c.fetch(ctx)
	if err != nil {
		return nil, err
	}
	items, err := ParseRSS(body, c.name, c.maxItems)
	if err != nil {
		return nil, fmt.Errorf("parse feed: %w", err)
	}
	if len(items) == 0 {
		return nil, errors.New("feed contains no items")
	}
	return items, nil
}

// fetch загружает ленту с ограниченным числом повторов при сетевых ошибках, 429 и 5xx.
func (c *RSSCollector) fetch(ctx context.Context) ([]byte, error) {
	var lastErr error
	for attempt := 1; attempt <= feedAttempts; attempt++ {
		if attempt > 1 {
			select {
			case <-ctx.Done():
				return nil, ctx.Err()
			case <-time.After(c.backoff * time.Duration(attempt-1)):
			}
		}
		body, retry, err := c.fetchOnce(ctx)
		if err == nil {
			return body, nil
		}
		lastErr = err
		if !retry || ctx.Err() != nil {
			break
		}
	}
	return nil, lastErr
}

func (c *RSSCollector) fetchOnce(ctx context.Context) ([]byte, bool, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.url, nil)
	if err != nil {
		return nil, false, fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("User-Agent", browserUserAgent)
	req.Header.Set("Accept", "application/rss+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.8")
	req.Header.Set("Accept-Language", "ru-RU,ru;q=0.9,en;q=0.8")

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, true, fmt.Errorf("request feed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 64<<10))
		retry := resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500
		return nil, retry, fmt.Errorf("feed returned HTTP %d", resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxFeedBytes))
	if err != nil {
		return nil, true, fmt.Errorf("read feed: %w", err)
	}
	return body, false, nil
}

// ParseRSS разбирает RSS 2.0 / Atom. Поддерживаются yandex:full-text,
// rbc_news:full-text и content:encoded как полный текст.
func ParseRSS(data []byte, sourceName string, maxItems int) ([]News, error) {
	data = bytes.TrimPrefix(data, utf8BOM)
	dec := xml.NewDecoder(bytes.NewReader(data))
	dec.Strict = false
	dec.Entity = xml.HTMLEntity
	dec.CharsetReader = xmlCharsetReader

	now := time.Now().UTC()
	items := make([]News, 0)
	seen := make(map[string]struct{})
	for {
		tok, err := dec.Token()
		if err == io.EOF {
			break
		}
		if err != nil {
			if len(items) > 0 {
				break // частично повреждённая лента: оставляем уже разобранное
			}
			return nil, err
		}
		se, ok := tok.(xml.StartElement)
		if !ok || (se.Name.Local != "item" && se.Name.Local != "entry") {
			continue
		}
		f, err := readItemFields(dec)
		if err != nil {
			if len(items) > 0 {
				break
			}
			return nil, err
		}
		item, ok := buildItem(f, sourceName, now)
		if !ok {
			continue
		}
		if _, dup := seen[item.URL]; dup {
			continue
		}
		seen[item.URL] = struct{}{}
		items = append(items, item)
		if maxItems > 0 && len(items) >= maxItems {
			break
		}
	}
	return items, nil
}

// itemFields — дочерние элементы item: без пространства имён и с ним.
type itemFields struct {
	plain map[string]string
	ns    map[string]string
}

func (f itemFields) get(names ...string) string {
	for _, n := range names {
		if v := strings.TrimSpace(f.plain[n]); v != "" {
			return v
		}
	}
	for _, n := range names {
		if v := strings.TrimSpace(f.ns[n]); v != "" {
			return v
		}
	}
	return ""
}

func readItemFields(dec *xml.Decoder) (itemFields, error) {
	f := itemFields{plain: map[string]string{}, ns: map[string]string{}}
	for {
		tok, err := dec.Token()
		if err != nil {
			return f, err
		}
		switch t := tok.(type) {
		case xml.EndElement:
			return f, nil // конец item/entry
		case xml.StartElement:
			text, err := readElementText(dec)
			if err != nil {
				return f, err
			}
			if t.Name.Local == "link" && strings.TrimSpace(text) == "" {
				for _, a := range t.Attr {
					if a.Name.Local == "href" {
						text = a.Value
					}
				}
			}
			target := f.plain
			if t.Name.Space != "" {
				target = f.ns
			}
			if strings.TrimSpace(target[t.Name.Local]) == "" {
				target[t.Name.Local] = text
			}
		}
	}
}

// readElementText собирает текст (включая CDATA) до закрывающего тега.
// Вложенные XML-элементы превращаются в теги-разделители для CleanHTML.
func readElementText(dec *xml.Decoder) (string, error) {
	var b strings.Builder
	depth := 1
	for depth > 0 {
		tok, err := dec.Token()
		if err != nil {
			return b.String(), err
		}
		switch t := tok.(type) {
		case xml.StartElement:
			depth++
			b.WriteString("<" + t.Name.Local + ">")
		case xml.EndElement:
			depth--
			if depth > 0 {
				b.WriteString("</" + t.Name.Local + ">")
			}
		case xml.CharData:
			b.Write(t)
		}
	}
	return b.String(), nil
}

func buildItem(f itemFields, sourceName string, now time.Time) (News, bool) {
	title := singleLine(CleanHTML(f.get("title")))
	link := f.get("link", "pdalink")
	if link == "" {
		if g := f.get("guid", "id"); strings.HasPrefix(g, "http://") || strings.HasPrefix(g, "https://") {
			link = g
		}
	}
	link = NormalizeURL(link)
	if title == "" || link == "" || !(strings.HasPrefix(link, "http://") || strings.HasPrefix(link, "https://")) {
		return News{}, false
	}

	summary := TruncateRunes(CleanHTML(f.get("description", "summary", "synopsis", "anons")), maxSummaryRunes)
	content := dropBoilerplate(CleanHTML(f.get("full-text", "encoded", "content")))
	if summary == "" && content != "" {
		summary = TruncateRunes(content, 1000)
	}
	if content == summary {
		content = ""
	}
	content = TruncateRunes(content, maxContentRunes)

	published := ParseFeedDate(f.get("pubDate", "published", "updated", "date"))
	if published.After(now.Add(time.Hour)) {
		published = now
	}
	return News{
		Title:       title,
		Summary:     summary,
		Content:     content,
		URL:         link,
		SourceName:  sourceName,
		PublishedAt: published,
		Origin:      OriginCollector,
	}, true
}

// boilerplatePrefixes — служебные строки источников, не относящиеся к новости.
var boilerplatePrefixes = []string{"Оставайтесь на связи с РБК", "Читайте РБК в", "Подписывайтесь на"}

func dropBoilerplate(s string) string {
	if s == "" {
		return s
	}
	lines := strings.Split(s, "\n")
	out := lines[:0]
	for _, line := range lines {
		skip := false
		for _, p := range boilerplatePrefixes {
			if strings.HasPrefix(line, p) {
				skip = true
				break
			}
		}
		if !skip {
			out = append(out, line)
		}
	}
	return strings.Join(out, "\n")
}

var feedDateLayouts = []string{
	time.RFC1123Z,
	time.RFC1123,
	"Mon, 2 Jan 2006 15:04:05 -0700",
	"Mon, 2 Jan 2006 15:04:05 MST",
	"Mon, 02 Jan 2006 15:04 -0700",
	"Mon, 2 Jan 2006 15:04 -0700",
	"02 Jan 2006 15:04:05 -0700",
	"2 Jan 2006 15:04:05 -0700",
	time.RFC3339Nano,
	time.RFC3339,
	"2006-01-02T15:04:05-0700",
	"2006-01-02 15:04:05 -0700",
	"2006-01-02 15:04:05",
	"2006-01-02",
}

var moscow = time.FixedZone("MSK", 3*60*60)

// ParseFeedDate разбирает дату публикации (RFC1123Z и распространённые варианты).
// Возвращает нулевое время, если формат не распознан.
func ParseFeedDate(s string) time.Time {
	s = strings.Join(strings.Fields(s), " ")
	if s == "" {
		return time.Time{}
	}
	s = strings.Replace(s, " MSK", " +0300", 1)
	s = strings.Replace(s, " UT", " UTC", 1)
	s = strings.Replace(s, " UTCC", " UTC", 1)
	for _, layout := range feedDateLayouts {
		if t, err := time.Parse(layout, s); err == nil {
			if layout == "2006-01-02 15:04:05" || layout == "2006-01-02" {
				t = time.Date(t.Year(), t.Month(), t.Day(), t.Hour(), t.Minute(), t.Second(), 0, moscow)
			}
			return t
		}
	}
	return time.Time{}
}
