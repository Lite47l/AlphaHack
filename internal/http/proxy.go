package http

import (
	"context"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"time"

	"hackathon-backend/internal/response"
)

// aiPrefixes — префиксы API, которые обслуживает AI-сервис.
var aiPrefixes = []string{
	"/api/v1/companies",
	"/api/v1/insights",
	"/api/v1/relevance",
	"/api/v1/bank",
	"/api/v1/system",
	"/api/v1/metrics",
}

const maxProxyBodyBytes = 1 << 20

// newAIProxy проксирует запрос в AI-сервис без изменения пути и query.
// Заголовки (в т. ч. X-Request-Id, X-Client-Id, X-User-Role) и тело передаются как есть.
func newAIProxy(target *url.URL, logger *slog.Logger) http.Handler {
	transport := &http.Transport{
		Proxy: nil,
		DialContext: (&net.Dialer{
			Timeout:   5 * time.Second,
			KeepAlive: 30 * time.Second,
		}).DialContext,
		MaxIdleConns:          50,
		MaxIdleConnsPerHost:   50,
		IdleConnTimeout:       90 * time.Second,
		ResponseHeaderTimeout: 3 * time.Minute, // чат/инсайт могут ждать LLM
	}
	rp := &httputil.ReverseProxy{
		Rewrite: func(pr *httputil.ProxyRequest) {
			pr.SetURL(target)
			pr.SetXForwarded()
		},
		Transport:     transport,
		FlushInterval: -1,
		ModifyResponse: func(resp *http.Response) error {
			// Эти заголовки уже выставлены шлюзом — не дублируем.
			for _, h := range []string{
				"X-Request-Id", "X-Response-Time", "X-Content-Type-Options",
				"X-Frame-Options", "Referrer-Policy", "Content-Security-Policy",
			} {
				resp.Header.Del(h)
			}
			return nil
		},
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			if errors.Is(err, context.Canceled) && r.Context().Err() != nil {
				return // клиент ушёл
			}
			logger.Warn("ai proxy error",
				"request_id", r.Context().Value(requestIDKey{}),
				"method", r.Method,
				"path", r.URL.Path,
				"error", err,
			)
			var tooLarge *http.MaxBytesError
			if errors.As(err, &tooLarge) {
				response.WriteError(w, http.StatusRequestEntityTooLarge, "тело запроса слишком большое")
				return
			}
			response.WriteError(w, http.StatusBadGateway, "AI-сервис недоступен")
		},
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Body != nil {
			r.Body = http.MaxBytesReader(w, r.Body, maxProxyBodyBytes)
		}
		rp.ServeHTTP(w, r)
	})
}
