package http

import (
	"context"
	"log/slog"
	"net/http"
	"runtime/debug"
	"strings"
	"time"

	"github.com/google/uuid"
)

type requestIDKey struct{}
type statusWriter struct {
	http.ResponseWriter
	status int
	start  time.Time
}

func (w *statusWriter) WriteHeader(code int) {
	if w.status != 0 {
		return
	}
	w.status = code

	if !w.start.IsZero() {
		w.Header().Set("X-Response-Time",
			time.Since(w.start).String(),
		)
	}

	w.ResponseWriter.WriteHeader(code)
}

func (w *statusWriter) Write(b []byte) (int, error) {
	if w.status == 0 {
		w.WriteHeader(http.StatusOK)
	}

	return w.ResponseWriter.Write(b)
}

// Unwrap даёт http.ResponseController (и reverse proxy) доступ к Flush.
func (w *statusWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }

func requestIDMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := strings.TrimSpace(r.Header.Get("X-Request-Id"))

		if id == "" || len(id) > 100 ||
			strings.ContainsAny(id, "\r\n") {
			id = uuid.NewString()
		}

		w.Header().Set("X-Request-Id", id)
		// Нормализованный ID пробрасывается дальше (в т. ч. в AI-сервис через прокси).
		r.Header.Set("X-Request-Id", id)

		ctx := context.WithValue(r.Context(), requestIDKey{}, id)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func loggingMiddleware(
	logger *slog.Logger,
	next http.Handler,
) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()

		sw := &statusWriter{
			ResponseWriter: w,
			start:          start,
		}

		next.ServeHTTP(sw, r)

		status := sw.status
		if status == 0 {
			status = http.StatusOK
		}

		logger.Info(
			"http request",
			"request_id", r.Context().Value(requestIDKey{}),
			"method", r.Method,
			"path", r.URL.Path,
			"status", status,
			"duration_ms", time.Since(start).Milliseconds(),
		)
	})
}

func recoveryMiddleware(
	logger *slog.Logger,
	next http.Handler,
) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if recovered := recover(); recovered != nil {
				logger.Error(
					"panic recovered",
					"request_id", r.Context().Value(requestIDKey{}),
					"method", r.Method,
					"path", r.URL.Path,
					"panic", recovered,
					"stack", string(debug.Stack()),
				)

				w.Header().Set(
					"Content-Type",
					"application/json; charset=utf-8",
				)
				w.WriteHeader(http.StatusInternalServerError)
				_, _ = w.Write(
					[]byte(`{"error":"internal server error"}`),
				)
			}
		}()

		next.ServeHTTP(w, r)
	})
}

func securityHeadersMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set(
			"Content-Security-Policy",
			"default-src 'none'; frame-ancestors 'none'",
		)

		next.ServeHTTP(w, r)
	})
}
