package knowledge

import (
	"context"
	"errors"
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
