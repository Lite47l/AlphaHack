package news

import (
	"context"
	"errors"
	"net/http"
	"net/url"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
)

// pageFetcher — интерфейс загрузки страниц (подменяется в тестах).
type pageFetcher interface {
	Fetch(ctx context.Context, rawURL string) (Page, error)
}

type Service struct {
	repo    *Repository
	fetcher pageFetcher
}

func NewService(repo *Repository, fetcher *PageFetcher) *Service {
	s := &Service{repo: repo}
	if fetcher != nil {
		s.fetcher = fetcher
	}
	return s
}

func (s *Service) List(ctx context.Context, limit, offset int) ([]News, error) {
	if limit < 1 || limit > 100 {
		return nil, errors.New("limit must be between 1 and 100")
	}
	if offset < 0 {
		return nil, errors.New("offset must be >= 0")
	}
	return s.repo.List(ctx, limit, offset)
}

func (s *Service) GetByID(ctx context.Context, id string) (News, error) {
	if _, err := uuid.Parse(id); err != nil {
		return News{}, errors.New("invalid id: expected UUID")
	}
	return s.repo.GetByID(ctx, id)
}

const (
	maxUserTitleRunes = 500
	maxUserTextRunes  = 50000
)

// CreateUserNews добавляет пользовательскую новость. Возвращает created=false,
// если новость с таким URL уже есть.
func (s *Service) CreateUserNews(ctx context.Context, in CreateInput) (News, bool, error) {
	title := singleLine(in.Title)
	text := NormalizeText(in.Text)
	rawURL := strings.TrimSpace(in.URL)

	if text == "" && rawURL == "" {
		return News{}, false, &InputError{http.StatusBadRequest, "нужно передать text или url"}
	}
	if utf8.RuneCountInString(title) > maxUserTitleRunes {
		return News{}, false, &InputError{http.StatusBadRequest, "title слишком длинный (максимум 500 символов)"}
	}
	if utf8.RuneCountInString(text) > maxUserTextRunes {
		return News{}, false, &InputError{http.StatusBadRequest, "text слишком длинный (максимум 50000 символов)"}
	}

	storedURL := ""
	sourceName := UserSourceName
	if rawURL != "" {
		u, err := url.Parse(rawURL)
		if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" || u.User != nil {
			return News{}, false, &InputError{http.StatusBadRequest, "url должен быть http(s)-ссылкой"}
		}
		storedURL = NormalizeURL(rawURL)
		if storedURL == "" || len(storedURL) > 2048 {
			return News{}, false, &InputError{http.StatusBadRequest, "некорректный url"}
		}
		existing, err := s.repo.GetByURL(ctx, storedURL)
		if err == nil {
			return existing, false, nil
		}
		if !errors.Is(err, ErrNotFound) {
			return News{}, false, err
		}
		if host := hostOf(storedURL); host != "" {
			sourceName = host
		}
	}

	summary := ""
	if text == "" {
		if s.fetcher == nil {
			return News{}, false, &InputError{http.StatusUnprocessableEntity, "загрузка страниц недоступна, передайте text"}
		}
		page, err := s.fetcher.Fetch(ctx, rawURL)
		if errors.Is(err, ErrForbiddenURL) {
			return News{}, false, &InputError{http.StatusBadRequest, "адрес запрещён: разрешены только публичные http(s)-адреса"}
		}
		if err != nil {
			return News{}, false, &InputError{http.StatusUnprocessableEntity, "не удалось загрузить страницу по url"}
		}
		text = page.Text
		summary = page.Description
		if title == "" {
			title = page.Title
		}
		if text == "" && summary == "" {
			return News{}, false, &InputError{http.StatusUnprocessableEntity, "не удалось извлечь текст со страницы, передайте text"}
		}
	}

	if summary == "" {
		summary = TruncateRunes(text, 600)
	}
	content := text
	if content == summary {
		content = ""
	}
	if title == "" {
		firstLine, _, _ := strings.Cut(text+"\n"+summary, "\n")
		title = TruncateRunes(singleLine(firstLine), 120)
	}
	title = TruncateRunes(title, maxUserTitleRunes)

	if storedURL == "" {
		storedURL = userURLPrefix + uuid.NewString()
	}
	item := News{
		Title:       title,
		Summary:     TruncateRunes(summary, maxSummaryRunes),
		Content:     TruncateRunes(content, maxUserTextRunes),
		SourceName:  sourceName,
		PublishedAt: time.Now().UTC(),
		Origin:      OriginUser,
	}
	return s.repo.InsertUser(ctx, item, storedURL)
}
