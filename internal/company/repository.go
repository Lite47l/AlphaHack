package company

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var ErrNotFound = errors.New("company not found")

type Repository struct{ db *pgxpool.Pool }

func NewRepository(db *pgxpool.Pool) *Repository { return &Repository{db: db} }
func (r *Repository) List(ctx context.Context, limit, offset int) ([]Company, error) {
	rows, err := r.db.Query(ctx, `SELECT id::text,name,industry,description,created_at FROM companies ORDER BY name,id LIMIT $1 OFFSET $2`, limit, offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]Company, 0)
	for rows.Next() {
		var x Company
		if err := rows.Scan(&x.ID, &x.Name, &x.Industry, &x.Description, &x.CreatedAt); err != nil {
			return nil, err
		}
		items = append(items, x)
	}
	return items, rows.Err()
}
func (r *Repository) GetByID(ctx context.Context, id string) (Company, error) {
	if _, err := uuid.Parse(id); err != nil {
		return Company{}, ErrNotFound
	}
	var x Company
	err := r.db.QueryRow(ctx, `SELECT id::text,name,industry,description,created_at FROM companies WHERE id=$1`, id).Scan(&x.ID, &x.Name, &x.Industry, &x.Description, &x.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return Company{}, ErrNotFound
	}
	return x, err
}
func (r *Repository) Feed(ctx context.Context, id string, limit int) ([]FeedItem, error) {
	if _, err := r.GetByID(ctx, id); err != nil {
		return nil, err
	}
	rows, err := r.db.Query(ctx, `SELECT id,kind,title,url,published_at FROM (SELECT n.id::text id,'news' kind,n.title,n.url,COALESCE(n.published_at,n.created_at) published_at FROM news n JOIN company_news cn ON cn.news_id=n.id WHERE cn.company_id=$1 UNION ALL SELECT kd.id::text,'knowledge',kd.title,kd.document_url,COALESCE(kd.published_at,kd.created_at) FROM knowledge_documents kd) f ORDER BY published_at DESC LIMIT $2`, id, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]FeedItem, 0)
	for rows.Next() {
		var x FeedItem
		if err := rows.Scan(&x.ID, &x.Kind, &x.Title, &x.URL, &x.Published); err != nil {
			return nil, err
		}
		items = append(items, x)
	}
	return items, rows.Err()
}
