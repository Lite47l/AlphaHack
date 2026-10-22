package response

import (
	"encoding/json"
	"errors"
	"github.com/jackc/pgx/v5"
	"net/http"
	"strings"
)

type ErrorBody struct {
	Error string `json:"error"`
}

func WriteJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func WriteError(w http.ResponseWriter, status int, message string) {
	WriteJSON(w, status, ErrorBody{Error: message})
}
func WriteServiceError(w http.ResponseWriter, err error) {
	if err == nil {
		return
	}
	msg := err.Error()
	status := http.StatusInternalServerError
	switch {
	case strings.Contains(msg, "invalid ") || strings.Contains(msg, "must be between") || strings.Contains(msg, "must be >="):
		status = http.StatusBadRequest
	case strings.Contains(msg, "not found") || errors.Is(err, pgx.ErrNoRows):
		status = http.StatusNotFound
	}
	if status == 500 {
		msg = "internal server error"
	}
	WriteError(w, status, msg)
}
