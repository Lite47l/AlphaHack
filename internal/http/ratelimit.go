package http

import (
	"math"
	"net"
	"net/http"
	"net/netip"
	"strconv"
	"strings"
	"sync"
	"time"

	"hackathon-backend/internal/response"
)

// rateLimiter — token bucket в памяти по IP клиента.
type rateLimiter struct {
	mu        sync.Mutex
	buckets   map[string]*bucket
	rate      float64 // токенов в секунду
	burst     float64
	now       func() time.Time
	lastSweep time.Time
}

type bucket struct {
	tokens float64
	last   time.Time
}

func newRateLimiter(perMinute int) *rateLimiter {
	if perMinute < 1 {
		perMinute = 1
	}
	return &rateLimiter{
		buckets: make(map[string]*bucket),
		rate:    float64(perMinute) / 60,
		burst:   float64(perMinute),
		now:     time.Now,
	}
}

// allow списывает токен; при отказе возвращает время до появления следующего.
func (l *rateLimiter) allow(key string) (bool, time.Duration) {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := l.now()

	if now.Sub(l.lastSweep) > time.Minute {
		for k, b := range l.buckets {
			if now.Sub(b.last) > 10*time.Minute {
				delete(l.buckets, k)
			}
		}
		l.lastSweep = now
	}

	b, ok := l.buckets[key]
	if !ok {
		b = &bucket{tokens: l.burst, last: now}
		l.buckets[key] = b
	}
	b.tokens = math.Min(l.burst, b.tokens+now.Sub(b.last).Seconds()*l.rate)
	b.last = now
	if b.tokens >= 1 {
		b.tokens--
		return true, 0
	}
	wait := time.Duration((1 - b.tokens) / l.rate * float64(time.Second))
	return false, wait
}

func (l *rateLimiter) middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ok, wait := l.allow(clientIP(r))
		if !ok {
			secs := int(math.Ceil(wait.Seconds()))
			if secs < 1 {
				secs = 1
			}
			w.Header().Set("Retry-After", strconv.Itoa(secs))
			response.WriteError(w, http.StatusTooManyRequests, "слишком много запросов, попробуйте позже")
			return
		}
		next.ServeHTTP(w, r)
	})
}

// clientIP — IP клиента. Заголовкам X-Real-IP / X-Forwarded-For доверяем, только если
// непосредственный собеседник — адрес внутренней сети (nginx в docker-сети).
func clientIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	peer, err := netip.ParseAddr(host)
	if err != nil {
		return host
	}
	peer = peer.Unmap()
	if !(peer.IsPrivate() || peer.IsLoopback()) {
		return peer.String()
	}
	if v := strings.TrimSpace(r.Header.Get("X-Real-IP")); v != "" {
		if ip, err := netip.ParseAddr(v); err == nil {
			return ip.Unmap().String()
		}
	}
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		parts := strings.Split(xff, ",")
		// Последний элемент добавлен ближайшим доверенным прокси.
		if ip, err := netip.ParseAddr(strings.TrimSpace(parts[len(parts)-1])); err == nil {
			return ip.Unmap().String()
		}
	}
	return peer.String()
}
