package news

import (
	"bytes"
	"html"
	"io"
	"regexp"
	"strings"
	"unicode/utf8"
)

const (
	maxSummaryRunes = 4000
	maxContentRunes = 20000
)

var (
	reComment  = regexp.MustCompile(`(?s)<!--.*?-->`)
	reCDATA    = regexp.MustCompile(`(?s)<!\[CDATA\[(.*?)\]\]>`)
	reDropTags = []*regexp.Regexp{
		regexp.MustCompile(`(?is)<script\b.*?</script\s*>`),
		regexp.MustCompile(`(?is)<style\b.*?</style\s*>`),
		regexp.MustCompile(`(?is)<noscript\b.*?</noscript\s*>`),
		regexp.MustCompile(`(?is)<template\b.*?</template\s*>`),
		regexp.MustCompile(`(?is)<svg\b.*?</svg\s*>`),
		regexp.MustCompile(`(?is)<iframe\b.*?</iframe\s*>`),
		regexp.MustCompile(`(?is)<figure\b.*?</figure\s*>`),
	}
	reBlockTag = regexp.MustCompile(`(?i)<\s*/?\s*(br|p|div|li|ul|ol|h[1-6]|tr|table|blockquote|section|article|header|footer)\b[^>]*>`)
	reAnyTag   = regexp.MustCompile(`(?s)<[^>]*>`)
	reSpaces   = regexp.MustCompile(`[ \t\f\v\r]+`)
)

// CleanHTML превращает HTML-фрагмент в чистый текст: удаляет скрипты, стили,
// комментарии и теги, раскрывает HTML-сущности и нормализует пробелы.
// Абзацы разделяются переводом строки.
func CleanHTML(s string) string {
	if s == "" {
		return ""
	}
	s = reComment.ReplaceAllString(s, " ")
	s = reCDATA.ReplaceAllString(s, "$1")
	for _, re := range reDropTags {
		s = re.ReplaceAllString(s, " ")
	}
	s = reBlockTag.ReplaceAllString(s, "\n")
	s = reAnyTag.ReplaceAllString(s, " ")
	s = html.UnescapeString(s)
	return NormalizeText(s)
}

// NormalizeText нормализует пробелы, сохраняя разбиение на абзацы.
func NormalizeText(s string) string {
	s = strings.ToValidUTF8(s, "")
	s = strings.NewReplacer(
		"\u00a0", " ", "\u200b", "", "\u00ad", "", "\ufeff", "", "\u2028", "\n", "\u2029", "\n",
	).Replace(s)
	lines := strings.Split(s, "\n")
	out := lines[:0]
	for _, line := range lines {
		line = strings.TrimSpace(reSpaces.ReplaceAllString(line, " "))
		if line != "" {
			out = append(out, line)
		}
	}
	return strings.Join(out, "\n")
}

// singleLine схлопывает текст в одну строку (для заголовков).
func singleLine(s string) string {
	return strings.Join(strings.Fields(s), " ")
}

// TruncateRunes обрезает текст до n символов по границе слова и добавляет «…».
func TruncateRunes(s string, n int) string {
	if n <= 0 || utf8.RuneCountInString(s) <= n {
		return s
	}
	runes := []rune(s)
	cut := string(runes[:n])
	if i := strings.LastIndexAny(cut, " \n"); i > len(cut)/2 {
		cut = cut[:i]
	}
	return strings.TrimSpace(cut) + "…"
}

var utf8BOM = []byte{0xEF, 0xBB, 0xBF}

// isCP1251 сообщает, обозначает ли метка кодировки windows-1251.
func isCP1251(label string) bool {
	switch strings.ToLower(strings.TrimSpace(label)) {
	case "windows-1251", "cp1251", "x-cp1251", "win-1251":
		return true
	}
	return false
}

// xmlCharsetReader поддерживает UTF-8 и windows-1251 без внешних зависимостей.
func xmlCharsetReader(label string, input io.Reader) (io.Reader, error) {
	if isCP1251(label) {
		data, err := io.ReadAll(input)
		if err != nil {
			return nil, err
		}
		return strings.NewReader(decodeCP1251(data)), nil
	}
	// Остальные метки читаем как UTF-8 (некорректные байты потом отбрасываются).
	return input, nil
}

// cp1251High — символы windows-1251 в диапазоне 0x80–0xBF.
var cp1251High = [64]rune{
	0x0402, 0x0403, 0x201A, 0x0453, 0x201E, 0x2026, 0x2020, 0x2021, 0x20AC, 0x2030, 0x0409, 0x2039, 0x040A, 0x040C, 0x040B, 0x040F,
	0x0452, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014, 0xFFFD, 0x2122, 0x0459, 0x203A, 0x045A, 0x045C, 0x045B, 0x045F,
	0x00A0, 0x040E, 0x045E, 0x0408, 0x00A4, 0x0490, 0x00A6, 0x00A7, 0x0401, 0x00A9, 0x0404, 0x00AB, 0x00AC, 0x00AD, 0x00AE, 0x0407,
	0x00B0, 0x00B1, 0x0406, 0x0456, 0x0491, 0x00B5, 0x00B6, 0x00B7, 0x0451, 0x2116, 0x0454, 0x00BB, 0x0458, 0x0405, 0x0455, 0x0457,
}

func decodeCP1251(data []byte) string {
	var b strings.Builder
	b.Grow(len(data) * 2)
	for _, c := range data {
		switch {
		case c < 0x80:
			b.WriteByte(c)
		case c < 0xC0:
			b.WriteRune(cp1251High[c-0x80])
		default:
			b.WriteRune(rune(c-0xC0) + 0x0410)
		}
	}
	return b.String()
}

var reMetaCharset = regexp.MustCompile(`(?i)<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)`)

// decodeHTMLBody приводит тело HTML-страницы к UTF-8 по заголовку или <meta charset>.
func decodeHTMLBody(body []byte, contentType string) string {
	body = bytes.TrimPrefix(body, utf8BOM)
	charset := ""
	if i := strings.Index(strings.ToLower(contentType), "charset="); i >= 0 {
		charset = strings.Trim(contentType[i+len("charset="):], `"' ;`)
	}
	if charset == "" {
		head := body
		if len(head) > 4096 {
			head = head[:4096]
		}
		if m := reMetaCharset.FindSubmatch(head); m != nil {
			charset = string(m[1])
		}
	}
	if isCP1251(charset) {
		return decodeCP1251(body)
	}
	return strings.ToValidUTF8(string(body), "")
}
