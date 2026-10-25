package news

import (
	"net/url"
	"strings"
)

func NormalizeURL(raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return ""
	}

	u, err := url.Parse(raw)
	if err != nil || u.Host == "" {
		return ""
	}

	u.Scheme = strings.ToLower(u.Scheme)
	u.Host = strings.ToLower(u.Host)
	u.Fragment = ""

	query := u.Query()
	for key := range query {
		lower := strings.ToLower(key)
		if strings.HasPrefix(lower, "utm_") ||
			strings.HasPrefix(lower, "utm-") ||
			lower == "fbclid" ||
			lower == "gclid" ||
			lower == "yclid" {
			query.Del(key)
		}
	}
	u.RawQuery = query.Encode()

	if u.Path != "/" {
		u.Path = strings.TrimRight(u.Path, "/")
		if u.Path == "" {
			u.Path = "/"
		}
	}

	return u.String()
}
