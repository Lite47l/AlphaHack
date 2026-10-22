package company

import (
	"context"
	"errors"
	"github.com/google/uuid"
)

type Service struct{ repo *Repository }

func NewService(repo *Repository) *Service { return &Service{repo: repo} }
func validID(id string) error {
	if _, err := uuid.Parse(id); err != nil {
		return errors.New("invalid id: expected UUID")
	}
	return nil
}
func validatePage(limit, offset int) error {
	if limit < 1 || limit > 100 {
		return errors.New("limit must be between 1 and 100")
	}
	if offset < 0 {
		return errors.New("offset must be >= 0")
	}
	return nil
}
func (s *Service) List(ctx context.Context, limit, offset int) ([]Company, error) {
	if err := validatePage(limit, offset); err != nil {
		return nil, err
	}
	return s.repo.List(ctx, limit, offset)
}
func (s *Service) GetByID(ctx context.Context, id string) (Company, error) {
	if err := validID(id); err != nil {
		return Company{}, err
	}
	return s.repo.GetByID(ctx, id)
}
func (s *Service) Feed(ctx context.Context, id string, limit int) ([]FeedItem, error) {
	if err := validID(id); err != nil {
		return nil, err
	}
	if limit < 1 || limit > 100 {
		return nil, errors.New("limit must be between 1 and 100")
	}
	return s.repo.Feed(ctx, id, limit)
}
