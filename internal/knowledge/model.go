package knowledge

import "time"

type Document struct {
	ID          string    `json:"id"`
	Title       string    `json:"title"`
	Institution string    `json:"institution"`
	DocumentURL string    `json:"document_url"`
	PublishedAt time.Time `json:"published_at"`
}
