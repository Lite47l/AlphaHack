package news

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var ErrNotFound = errors.New("news not found")

type Repository struct{ db *pgxpool.Pool }

func NewRepository(db *pgxpool.Pool) *Repository { return &Repository{db: db} }
func (r *Repository) List(ctx context.Context, limit, offset int, companyID string) ([]News, error) {
	if companyID != "" {
		if _, err := uuid.Parse(companyID); err != nil {
			return nil, errors.New("invalid company_id: expected UUID")
		}
	}
	q := `
    SELECT
        n.id::text,
        n.title,
        n.summary,
        n.url,
        COALESCE(s.name, ''),
        COALESCE(n.published_at, n.created_at)
    FROM news n
    LEFT JOIN sources s ON s.id = n.source_id
    WHERE (
        $1::text = ''
        OR EXISTS (
            SELECT 1
            FROM company_news cn
            WHERE cn.news_id = n.id
              AND cn.company_id = $1::uuid
        )
    )
    ORDER BY COALESCE(n.published_at, n.created_at) DESC, n.id
    LIMIT $2 OFFSET $3
`
	rows, err := r.db.Query(ctx, q, companyID, limit, offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]News, 0)
	for rows.Next() {
		var x News
		if err := rows.Scan(&x.ID, &x.Title, &x.Summary, &x.URL, &x.SourceName, &x.PublishedAt); err != nil {
			return nil, err
		}
		items = append(items, x)
	}
	return items, rows.Err()
}
func (r *Repository) GetByID(ctx context.Context, id string) (News, error) {
	if _, err := uuid.Parse(id); err != nil {
		return News{}, ErrNotFound
	}
	var x News
	err := r.db.QueryRow(ctx, `SELECT n.id::text,n.title,n.summary,n.url,COALESCE(s.name,''),COALESCE(n.published_at,n.created_at) FROM news n LEFT JOIN sources s ON s.id=n.source_id WHERE n.id=$1`, id).Scan(&x.ID, &x.Title, &x.Summary, &x.URL, &x.SourceName, &x.PublishedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return News{}, ErrNotFound
	}
	return x, err
}
