package main

import (
	"context"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"syscall"
	"time"

	"hackathon-backend/internal/config"
	apphttp "hackathon-backend/internal/http"
	"hackathon-backend/internal/news"
	"hackathon-backend/internal/storage"
	"hackathon-backend/migrations"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		slog.Error("invalid configuration", "error", err)
		os.Exit(1)
	}
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: parseLevel(cfg.LogLevel)}))

	if err := run(cfg, logger); err != nil {
		logger.Error("fatal", "error", err)
		os.Exit(1)
	}
}

func run(cfg config.Config, logger *slog.Logger) error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	db, err := storage.NewPostgres(ctx, cfg.DatabaseURL)
	if err != nil {
		logger.Error("database connection failed", "error", err)
		return err
	}
	defer db.Close()

	if err := storage.Migrate(ctx, db, migrations.FS, logger); err != nil {
		logger.Error("migrations failed", "error", err)
		return err
	}

	newsRepo := news.NewRepository(db)
	if err := newsRepo.Deduplicate(ctx); err != nil {
		logger.Error("deduplicate failed", "error", err)
		return err
	}
	if err := news.LoadSnapshotIfEmpty(ctx, newsRepo, cfg.NewsSnapshotPath, logger); err != nil {
		// Снимок — вспомогательный источник; его ошибка не мешает старту.
		logger.Warn("news snapshot load failed", "path", cfg.NewsSnapshotPath, "error", err)
	}

	collectors := []news.Collector{news.NewAlfaCollector()}
	for _, f := range cfg.NewsFeeds {
		collectors = append(collectors, news.NewRSSCollector(f.Name, f.URL))
	}
	importer := news.NewImporter(newsRepo, logger, collectors...)
	go importer.Run(ctx, cfg.NewsImportInterval, cfg.NewsImportOnStart)
	// Run the heavy parser independently: RSS articles reach the DB immediately.
	rbcImporter := news.NewImporter(newsRepo, logger, news.NewRBCCollector())
	go rbcImporter.Run(ctx, cfg.NewsImportInterval, cfg.NewsImportOnStart)

	allowCIDRs, err := news.ParseCIDRList(cfg.FetchAllowCIDRs)
	if err != nil {
		logger.Error("invalid FETCH_ALLOW_CIDRS", "error", err)
		return err
	}

	aiURL, _ := url.Parse(cfg.AIURL) // проверен в config.Load
	router := apphttp.NewRouter(db, logger, apphttp.Options{
		AIURL:              aiURL,
		NewsService:        news.NewService(newsRepo, news.NewPageFetcher(allowCIDRs...)),
		Importer:           news.NewImporter(newsRepo, logger, append(collectors, news.NewRBCCollector())...),
		RateLimitPerMinute: cfg.RateLimitPerMinute,
	})
	server := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           router,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		IdleTimeout:       120 * time.Second,
	}

	go func() {
		logger.Info("server starting", "port", cfg.Port, "ai_url", cfg.AIURL, "feeds", len(cfg.NewsFeeds),
			"import_interval", cfg.NewsImportInterval.String())
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("server failed", "error", err)
			stop()
		}
	}()

	<-ctx.Done()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), time.Duration(cfg.ShutdownTimeoutSeconds)*time.Second)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Error("server shutdown failed", "error", err)
	}
	return nil
}

func parseLevel(s string) slog.Level {
	switch s {
	case "debug":
		return slog.LevelDebug
	case "warn", "warning":
		return slog.LevelWarn
	case "error":
		return slog.LevelError
	}
	return slog.LevelInfo
}
