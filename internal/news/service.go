package news

import (
	"context"
	"errors"
	"github.com/google/uuid"
)

type Service struct{ repo *Repository }

func NewService(repo *Repository) *Service { return &Service{repo: repo} }
func (s *Service) List(ctx context.Context, limit, offset int, companyID string) ([]News, error) {
	if limit < 1 || limit > 100 {
		return nil, errors.New("limit must be between 1 and 100")
	}
	if offset < 0 {
		return nil, errors.New("offset must be >= 0")
	}
	if companyID != "" {
		if _, err := uuid.Parse(companyID); err != nil {
			return nil, errors.New("invalid company_id: expected UUID")
		}
	}
	return s.repo.List(ctx, limit, offset, companyID)
}
func (s *Service) GetByID(ctx context.Context, id string) (News, error) {
	if _, err := uuid.Parse(id); err != nil {
		return News{}, errors.New("invalid id: expected UUID")
	}
	return s.repo.GetByID(ctx, id)
}
