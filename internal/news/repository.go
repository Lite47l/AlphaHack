package news

import (
	"context"
	"errors"
	"net/url"
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

const newsColumns = `
	n.id::text,
	n.title,
	n.summary,
	n.content,
	CASE WHEN n.url LIKE 'user-news:%' THEN '' ELSE n.url END,
	COALESCE(s.name, ''),
	COALESCE(n.published_at, n.created_at),
	n.fetched_at,
	n.origin`

func scanNews(row pgx.Row) (News, error) {
	var x News
	err := row.Scan(&x.ID, &x.Title, &x.Summary, &x.Content, &x.URL, &x.SourceName, &x.PublishedAt, &x.FetchedAt, &x.Origin)
	return x, err
}

func (r *Repository) List(ctx context.Context, limit, offset int) ([]News, error) {
	rows, err := r.db.Query(ctx, `
		SELECT `+newsColumns+`
		FROM news n
		LEFT JOIN sources s ON s.id = n.source_id
		ORDER BY COALESCE(n.published_at, n.created_at) DESC, n.id
		LIMIT $1 OFFSET $2`, limit, offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]News, 0)
	for rows.Next() {
		x, err := scanNews(rows)
		if err != nil {
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
	x, err := scanNews(r.db.QueryRow(ctx, `
		SELECT `+newsColumns+`
		FROM news n LEFT JOIN sources s ON s.id = n.source_id
		WHERE n.id = $1`, id))
	if errors.Is(err, pgx.ErrNoRows) {
		return News{}, ErrNotFound
	}
	return x, err
}

// GetByURL ищет новость по уже нормализованному URL.
func (r *Repository) GetByURL(ctx context.Context, normalizedURL string) (News, error) {
	x, err := scanNews(r.db.QueryRow(ctx, `
		SELECT `+newsColumns+`
		FROM news n LEFT JOIN sources s ON s.id = n.source_id
		WHERE n.url = $1`, normalizedURL))
	if errors.Is(err, pgx.ErrNoRows) {
		return News{}, ErrNotFound
	}
	return x, err
}

// IsEmpty сообщает, пуста ли таблица news.
func (r *Repository) IsEmpty(ctx context.Context) (bool, error) {
	var exists bool
	err := r.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM news)`).Scan(&exists)
	return !exists, err
}

type sourceIDs struct {
	tx    pgx.Tx
	cache map[string]string
}

func (s *sourceIDs) get(ctx context.Context, name, baseURL string) (string, error) {
	if id, ok := s.cache[name]; ok {
		return id, nil
	}
	var id string
	err := s.tx.QueryRow(ctx, `
		INSERT INTO sources (name, base_url)
		VALUES ($1, $2)
		ON CONFLICT (name) DO UPDATE
		SET base_url = CASE WHEN sources.base_url = '' THEN EXCLUDED.base_url ELSE sources.base_url END
		RETURNING id::text`, name, baseURL).Scan(&id)
	if err != nil {
		return "", err
	}
	s.cache[name] = id
	return id, nil
}

// SaveCollected сохраняет новости с дедупликацией по нормализованному URL.
// Для уже существующей записи без полного текста дописывается content.
// Возвращает число вставленных записей.
func (r *Repository) SaveCollected(ctx context.Context, items []News, origin string) (int, error) {
	tx, err := r.db.Begin(ctx)
	if err != nil {
		return 0, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	sources := &sourceIDs{tx: tx, cache: map[string]string{}}
	inserted := 0
	for _, item := range items {
		link := NormalizeURL(item.URL)
		title := strings.TrimSpace(item.Title)
		if link == "" || title == "" {
			continue
		}
		sourceName := strings.TrimSpace(item.SourceName)
		if sourceName == "" {
			sourceName = hostOf(link)
		}
		sourceID, err := sources.get(ctx, sourceName, sourceBaseURL(link))
		if err != nil {
			return 0, err
		}
		var publishedAt any
		if !item.PublishedAt.IsZero() {
			publishedAt = item.PublishedAt
		}
		var isInsert bool
		err = tx.QueryRow(ctx, `
			INSERT INTO news (source_id, title, summary, content, url, published_at, origin, fetched_at)
			VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, now())
			ON CONFLICT (url) DO UPDATE
			SET content = EXCLUDED.content
			WHERE news.content = '' AND EXCLUDED.content <> ''
			RETURNING (xmax = 0)`,
			sourceID, title, item.Summary, item.Content, link, publishedAt, origin,
		).Scan(&isInsert)
		if errors.Is(err, pgx.ErrNoRows) {
			continue // дубликат без изменений
		}
		if err != nil {
			return 0, err
		}
		if isInsert {
			inserted++
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, err
	}
	return inserted, nil
}

// InsertUser сохраняет пользовательскую новость. Если URL уже существует
// (гонка параллельных запросов), возвращает существующую запись и created=false.
func (r *Repository) InsertUser(ctx context.Context, item News, storedURL string) (News, bool, error) {
	tx, err := r.db.Begin(ctx)
	if err != nil {
		return News{}, false, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	sources := &sourceIDs{tx: tx, cache: map[string]string{}}
	baseURL := ""
	if !strings.HasPrefix(storedURL, userURLPrefix) {
		baseURL = sourceBaseURL(storedURL)
	}
	sourceID, err := sources.get(ctx, item.SourceName, baseURL)
	if err != nil {
		return News{}, false, err
	}
	var id string
	err = tx.QueryRow(ctx, `
		INSERT INTO news (source_id, title, summary, content, url, published_at, origin, fetched_at)
		VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, now())
		ON CONFLICT (url) DO NOTHING
		RETURNING id::text`,
		sourceID, item.Title, item.Summary, item.Content, storedURL, item.PublishedAt, OriginUser,
	).Scan(&id)
	created := true
	if errors.Is(err, pgx.ErrNoRows) {
		created = false
	} else if err != nil {
		return News{}, false, err
	}
	if err := tx.Commit(ctx); err != nil {
		return News{}, false, err
	}
	if !created {
		existing, err := r.GetByURL(ctx, storedURL)
		return existing, false, err
	}
	saved, err := r.GetByID(ctx, id)
	return saved, true, err
}

// Deduplicate объединяет записи с одинаковым нормализованным URL (выполняется при старте).
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
			content,
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
		Content        string
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
			&n.Content,
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

	// dedupKey — нормализованный URL; служебные URL (user-news:...) не нормализуются.
	dedupKey := func(raw string) string {
		if key := NormalizeURL(raw); key != "" {
			return key
		}
		return raw
	}

	groups := make(map[string][]newsRecord)
	for _, n := range records {
		key := dedupKey(n.URL)
		if key == "" {
			continue
		}
		groups[key] = append(groups[key], n)
	}

	for key, group := range groups {
		if len(group) == 1 && group[0].URL == key {
			continue
		}
		sort.Slice(group, func(i, j int) bool {
			score := func(n newsRecord) int {
				s := 0
				if strings.TrimSpace(n.Title) != "" {
					s++
				}
				if strings.TrimSpace(n.Summary) != "" {
					s++
				}
				if strings.TrimSpace(n.Content) != "" {
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
		mergedContent := canonical.Content
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
			if strings.TrimSpace(mergedContent) == "" {
				mergedContent = duplicate.Content
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
				content = $5,
				published_at = $6,
				url = $7
			WHERE id = $1::uuid
		`,
			canonical.ID,
			mergedSourceID,
			mergedTitle,
			mergedSummary,
			mergedContent,
			mergedPublishedAt,
			key,
		)
		if err != nil {
			return err
		}
	}

	return tx.Commit(ctx)
}

func hostOf(rawURL string) string {
	u, err := url.Parse(rawURL)
	if err != nil {
		return ""
	}
	return strings.TrimPrefix(strings.ToLower(u.Hostname()), "www.")
}

func sourceBaseURL(rawURL string) string {
	u, err := url.Parse(rawURL)
	if err != nil || u.Host == "" {
		return ""
	}
	return u.Scheme + "://" + u.Host
}
