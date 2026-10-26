package knowledge

import (
    "context"
    "crypto/sha256"
    "encoding/hex"
    "errors"
    "path/filepath"
    "strings"
    "time"
)

type Service struct{ repo *Repository }

func NewService(repo *Repository) *Service { return &Service{repo: repo} }

func (s *Service) List(ctx context.Context, limit, offset int) ([]Document, error) {
    if limit < 1 || limit > 100 {
        return nil, errors.New("limit must be between 1 and 100")
    }
    if offset < 0 {
        return nil, errors.New("offset must be >= 0")
    }
    return s.repo.List(ctx, limit, offset)
}

func (s *Service) ImportPDF(
    ctx context.Context,
    path string,
    title string,
    documentURL string,
    publishedAt *time.Time,
) (string, bool, error) {
    data, err := readPDF(path)
    if err != nil {
        return "", false, err
    }
    pages, err := extractPDF(ctx, path)
    if err != nil {
        return "", false, err
    }
    if strings.TrimSpace(title) == "" {
        title = filepath.Base(path)
    }
    hash := sha256.Sum256(data)
    return s.repo.SavePDF(
        ctx, title, "Alfa-Bank", documentURL, publishedAt,
        hex.EncodeToString(hash[:]), pages,
    )
}
