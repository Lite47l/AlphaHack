package news

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

// ErrForbiddenURL — адрес запрещён политикой SSRF (не http/https, приватный IP и т. п.).
var ErrForbiddenURL = errors.New("forbidden url")

const (
	maxPageBytes    = 2 << 20
	pageTimeout     = 10 * time.Second
	maxPageRedirect = 5
)

// Page — данные, извлечённые со страницы пользовательской новости.
type Page struct {
	FinalURL    string
	Title       string
	Description string
	Text        string
}

// PageFetcher загружает внешние страницы с защитой от SSRF: разрешены только
// http/https, каждый IP, к которому выполняется подключение (в том числе
// после редиректов), проверяется в DialContext.
type PageFetcher struct {
	client   *http.Client
	allow    func(netip.Addr) bool
	resolver *net.Resolver
}

// NewPageFetcher создаёт загрузчик. extraAllowed (FETCH_ALLOW_CIDRS) может разрешить
// только служебные диапазоны вроде 240.0.0.0/4 или 198.18.0.0/15 (fake-IP DNS у VPN/прокси);
// loopback/private/link-local/multicast/unspecified остаются запрещены всегда.
func NewPageFetcher(extraAllowed ...netip.Prefix) *PageFetcher {
	return newPageFetcher(func(a netip.Addr) bool {
		if IsPublicAddr(a) {
			return true
		}
		if isAlwaysBlocked(a) {
			return false
		}
		for _, p := range extraAllowed {
			if p.Contains(a.Unmap()) {
				return true
			}
		}
		return false
	})
}

func newPageFetcher(allow func(netip.Addr) bool) *PageFetcher {
	f := &PageFetcher{allow: allow, resolver: net.DefaultResolver}
	transport := &http.Transport{
		Proxy:                  nil, // прокси из окружения обошёл бы проверку IP
		DialContext:            f.dialContext,
		ForceAttemptHTTP2:      true,
		TLSHandshakeTimeout:    5 * time.Second,
		ResponseHeaderTimeout:  pageTimeout,
		MaxResponseHeaderBytes: 64 << 10,
		MaxIdleConns:           10,
		IdleConnTimeout:        30 * time.Second,
	}
	f.client = &http.Client{
		Timeout:   pageTimeout,
		Transport: transport,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) >= maxPageRedirect {
				return errors.New("too many redirects")
			}
			if err := checkURLScheme(req.URL); err != nil {
				return err
			}
			return nil
		},
	}
	return f
}

func checkURLScheme(u *url.URL) error {
	if (u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" || u.User != nil {
		return fmt.Errorf("%w: only http/https URLs are allowed", ErrForbiddenURL)
	}
	return nil
}

func (f *PageFetcher) dialContext(ctx context.Context, network, addr string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(addr)
	if err != nil {
		return nil, err
	}
	var addrs []netip.Addr
	if ip, err := netip.ParseAddr(host); err == nil {
		addrs = []netip.Addr{ip}
	} else {
		addrs, err = f.resolver.LookupNetIP(ctx, "ip", host)
		if err != nil {
			return nil, err
		}
	}
	if len(addrs) == 0 {
		return nil, fmt.Errorf("no addresses for %s", host)
	}
	// Если хоть один адрес приватный — отказываем целиком (защита от DNS-трюков).
	for _, a := range addrs {
		if !f.allow(a.Unmap()) {
			return nil, fmt.Errorf("%w: address %s is not public", ErrForbiddenURL, a)
		}
	}
	dialer := &net.Dialer{Timeout: 5 * time.Second}
	var lastErr error
	for _, a := range addrs {
		conn, err := dialer.DialContext(ctx, network, net.JoinHostPort(a.Unmap().String(), port))
		if err == nil {
			return conn, nil
		}
		lastErr = err
	}
	return nil, lastErr
}

var extraBlockedPrefixes = []netip.Prefix{
	netip.MustParsePrefix("192.0.0.0/24"),
	netip.MustParsePrefix("192.0.2.0/24"),
	netip.MustParsePrefix("198.18.0.0/15"),
	netip.MustParsePrefix("198.51.100.0/24"),
	netip.MustParsePrefix("203.0.113.0/24"),
	netip.MustParsePrefix("240.0.0.0/4"),
	netip.MustParsePrefix("64:ff9b::/96"), // NAT64
	netip.MustParsePrefix("2001:db8::/32"),
}

// IsPublicAddr — true, если адрес допустим для исходящих запросов
// (не loopback/private/link-local/multicast/unspecified/служебный).
func IsPublicAddr(a netip.Addr) bool {
	a = a.Unmap()
	if isAlwaysBlocked(a) {
		return false
	}
	for _, p := range extraBlockedPrefixes {
		if p.Contains(a) {
			return false
		}
	}
	return true
}

// isAlwaysBlocked — адреса, которые нельзя разрешить никакой настройкой.
func isAlwaysBlocked(a netip.Addr) bool {
	a = a.Unmap()
	return !a.IsValid() || a.IsLoopback() || a.IsPrivate() || a.IsLinkLocalUnicast() ||
		a.IsLinkLocalMulticast() || a.IsInterfaceLocalMulticast() || a.IsMulticast() ||
		a.IsUnspecified() || thisNetwork.Contains(a) || cgnat.Contains(a) || a == broadcast4
}

