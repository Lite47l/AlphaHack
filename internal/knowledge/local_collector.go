package knowledge

import (
	"context"
	"fmt"
	"hackathon-backend/internal/response"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type LocalPDFCollector struct {
	service *Service
	dir     string
}

type LocalPDFResult struct {
	Name     string `json:"name"`
	ID       string `json:"id,omitempty"`
	Inserted bool   `json:"inserted"`
	Error    string `json:"error,omitempty"`
}

func NewLocalPDFCollector(service *Service, dir string) *LocalPDFCollector {
	return &LocalPDFCollector{
		service: service,
		dir:     dir,
	}
}

func (c *LocalPDFCollector) Collect(ctx context.Context) ([]LocalPDFResult, error) {
	if c.service == nil {
		return nil, fmt.Errorf("knowledge service is not configured")
	}

	dir := strings.TrimSpace(c.dir)
	if dir == "" {
		return nil, fmt.Errorf("local PDF directory is not configured")
	}

	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, fmt.Errorf("read PDF directory %q: %w", dir, err)
	}

	var files []string

	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}

		if strings.EqualFold(filepath.Ext(entry.Name()), ".pdf") {
			files = append(files, filepath.Join(dir, entry.Name()))
		}
	}

	sort.Strings(files)

	if len(files) == 0 {
		return []LocalPDFResult{}, nil
	}

	results := make([]LocalPDFResult, 0, len(files))

	for _, file := range files {
		if err := ctx.Err(); err != nil {
			return results, err
		}

		name := filepath.Base(file)
		result := LocalPDFResult{Name: name}

		info, err := os.Stat(file)
		if err != nil {
			result.Error = fmt.Sprintf("stat file: %v", err)
			results = append(results, result)
			continue
		}

		if !info.Mode().IsRegular() {
			result.Error = "not a regular file"
			results = append(results, result)
			continue
		}

		if info.Size() == 0 {
			result.Error = "PDF file is empty"
			results = append(results, result)
			continue
		}

		id, inserted, err := c.service.ImportPDF(
			ctx,
			file,
			name,
			"",
			nil,
		)
		if err != nil {
			result.Error = err.Error()
			results = append(results, result)
			continue
		}

		result.ID = id
		result.Inserted = inserted
		results = append(results, result)
	}

	return results, nil
}

func (c *LocalPDFCollector) CollectWithTimeout(
	ctx context.Context,
	timeout time.Duration,
) ([]LocalPDFResult, error) {
	if timeout <= 0 {
		return c.Collect(ctx)
	}

	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	return c.Collect(ctx)
}

func (h *Handler) CollectLocal(collector *LocalPDFCollector) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		results, err := collector.CollectWithTimeout(
			r.Context(),
			30*time.Minute,
		)
		if err != nil {
			response.WriteServiceError(w, err)
			return
		}

		inserted := 0
		failed := 0

		for _, item := range results {
			if item.Error != "" {
				failed++
			}
			if item.Inserted {
				inserted++
			}
		}

		response.WriteJSON(w, http.StatusOK, map[string]any{
			"items":    results,
			"count":    len(results),
			"inserted": inserted,
			"failed":   failed,
		})
	}
}
