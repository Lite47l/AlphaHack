package knowledge

import (
    "context"
    "errors"
    "time"

    "github.com/jackc/pgx/v5"
    "github.com/jackc/pgx/v5/pgxpool"
)

type Repository struct{ db *pgxpool.Pool }
func NewRepository(db *pgxpool.Pool) *Repository { return &Repository{db: db} }

func (r *Repository) List(ctx context.Context, limit, offset int) ([]Document, error) {
    rows, err := r.db.Query(ctx, `SELECT id::text,title,institution,document_url,COALESCE(published_at,created_at)
        FROM knowledge_documents ORDER BY COALESCE(published_at,created_at) DESC,id LIMIT $1 OFFSET $2`, limit, offset)
    if err != nil { return nil, err }
    defer rows.Close()
    items := make([]Document, 0)
    for rows.Next() {
        var x Document
        if err := rows.Scan(&x.ID,&x.Title,&x.Institution,&x.DocumentURL,&x.PublishedAt); err != nil { return nil, err }
        items = append(items,x)
    }
    return items, rows.Err()
}

func (r *Repository) SavePDF(ctx context.Context, title, institution, documentURL string, publishedAt *time.Time, fileHash string, pages []PDFPage) (string,bool,error) {
    tx, err := r.db.Begin(ctx)
    if err != nil { return "",false,err }
    defer tx.Rollback(ctx)
    var id string
    err = tx.QueryRow(ctx, `INSERT INTO knowledge_documents(title,institution,document_url,published_at,file_hash)
        VALUES($1,$2,$3,$4,$5)
        ON CONFLICT (file_hash) WHERE file_hash IS NOT NULL DO NOTHING
        RETURNING id::text`, title,institution,documentURL,publishedAt,fileHash).Scan(&id)
    if err != nil {
        if errors.Is(err,pgx.ErrNoRows) {
            if e := tx.QueryRow(ctx,`SELECT id::text FROM knowledge_documents WHERE file_hash=$1`,fileHash).Scan(&id); e != nil { return "",false,e }
            return id,false,nil
        }
        return "",false,err
    }
    for _, page := range pages {
        for _, chunk := range splitText(page.Number,page.Text,1500) {
            if _,err := tx.Exec(ctx,`INSERT INTO knowledge_chunks(document_id,page_number,chunk_index,content)
                VALUES($1,$2,$3,$4) ON CONFLICT(document_id,page_number,chunk_index) DO NOTHING`,
                id,chunk.PageNumber,chunk.Index,chunk.Content); err != nil { return "",false,err }
        }
    }
    if err := tx.Commit(ctx); err != nil { return "",false,err }
    return id,true,nil
}

type SearchResult struct {
    DocumentID string `json:"document_id"`
    Title string `json:"title"`
    PageNumber int `json:"page_number"`
    Content string `json:"content"`
}
func (r *Repository) Search(ctx context.Context, query string, limit int) ([]SearchResult,error) {
    if limit < 1 || limit > 20 { limit = 5 }
    rows,err := r.db.Query(ctx,`SELECT d.id::text,d.title,c.page_number,c.content
        FROM knowledge_chunks c JOIN knowledge_documents d ON d.id=c.document_id
        WHERE c.content ILIKE '%' || $1 || '%' ORDER BY COALESCE(d.published_at,d.created_at) DESC LIMIT $2`,query,limit)
    if err != nil { return nil,err }; defer rows.Close()
    out:=make([]SearchResult,0)
    for rows.Next(){ var x SearchResult; if err:=rows.Scan(&x.DocumentID,&x.Title,&x.PageNumber,&x.Content);err!=nil{return nil,err};out=append(out,x)}
    return out,rows.Err()
}
