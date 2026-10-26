package analysis

import "time"

type Status string

const (
	StatusQueued     Status = "queued"
	StatusProcessing Status = "processing"
	StatusCompleted  Status = "completed"
	StatusFailed     Status = "failed"
)

type Analysis struct {
	ID        string    `json:"id"`
	CompanyID string    `json:"company_id"`
	Status    Status    `json:"status"`
	Result    *Result   `json:"result,omitempty"`
	Error     string    `json:"error,omitempty"`
	CreatedAt time.Time `json:"created_at"`
}

type Result struct {
	Facts           []string `json:"facts"`
	BankPerspective []string `json:"bank_perspective"`
	AIConclusions   []string `json:"ai_conclusions"`
	Risks           []string `json:"risks"`
	Opportunities   []string `json:"opportunities"`
	SourceURLs      []string `json:"source_urls"`
}
