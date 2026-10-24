package news

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"time"

	"hackathon-backend/internal/response"
)

type Handler struct{ service *Service }

func NewHandler(service *Service) *Handler { return &Handler{service: service} }

func (h *Handler) List(w http.ResponseWriter, r *http.Request) {
	limit, offset := parseInt(r, "limit", 20), parseInt(r, "offset", 0)
	items, err := h.service.List(r.Context(), limit, offset)
	if err != nil {
		response.WriteServiceError(w, err)
		return
	}
	response.WriteJSON(w, http.StatusOK, map[string]any{"items": items, "limit": limit, "offset": offset})
}

func (h *Handler) GetByID(w http.ResponseWriter, r *http.Request) {
	item, err := h.service.GetByID(r.Context(), r.PathValue("id"))
	if err != nil {
		response.WriteServiceError(w, err)
		return
	}
	response.WriteJSON(w, http.StatusOK, item)
}

// Create — POST /api/v1/news: пользовательская новость (201, повтор URL — 200).
func (h *Handler) Create(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
	var in CreateInput
	dec := json.NewDecoder(r.Body)
	if err := dec.Decode(&in); err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			response.WriteError(w, http.StatusRequestEntityTooLarge, "тело запроса слишком большое")
			return
		}
		response.WriteError(w, http.StatusBadRequest, "некорректный JSON в теле запроса")
		return
	}
	item, created, err := h.service.CreateUserNews(r.Context(), in)
	if err != nil {
		var inputErr *InputError
		if errors.As(err, &inputErr) {
			response.WriteError(w, inputErr.Status, inputErr.Message)
			return
		}
		response.WriteServiceError(w, err)
		return
	}
	status := http.StatusOK
	if created {
		status = http.StatusCreated
	}
	response.WriteJSON(w, status, item)
}

func parseInt(r *http.Request, key string, fallback int) int {
	n, err := strconv.Atoi(r.URL.Query().Get(key))
	if err != nil {
		return fallback
	}
	return n
}

// Import — POST /api/v1/news/import: ручной запуск сбора новостей.
func (h *Handler) Import(importer *Importer) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 3*time.Minute)
		defer cancel()
		results, err := importer.Import(ctx)
		if err != nil {
			response.WriteServiceError(w, err)
			return
		}
		response.WriteJSON(w, http.StatusOK, map[string]any{"results": results})
	}
}