var (
	thisNetwork = netip.MustParsePrefix("0.0.0.0/8")
	cgnat       = netip.MustParsePrefix("100.64.0.0/10")
	broadcast4  = netip.MustParseAddr("255.255.255.255")
)

// ParseCIDRList разбирает список CIDR через запятую (FETCH_ALLOW_CIDRS).
func ParseCIDRList(raw string) ([]netip.Prefix, error) {
	var out []netip.Prefix
	for _, part := range strings.Split(raw, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		p, err := netip.ParsePrefix(part)
		if err != nil {
			return nil, err
		}
		out = append(out, p.Masked())
	}
	return out, nil
}

// Fetch загружает страницу (≤2 МБ, таймаут 10 с) и извлекает заголовок,
// og:description и текст абзацев.
func (f *PageFetcher) Fetch(ctx context.Context, rawURL string) (Page, error) {
	u, err := url.Parse(strings.TrimSpace(rawURL))
	if err != nil {
		return Page{}, fmt.Errorf("%w: invalid url", ErrForbiddenURL)
	}
	if err := checkURLScheme(u); err != nil {
		return Page{}, err
	}
	ctx, cancel := context.WithTimeout(ctx, pageTimeout)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return Page{}, err
	}
	req.Header.Set("User-Agent", browserUserAgent)
	req.Header.Set("Accept", "text/html,application/xhtml+xml;q=0.9,text/plain;q=0.8")
	req.Header.Set("Accept-Language", "ru-RU,ru;q=0.9,en;q=0.8")

	resp, err := f.client.Do(req)
	if err != nil {
		return Page{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return Page{}, fmt.Errorf("page returned HTTP %d", resp.StatusCode)
	}
	if resp.ContentLength > maxPageBytes {
		return Page{}, errors.New("page is too large")
	}
	ct := resp.Header.Get("Content-Type")
	lct := strings.ToLower(ct)
	if lct != "" && !strings.Contains(lct, "html") && !strings.HasPrefix(lct, "text/") {
		return Page{}, fmt.Errorf("unsupported content type %q", strings.Split(ct, ";")[0])
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxPageBytes))
	if err != nil {
		return Page{}, fmt.Errorf("read page: %w", err)
	}
	text := decodeHTMLBody(body, ct)

	page := Page{FinalURL: resp.Request.URL.String()}
	if strings.HasPrefix(lct, "text/plain") {
		page.Text = TruncateRunes(NormalizeText(text), maxContentRunes)
		return page, nil
	}
	page.Title, page.Description, page.Text = ExtractPage(text)
	return page, nil
}

var (
	reTitle     = regexp.MustCompile(`(?is)<title\b[^>]*>(.*?)</title\s*>`)
	reMetaTag   = regexp.MustCompile(`(?is)<meta\s[^>]*>`)
	reAttr      = regexp.MustCompile(`(?is)([a-zA-Z_:\-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))`)
	reParagraph = regexp.MustCompile(`(?is)<p\b[^>]*>(.*?)</p\s*>`)
)

// ExtractPage извлекает из HTML заголовок (<title>, затем og:title),
// описание (og:description, затем meta description) и текст абзацев <p>.
func ExtractPage(doc string) (title, description, text string) {
	for _, re := range reDropTags {
		doc = re.ReplaceAllString(doc, " ")
	}
	doc = reComment.ReplaceAllString(doc, " ")

	if m := reTitle.FindStringSubmatch(doc); m != nil {
		title = singleLine(CleanHTML(m[1]))
	}
	meta := map[string]string{}
	for _, tag := range reMetaTag.FindAllString(doc, -1) {
		attrs := map[string]string{}
		for _, a := range reAttr.FindAllStringSubmatch(tag, -1) {
			attrs[strings.ToLower(a[1])] = a[2] + a[3] + a[4]
		}
		key := strings.ToLower(attrs["property"])
		if key == "" {
			key = strings.ToLower(attrs["name"])
		}
		if key != "" && attrs["content"] != "" {
			if _, exists := meta[key]; !exists {
				meta[key] = attrs["content"]
			}
		}
	}
	if title == "" {
		title = singleLine(CleanHTML(meta["og:title"]))
	}
	description = CleanHTML(meta["og:description"])
	if description == "" {
		description = CleanHTML(meta["description"])
	}
	description = TruncateRunes(description, maxSummaryRunes)

	var paragraphs []string
	total := 0
	for _, m := range reParagraph.FindAllStringSubmatch(doc, -1) {
		p := singleLine(CleanHTML(m[1]))
		if utf8.RuneCountInString(p) < 40 {
			continue
		}
		paragraphs = append(paragraphs, p)
		total += utf8.RuneCountInString(p)
		if total > maxContentRunes {
			break
		}
	}
	text = TruncateRunes(strings.Join(paragraphs, "\n"), maxContentRunes)
	return title, description, text
}
