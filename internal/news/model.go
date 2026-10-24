package news

import "time"

// Происхождение новости (поле origin).
const (
	OriginCollector = "collector"
	OriginSnapshot  = "snapshot"
	OriginUser      = "user"
)

// UserSourceName — источник для новостей, добавленных пользователем без URL.
const UserSourceName = "Добавлено пользователем"

// userURLPrefix — служебный URL для пользовательских новостей без ссылки
// (колонка news.url уникальна и NOT NULL). В API такой URL отдаётся как "".
const userURLPrefix = "user-news:"

type News struct {
	ID          string    `json:"id"`
	Title       string    `json:"title"`
	Summary     string    `json:"summary"`
	Content     string    `json:"content"`
	URL         string    `json:"url"`
	SourceName  string    `json:"source_name"`
	PublishedAt time.Time `json:"published_at"`
	FetchedAt   time.Time `json:"fetched_at"`
	Origin      string    `json:"origin"`
}

// CreateInput — тело POST /api/v1/news.
type CreateInput struct {
	Title string `json:"title"`
	Text  string `json:"text"`
	URL   string `json:"url"`
}

// InputError — ошибка, которую можно показать клиенту с конкретным HTTP-кодом.
type InputError struct {
	Status  int
	Message string
}

func (e *InputError) Error() string { return e.Message }
