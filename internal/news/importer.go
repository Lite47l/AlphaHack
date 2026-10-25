package news

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"strings"
	"sync"
	"time"
)

// newsStore — часть репозитория, нужная импортёру (подменяется в тестах).
type newsStore interface {
	SaveCollected(ctx context.Context, items []News, origin string) (int, error)
}

type Importer struct {
	repo       newsStore
	collectors []Collector
	logger     *slog.Logger
	mu         sync.Mutex // не допускаем параллельных импортов (таймер + ручной запуск)
}

func NewImporter(repo *Repository, logger *slog.Logger, collectors ...Collector) *Importer {
	return &Importer{repo: repo, collectors: collectors, logger: logger}
}

type ImporterResult struct {
	Source   string `json:"source"`
	Fetched  int    `json:"fetched"`
	Inserted int    `json:"inserted"`
	Error    string `json:"error,omitempty"`
}

const collectTimeout = 90 * time.Second

// Import опрашивает все коллекторы параллельно; ошибка одного источника
// не останавливает остальные.
func (i *Importer) Import(ctx context.Context) ([]ImporterResult, error) {
	i.mu.Lock()
	defer i.mu.Unlock()

	type collected struct {
		items []News
		err   error
	}
	out := make([]collected, len(i.collectors))
	var wg sync.WaitGroup
	for idx, c := range i.collectors {
		wg.Add(1)
		go func() {
			defer wg.Done()
			timeout := collectTimeout
			if _, ok := c.(*RBCCollector); ok {
				timeout = 10 * time.Minute
			}
			cctx, cancel := context.WithTimeout(ctx, timeout)
			defer cancel()
			items, err := c.Collect(cctx)
			out[idx] = collected{items: items, err: err}
		}()
	}
	wg.Wait()

	results := make([]ImporterResult, 0, len(i.collectors))
	for idx, c := range i.collectors {
		res := ImporterResult{Source: c.Name()}
		if err := out[idx].err; err != nil {
			res.Error = err.Error()
			results = append(results, res)
			continue
		}
		res.Fetched = len(out[idx].items)
		inserted, err := i.repo.SaveCollected(ctx, out[idx].items, OriginCollector)
		if err != nil {
			res.Error = fmt.Sprintf("save news: %v", err)
		}
		res.Inserted = inserted
		results = append(results, res)
	}
	if i.logger != nil {
		for _, r := range results {
			if r.Error != "" {
				i.logger.Warn("news import source failed", "source", r.Source, "fetched", r.Fetched, "error", r.Error)
			} else {
				i.logger.Info("news import source", "source", r.Source, "fetched", r.Fetched, "inserted", r.Inserted)
			}
		}
	}
	return results, nil
}

// Run выполняет импорт сразу (если runNow) и затем по таймеру до отмены ctx.
// interval == 0 отключает периодический импорт.
func (i *Importer) Run(ctx context.Context, interval time.Duration, runNow bool) {
	if runNow {
		_, _ = i.Import(ctx)
	}
	if interval <= 0 {
		return
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			_, _ = i.Import(ctx)
		}
	}
}

type snapshotFile struct {
	GeneratedAt string `json:"generated_at"`
	Items       []struct {
		Title       string `json:"title"`
		Summary     string `json:"summary"`
		Content     string `json:"content"`
		URL         string `json:"url"`
		SourceName  string `json:"source_name"`
		PublishedAt string `json:"published_at"`
	} `json:"items"`
}

// LoadSnapshotIfEmpty загружает контрольный снимок новостей, если таблица news пуста.
// Отсутствие файла — не ошибка (только предупреждение в логе).
func LoadSnapshotIfEmpty(ctx context.Context, repo *Repository, path string, logger *slog.Logger) error {
	empty, err := repo.IsEmpty(ctx)
	if err != nil {
		return err
	}
	if !empty {
		return nil
	}
	items, err := ReadSnapshot(path)
	if errors.Is(err, os.ErrNotExist) {
		logger.Warn("news snapshot not found, skipping", "path", path)
		return nil
	}
	if err != nil {
		return err
	}
	inserted, err := repo.SaveCollected(ctx, items, OriginSnapshot)
	if err != nil {
		return fmt.Errorf("save snapshot: %w", err)
	}
	logger.Info("news snapshot loaded", "path", path, "items", len(items), "inserted", inserted)
	return nil
}

// ReadSnapshot читает файл снимка (формат описан в docs/api_contract.md).
func ReadSnapshot(path string) ([]News, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var f snapshotFile
	if err := json.Unmarshal(data, &f); err != nil {
		return nil, fmt.Errorf("parse snapshot %s: %w", path, err)
	}
	items := make([]News, 0, len(f.Items))
	for _, x := range f.Items {
		title := singleLine(x.Title)
		if title == "" || NormalizeURL(x.URL) == "" {
			continue
		}
		items = append(items, News{
			Title:       title,
			Summary:     TruncateRunes(NormalizeText(x.Summary), maxSummaryRunes),
			Content:     TruncateRunes(NormalizeText(x.Content), maxContentRunes),
			URL:         x.URL,
			SourceName:  strings.TrimSpace(x.SourceName),
			PublishedAt: ParseFeedDate(x.PublishedAt),
			Origin:      OriginSnapshot,
		})
	}
	return items, nil
}
