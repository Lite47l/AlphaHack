package config

import (
	"fmt"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

// FeedSource — RSS-источник новостей.
type FeedSource struct {
	Name string
	URL  string
}

// DefaultNewsFeeds — проверенные источники по умолчанию (формат NEWS_FEEDS: "Имя|url;Имя|url").
const DefaultNewsFeeds = "Банк России|https://www.cbr.ru/rss/RssPress;" +
	"Банк России (события)|https://www.cbr.ru/rss/eventrss;" +
	"РБК|https://rssexport.rbc.ru/rbcnews/news/30/full.rss;" +
	"Ведомости|https://www.vedomosti.ru/rss/news;" +
	"Коммерсантъ|https://www.kommersant.ru/RSS/news.xml;" +
	"Лента.ру Экономика|https://lenta.ru/rss/news/economics;" +
	"Banki.ru|https://www.banki.ru/xml/news.rss"

type Config struct {
	Port                   string
	DatabaseURL            string
	AppEnv                 string
	LogLevel               string
	ShutdownTimeoutSeconds int

	AIURL              string
	NewsFeeds          []FeedSource
	NewsImportInterval time.Duration
	NewsImportOnStart  bool
	NewsSnapshotPath   string
	RateLimitPerMinute int
	// FetchAllowCIDRs — доп. диапазоны для загрузки страниц по URL (fake-IP DNS у VPN).
	FetchAllowCIDRs string
}

func Load() (Config, error) {
	c := Config{
		Port:                   getEnv("PORT", "8080"),
		DatabaseURL:            getEnv("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/hackathon?sslmode=disable"),
		AppEnv:                 getEnv("APP_ENV", "dev"),
		LogLevel:               strings.ToLower(getEnv("LOG_LEVEL", "info")),
		ShutdownTimeoutSeconds: 10,
		AIURL:                  strings.TrimRight(getEnv("AI_URL", "http://ai:8000"), "/"),
		NewsSnapshotPath:       getEnv("NEWS_SNAPSHOT_PATH", "/data/news_snapshot.json"),
		NewsImportOnStart:      getEnv("NEWS_IMPORT_ON_START", "true") != "false",
		RateLimitPerMinute:     20,
		FetchAllowCIDRs:        os.Getenv("FETCH_ALLOW_CIDRS"),
	}
	if _, err := strconv.Atoi(c.Port); err != nil {
		return Config{}, fmt.Errorf("PORT must be a port number: %w", err)
	}
	if c.DatabaseURL == "" {
		return Config{}, fmt.Errorf("DATABASE_URL is required")
	}
	if v := os.Getenv("SHUTDOWN_TIMEOUT_SECONDS"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil {
			return Config{}, fmt.Errorf("SHUTDOWN_TIMEOUT_SECONDS must be a number: %w", err)
		}
		c.ShutdownTimeoutSeconds = n
	}
	if c.ShutdownTimeoutSeconds < 1 {
		return Config{}, fmt.Errorf("SHUTDOWN_TIMEOUT_SECONDS must be positive")
	}
	if u, err := url.Parse(c.AIURL); err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		return Config{}, fmt.Errorf("AI_URL must be an http(s) URL")
	}

	interval, err := time.ParseDuration(getEnv("NEWS_IMPORT_INTERVAL", "30m"))
	if err != nil {
		return Config{}, fmt.Errorf("NEWS_IMPORT_INTERVAL: %w", err)
	}
	if interval != 0 && interval < time.Minute {
		return Config{}, fmt.Errorf("NEWS_IMPORT_INTERVAL must be 0 (disabled) or >= 1m")
	}
	c.NewsImportInterval = interval

	feeds, err := ParseFeeds(getEnv("NEWS_FEEDS", DefaultNewsFeeds))
	if err != nil {
		return Config{}, err
	}
	c.NewsFeeds = feeds

	if v := os.Getenv("RATE_LIMIT_PER_MINUTE"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 1 {
			return Config{}, fmt.Errorf("RATE_LIMIT_PER_MINUTE must be a positive number")
		}
		c.RateLimitPerMinute = n
	}
	return c, nil
}

// ParseFeeds разбирает строку вида "Имя|url;Имя|url". Пустые элементы пропускаются.
func ParseFeeds(raw string) ([]FeedSource, error) {
	var feeds []FeedSource
	for _, part := range strings.Split(raw, ";") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		name, rawURL, ok := strings.Cut(part, "|")
		name, rawURL = strings.TrimSpace(name), strings.TrimSpace(rawURL)
		if !ok || name == "" || rawURL == "" {
			return nil, fmt.Errorf("NEWS_FEEDS: invalid entry %q, expected Name|url", part)
		}
		u, err := url.Parse(rawURL)
		if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
			return nil, fmt.Errorf("NEWS_FEEDS: invalid url for %q", name)
		}
		feeds = append(feeds, FeedSource{Name: name, URL: rawURL})
	}
	return feeds, nil
}

func getEnv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
