package http

import (
	"hackathon-backend/internal/analysis"
	"hackathon-backend/internal/company"
	"log/slog"
	"net/http"
	"net/url"
	"os"

	"hackathon-backend/internal/knowledge"
	"hackathon-backend/internal/news"
	"hackathon-backend/internal/response"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Options — зависимости шлюза.
type Options struct {
	AIURL              *url.URL
	NewsService        *news.Service
	Importer           *news.Importer
	RateLimitPerMinute int
}

func NewRouter(db *pgxpool.Pool, logger *slog.Logger, opts Options) http.Handler {
	mux := http.NewServeMux()

	nh := news.NewHandler(opts.NewsService)
	kh := knowledge.NewHandler(knowledge.NewService(knowledge.NewRepository(db)))

	insightsLimit := newRateLimiter(opts.RateLimitPerMinute)
	chatLimit := newRateLimiter(opts.RateLimitPerMinute)
	newsLimit := newRateLimiter(opts.RateLimitPerMinute)

	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		response.WriteJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /ready", readyHandler(db))

	mux.HandleFunc("GET /api/v1/news", nh.List)
	mux.HandleFunc("GET /api/v1/news/{id}", nh.GetByID)
	mux.Handle("POST /api/v1/news", newsLimit.middleware(http.HandlerFunc(nh.Create)))
	if opts.Importer != nil {
		mux.HandleFunc("POST /api/v1/news/import", nh.Import(opts.Importer))
	}
	mux.HandleFunc("GET /api/v1/knowledge", kh.List)
	pdfDir := os.Getenv("KNOWLEDGE_PDF_DIR")
	if pdfDir == "" {
		pdfDir = "/app/data/knowledge"
	}
	ks := knowledge.NewService(knowledge.NewRepository(db))
	mux.HandleFunc("POST /api/v1/knowledge/import", kh.ImportPDF)
	mux.HandleFunc("POST /api/v1/knowledge/collect", kh.CollectLocal(knowledge.NewLocalPDFCollector(ks, pdfDir)))
	ah := analysis.NewHandler(analysis.NewService(analysis.NewRepository(db), db))
	mux.HandleFunc("POST /api/v1/companies/{id}/analyses", ah.Create)
	mux.HandleFunc("GET /api/v1/analyses/{id}", ah.GetByID)
	// Legacy Go contract remains available alongside the AI contract.
	ch := company.NewHandler(company.NewService(company.NewRepository(db)))
	mux.HandleFunc("GET /api/v1/legacy/companies", ch.List)
	mux.HandleFunc("GET /api/v1/legacy/companies/{id}", ch.GetByID)
	mux.HandleFunc("GET /api/v1/legacy/companies/{id}/feed", ch.Feed)

	ai := newAIProxy(opts.AIURL, logger)
	for _, prefix := range aiPrefixes {
		mux.Handle(prefix, ai)
		mux.Handle(prefix+"/", ai)
	}
	mux.Handle("POST /api/v1/insights", insightsLimit.middleware(ai))
	mux.Handle("POST /api/v1/insights/{id}/chat", chatLimit.middleware(ai))

	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		response.WriteError(w, http.StatusNotFound, "not found")
	})

	var handler http.Handler = mux

	handler = recoveryMiddleware(logger, handler)
	handler = loggingMiddleware(logger, handler)
	handler = requestIDMiddleware(handler)
	handler = securityHeadersMiddleware(handler)

	return handler
}

func readyHandler(db *pgxpool.Pool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if db == nil || db.Ping(r.Context()) != nil {
			response.WriteJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "not_ready"})
			return
		}
		response.WriteJSON(w, http.StatusOK, map[string]string{"status": "ready"})
	}
}
