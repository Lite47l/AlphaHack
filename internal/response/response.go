package response

import (
	"encoding/json"
	"errors"
	"net/http"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
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

	status := http.StatusInternalServerError
	message := "internal server error"

	switch {
	case errors.Is(err, pgx.ErrNoRows):
		status = http.StatusNotFound
		message = "Resource Not Found"

	case strings.Contains(err.Error(), "not found"):
		status = http.StatusNotFound
		message = err.Error()

	case strings.Contains(err.Error(), "invalid"),
		strings.Contains(err.Error(), "must be between"),
		strings.Contains(err.Error(), "must be >="):
		status = http.StatusBadRequest
		message = err.Error()

	default:
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) {
			switch pgErr.Code {
			case "23505":
				status = http.StatusConflict
				message = "resource already exists"

			case "23503", "23514", "23502":
				status = http.StatusBadRequest
				message = "invalid data"
			}
		}
	}

	WriteError(w, status, message)
}
