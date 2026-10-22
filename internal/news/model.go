package news

import "time"

type News struct {
	ID          string    `json:"id"`
	Title       string    `json:"title"`
	Summary     string    `json:"summary"`
	URL         string    `json:"url"`
	SourceName  string    `json:"source_name"`
	PublishedAt time.Time `json:"published_at"`
}
