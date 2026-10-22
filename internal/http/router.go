package http

import (
	"github.com/jackc/pgx/v5/pgxpool"
	"hackathon-backend/internal/analysis"
	"hackathon-backend/internal/company"
	"hackathon-backend/internal/knowledge"
	"hackathon-backend/internal/news"
	"hackathon-backend/internal/response"
	"log/slog"
	"net/http"
)

func NewRouter(db *pgxpool.Pool, logger *slog.Logger) http.Handler {
	mux := http.NewServeMux()
	cr := company.NewRepository(db)
	ch := company.NewHandler(company.NewService(cr))
	nr := news.NewRepository(db)
	nh := news.NewHandler(news.NewService(nr))
	kr := knowledge.NewRepository(db)
	kh := knowledge.NewHandler(knowledge.NewService(kr))
	ar := analysis.NewRepository(db)
	ah := analysis.NewHandler(analysis.NewService(ar, db))
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		response.WriteJSON(w, 200, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /ready", readyHandler(db))
	mux.HandleFunc("GET /api/v1/companies", ch.List)
	mux.HandleFunc("GET /api/v1/companies/{id}", ch.GetByID)
	mux.HandleFunc("GET /api/v1/companies/{id}/feed", ch.Feed)
	mux.HandleFunc("GET /api/v1/news", nh.List)
	mux.HandleFunc("GET /api/v1/news/{id}", nh.GetByID)
	mux.HandleFunc("GET /api/v1/knowledge", kh.List)
	mux.HandleFunc("POST /api/v1/companies/{id}/analyses", ah.Create)
	mux.HandleFunc("GET /api/v1/analyses/{id}", ah.GetByID)
	return requestIDMiddleware(loggingMiddleware(logger, mux))
}
func readyHandler(db *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if err := db.Ping(r.Context()); err != nil {
			response.WriteJSON(w, 503, map[string]string{"status": "not_ready"})
			return
		}
		response.WriteJSON(w, 200, map[string]string{"status": "ready"})
	}
}
