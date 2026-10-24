package news

import (
	"context"
	"fmt"
)

type Importer struct {
	repo       *Repository
	collectors []Collector
}

func NewImporter(repo *Repository, collectors ...Collector) *Importer {
	return &Importer{
		repo:       repo,
		collectors: collectors,
	}
}

type ImporterResult struct {
	Source   string `json:"source"`
	Fetched  int    `json:"fetched"`
	Inserted int    `json:"inserted"`
	Error    string `json:"error,omitempty"`
}

func (i *Importer) Import(ctx context.Context) ([]ImporterResult, error) {
	results := make([]ImporterResult, 0, len(i.collectors))

	for _, collector := range i.collectors {
		items, err := collector.Collect(ctx)
		if err != nil {
			results = append(results, ImporterResult{
				Source: collector.Name(),
				Error:  err.Error(),
			})
			continue
		}

		inserted, err := i.repo.SaveCollected(ctx, items)
		if err != nil {
			results = append(results, ImporterResult{
				Source:  collector.Name(),
				Fetched: len(items),
				Error:   fmt.Sprintf("save news: %v", err),
			})
			continue
		}

		results = append(results, ImporterResult{
			Source:   collector.Name(),
			Fetched:  len(items),
			Inserted: inserted,
		})
	}

	return results, nil
}
