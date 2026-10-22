package company

import "time"

type Company struct {
	ID          string    `json:"id"`
	Name        string    `json:"name"`
	Industry    string    `json:"industry"`
	Description string    `json:"description"`
	CreatedAt   time.Time `json:"created_at"`
}

type FeedItem struct {
	ID        string    `json:"id"`
	Kind      string    `json:"kind"`
	Title     string    `json:"title"`
	URL       string    `json:"url"`
	Published time.Time `json:"published_at"`
}
