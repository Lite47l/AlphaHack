package news

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"
)

type AlfaCollector struct {
	client *http.Client
	URL    string
}

func NewAlfaCollector() *AlfaCollector {
	return &AlfaCollector{
		client: &http.Client{
			Timeout: 15 * time.Second,
		},
		URL: "https://alfabank.ru/news/",
	}
}

func (c *AlfaCollector) Name() string {
	return "Альфа-банк"
}

func (c *AlfaCollector) Collect(ctx context.Context) ([]News, error) {
	req, err := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		"https://alfabank.ru/news/",
		nil,
	)
	if err != nil {
		return nil, fmt.Errorf("create Alfa news request: %w", err)
	}

	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
	req.Header.Set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
	req.Header.Set("Accept-Language", "ru-RU,ru;q=0.9,en;q=0.8")

	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request Alfa news: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("Alfa news returned HTTP %d", resp.StatusCode)
	}

	const maxBodySize = 5 << 20

	body, err := io.ReadAll(io.LimitReader(resp.Body, maxBodySize))
	if err != nil {
		return nil, fmt.Errorf("read Alfa news: %w", err)
	}

	html := string(body)

	linkPattern := regexp.MustCompile(
		`(?is)<a\b[^>]*href=["']([^"'#]+)["'][^>]*>(.*?)</a\s*>`,
	)
	tagPattern := regexp.MustCompile(`(?is)<[^>]+>`)
	spacePattern := regexp.MustCompile(`\s+`)

	items := make([]News, 0)
	seen := make(map[string]struct{})

	for _, match := range linkPattern.FindAllStringSubmatch(html, -1) {
		href := strings.TrimSpace(match[1])
		title := tagPattern.ReplaceAllString(match[2], " ")
		title = strings.TrimSpace(spacePattern.ReplaceAllString(title, " "))

		if title == "" || len([]rune(title)) < 15 {
			continue
		}

		if strings.HasPrefix(href, "/") {
			href = "https://alfabank.ru" + href
		}

		normalizedURL := NormalizeURL(href)
		if normalizedURL == "" ||
			!strings.HasPrefix(normalizedURL, "https://alfabank.ru/news/") {
			continue
		}

		if _, exists := seen[normalizedURL]; exists {
			continue
		}
		seen[normalizedURL] = struct{}{}

		items = append(items, News{
			Title:       title,
			Summary:     "",
			URL:         normalizedURL,
			SourceName:  c.Name(),
			PublishedAt: time.Time{},
		})
	}

	if len(items) == 0 {
		return nil, fmt.Errorf(
			"no Alfa publications found; website markup may have changed",
		)
	}

	return items, nil
}

type MockCollector struct{}

func NewMockCollector() *MockCollector {
	return &MockCollector{}
}

func (c *MockCollector) Name() string {
	return "Mock News Source"
}

func (c *MockCollector) Collect(ctx context.Context) ([]News, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}

	now := time.Now().UTC()

	return []News{
		{
			Title:       "[MOCK] Пример новости о финансовом рынке",
			Summary:     "Тестовая публикация для проверки импорта новостей.",
			URL:         "https://mock.invalid/news/financial-market-001",
			SourceName:  c.Name(),
			PublishedAt: now,
		},
		{
			Title:       "[MOCK] Пример новости о корпоративном секторе",
			Summary:     "Тестовая публикация о состоянии корпоративного сектора.",
			URL:         "https://mock.invalid/news/corporate-sector-002",
			SourceName:  c.Name(),
			PublishedAt: now.Add(-time.Hour),
		},
	}, nil
}
