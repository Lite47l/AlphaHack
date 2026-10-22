package news

import (
	"context"
	"errors"
	"sort"
	"strings"
	"time"

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

func (r *Repository) Deduplicate(ctx context.Context) error {
	tx, err := r.db.Begin(ctx)
	if err != nil {
		return err
	}
	defer func() {
		_ = tx.Rollback(ctx)
	}()

	if _, err := tx.Exec(ctx, `LOCK TABLE news IN SHARE ROW EXCLUSIVE MODE`); err != nil {
		return err
	}

	rows, err := tx.Query(ctx, `
		SELECT
			id::text,
			COALESCE(source_id::text, ''),
			title,
			summary,
			url,
			published_at IS NOT NULL,
			COALESCE(published_at, created_at),
			created_at
		FROM news
		ORDER BY created_at, id
		FOR UPDATE
	`)
	if err != nil {
		return err
	}

	type newsRecord struct {
		ID             string
		SourceID       string
		Title          string
		Summary        string
		URL            string
		HasPublishedAt bool
		PublishedAt    time.Time
		CreatedAt      time.Time
	}

	var records []newsRecord

	for rows.Next() {
		var n newsRecord
		if err := rows.Scan(
			&n.ID,
			&n.SourceID,
			&n.Title,
			&n.Summary,
			&n.URL,
			&n.HasPublishedAt,
			&n.PublishedAt,
			&n.CreatedAt,
		); err != nil {
			rows.Close()
			return err
		}
		records = append(records, n)
	}

	if err := rows.Err(); err != nil {
		rows.Close()
		return err
	}
	rows.Close()

	groups := make(map[string][]newsRecord)
	for _, n := range records {
		key := NormalizeURL(n.URL)
		if key == "" {
			return errors.New("cannot deduplicate news with empty URL")
		}
		groups[key] = append(groups[key], n)
	}

	for _, group := range groups {
		sort.Slice(group, func(i, j int) bool {
			score := func(n newsRecord) int {
				s := 0
				if strings.TrimSpace(n.Title) != "" {
					s++
				}
				if strings.TrimSpace(n.Summary) != "" {
					s++
				}
				if n.SourceID != "" {
					s++
				}
				if n.HasPublishedAt {
					s++
				}
				return s
			}

			si, sj := score(group[i]), score(group[j])
			if si != sj {
				return si > sj
			}
			if !group[i].CreatedAt.Equal(group[j].CreatedAt) {
				return group[i].CreatedAt.Before(group[j].CreatedAt)
			}
			return group[i].ID < group[j].ID
		})

		canonical := group[0]
		mergedSourceID := canonical.SourceID
		mergedTitle := canonical.Title
		mergedSummary := canonical.Summary
		var mergedPublishedAt any

		if canonical.HasPublishedAt {
			mergedPublishedAt = canonical.PublishedAt
		}

		for _, duplicate := range group[1:] {
			if mergedSourceID == "" {
				mergedSourceID = duplicate.SourceID
			}
			if strings.TrimSpace(mergedTitle) == "" {
				mergedTitle = duplicate.Title
			}
			if strings.TrimSpace(mergedSummary) == "" {
				mergedSummary = duplicate.Summary
			}
			if mergedPublishedAt == nil && duplicate.HasPublishedAt {
				mergedPublishedAt = duplicate.PublishedAt
			}

			_, err := tx.Exec(ctx, `
				INSERT INTO company_news (company_id, news_id, relevance_score)
				SELECT company_id, $1::uuid, relevance_score
				FROM company_news
				WHERE news_id = $2::uuid
				ON CONFLICT (company_id, news_id) DO UPDATE
				SET relevance_score = COALESCE(
					company_news.relevance_score,
					EXCLUDED.relevance_score
				)
			`, canonical.ID, duplicate.ID)
			if err != nil {
				return err
			}

			if _, err := tx.Exec(ctx,
				`DELETE FROM news WHERE id = $1::uuid`,
				duplicate.ID,
			); err != nil {
				return err
			}
		}

		_, err := tx.Exec(ctx, `
			UPDATE news
			SET
				source_id = NULLIF($2, '')::uuid,
				title = $3,
				summary = $4,
				published_at = $5,
				url = $6
			WHERE id = $1::uuid
		`,
			canonical.ID,
			mergedSourceID,
			mergedTitle,
			mergedSummary,
			mergedPublishedAt,
			NormalizeURL(canonical.URL),
		)
		if err != nil {
			return err
		}
	}

	return tx.Commit(ctx)
}
