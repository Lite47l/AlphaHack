package analysis

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Service struct {
	repo *Repository
	db   *pgxpool.Pool
}

func NewService(repo *Repository, db *pgxpool.Pool) *Service { return &Service{repo: repo, db: db} }
func (s *Service) Create(ctx context.Context, companyID string) (Analysis, error) {
	if _, err := uuid.Parse(companyID); err != nil {
		return Analysis{}, errors.New("invalid company id: expected UUID")
	}
	var exists bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM companies WHERE id=$1)`, companyID).Scan(&exists); err != nil {
		return Analysis{}, err
	}
	if !exists {
		return Analysis{}, errors.New("company not found")
	}
	return s.repo.Create(ctx, companyID)
}
func (s *Service) GetByID(ctx context.Context, id string) (Analysis, error) {
	if _, err := uuid.Parse(id); err != nil {
		return Analysis{}, errors.New("invalid id: expected UUID")
	}
	return s.repo.GetByID(ctx, id)
}
