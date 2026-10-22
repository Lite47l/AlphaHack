package knowledge

import (
	"context"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Repository struct{ db *pgxpool.Pool }

func NewRepository(db *pgxpool.Pool) *Repository { return &Repository{db: db} }
func (r *Repository) List(ctx context.Context, limit, offset int) ([]Document, error) {
	rows, err := r.db.Query(ctx, `SELECT id::text,title,institution,document_url,COALESCE(published_at,created_at) FROM knowledge_documents ORDER BY COALESCE(published_at,created_at) DESC,id LIMIT $1 OFFSET $2`, limit, offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]Document, 0)
	for rows.Next() {
		var x Document
		if err := rows.Scan(&x.ID, &x.Title, &x.Institution, &x.DocumentURL, &x.PublishedAt); err != nil {
			return nil, err
		}
		items = append(items, x)
	}
	return items, rows.Err()
}
