package news

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"
)

type RBCCollector struct {
	client  *http.Client
	baseURL string
	query   string
	days    int
}
type rbcRequest struct {
	DateFrom string `json:"date_from"`
	DateTo   string `json:"date_to"`
	Query    string `json:"query"`
}
type rbcArticle struct {
	ID                string   `json:"id"`
	Title             string   `json:"title"`
	Text              *string  `json:"text"`
	Date              string   `json:"date"`
	Source            string   `json:"source"`
	URL               string   `json:"url"`
	FoundCompanies    []string `json:"found_companies"`
	OKVEDCodes        *string  `json:"okved_codes"`
	OKVEDDescriptions *string  `json:"okved_descriptions"`
	OKVEDScores       *string  `json:"okved_scores"`
}

func NewRBCCollector() *RBCCollector {
	base := strings.TrimRight(strings.TrimSpace(os.Getenv("RBC_PARSER_URL")), "/")
	if base == "" {
		base = "http://rbc-parser:8000"
	}
	query := strings.TrimSpace(os.Getenv("RBC_QUERY"))
	if query == "" {
		query = "экономика"
	}
	days := 7
	return &RBCCollector{client: &http.Client{Timeout: 10 * time.Minute}, baseURL: base, query: query, days: days}
}
func (c *RBCCollector) Name() string { return "RBC.ru" }
func (c *RBCCollector) Collect(ctx context.Context) ([]News, error) {
	now := time.Now()
	payload := rbcRequest{DateFrom: now.AddDate(0, 0, -c.days).Format("2006-01-02"), DateTo: now.Format("2006-01-02"), Query: c.query}
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.baseURL+"/parse", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("RBC parser request: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("RBC parser returned HTTP %d", resp.StatusCode)
	}
	var articles []rbcArticle
	if err := json.NewDecoder(resp.Body).Decode(&articles); err != nil {
		return nil, fmt.Errorf("decode RBC response: %w", err)
	}
	items := make([]News, 0, len(articles))
	seen := map[string]struct{}{}
	for _, a := range articles {
		title := strings.TrimSpace(a.Title)
		normalized := NormalizeURL(a.URL)
		if title == "" || normalized == "" {
			continue
		}
		if _, ok := seen[normalized]; ok {
			continue
		}
		seen[normalized] = struct{}{}
		summary := ""
		if a.Text != nil {
			summary = strings.TrimSpace(*a.Text)
		}
		var published time.Time

		if a.Date != "" {
			parsed, err := time.Parse(time.RFC3339, a.Date)
			if err != nil {
				parsed, err = time.ParseInLocation(
					"2006-01-02T15:04:05",
					a.Date,
					time.UTC,
				)
			}

			if err != nil {
				return nil, fmt.Errorf("parse RBC article date %q: %w", a.Date, err)
			}

			published = parsed.UTC()
		}
		items = append(items, News{Title: title, Summary: TruncateRunes(summary, maxSummaryRunes), Content: TruncateRunes(summary, maxContentRunes), URL: normalized, SourceName: c.Name(), PublishedAt: published})
	}
	return items, nil
}
