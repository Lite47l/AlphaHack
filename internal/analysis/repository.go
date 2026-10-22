package analysis

import (
	"context"
	"encoding/json"
	"errors"
	_ "github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var ErrNotFound = errors.New("analysis not found")

type Repository struct{ db *pgxpool.Pool }

func NewRepository(db *pgxpool.Pool) *Repository { return &Repository{db: db} }
func (r *Repository) Create(ctx context.Context, companyID string) (Analysis, error) {
	var a Analysis
	err := r.db.QueryRow(ctx, `INSERT INTO analyses(company_id,status) VALUES($1,'queued') RETURNING id::text,company_id::text,status,created_at`, companyID).Scan(&a.ID, &a.CompanyID, &a.Status, &a.CreatedAt)
	return a, err
}
func (r *Repository) GetByID(ctx context.Context, id string) (Analysis, error) {
	var a Analysis
	err := r.db.QueryRow(ctx, `SELECT id::text,company_id::text,status,error,created_at FROM analyses WHERE id=$1`, id).Scan(&a.ID, &a.CompanyID, &a.Status, &a.Error, &a.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return Analysis{}, ErrNotFound
	}
	if err != nil {
		return Analysis{}, err
	}
	var facts, bank, conclusions, risks, opps []byte
	err = r.db.QueryRow(ctx, `SELECT facts,bank_perspective,ai_conclusions,risks,opportunities FROM analysis_results WHERE analysis_id=$1`, id).Scan(&facts, &bank, &conclusions, &risks, &opps)
	if err == nil {
		res := Result{}
		_ = json.Unmarshal(facts, &res.Facts)
		_ = json.Unmarshal(bank, &res.BankPerspective)
		_ = json.Unmarshal(conclusions, &res.AIConclusions)
		_ = json.Unmarshal(risks, &res.Risks)
		_ = json.Unmarshal(opps, &res.Opportunities)
		rows, e := r.db.Query(ctx, `SELECT source_url FROM analysis_sources WHERE analysis_id=$1 ORDER BY source_url`, id)
		if e != nil {
			return Analysis{}, e
		}
		for rows.Next() {
			var u string
			if e = rows.Scan(&u); e != nil {
				rows.Close()
				return Analysis{}, e
			}
			res.SourceURLs = append(res.SourceURLs, u)
		}
		e = rows.Err()
		rows.Close()
		if e != nil {
			return Analysis{}, e
		}
		a.Result = &res
	} else if !errors.Is(err, pgx.ErrNoRows) {
		return Analysis{}, err
	}
	return a, nil
}
func (r *Repository) SaveResult(ctx context.Context, id string, result Result) error {
	tx, err := r.db.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	facts, _ := json.Marshal(result.Facts)
	bank, _ := json.Marshal(result.BankPerspective)
	conclusions, _ := json.Marshal(result.AIConclusions)
	risks, _ := json.Marshal(result.Risks)
	opps, _ := json.Marshal(result.Opportunities)
	_, err = tx.Exec(ctx, `INSERT INTO analysis_results(analysis_id,facts,bank_perspective,ai_conclusions,risks,opportunities) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(analysis_id) DO UPDATE SET facts=EXCLUDED.facts,bank_perspective=EXCLUDED.bank_perspective,ai_conclusions=EXCLUDED.ai_conclusions,risks=EXCLUDED.risks,opportunities=EXCLUDED.opportunities`, id, facts, bank, conclusions, risks, opps)
	if err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `DELETE FROM analysis_sources WHERE analysis_id=$1`, id); err != nil {
		return err
	}
	for _, u := range result.SourceURLs {
		if _, err = tx.Exec(ctx, `INSERT INTO analysis_sources(analysis_id,source_url) VALUES($1,$2) ON CONFLICT DO NOTHING`, id, u); err != nil {
			return err
		}
	}
	tag, err := tx.Exec(ctx, `UPDATE analyses SET status='completed',error='',updated_at=now() WHERE id=$1`, id)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return ErrNotFound
	}
	return tx.Commit(ctx)
}
