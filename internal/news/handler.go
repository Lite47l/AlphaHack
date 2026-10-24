package news

import (
	"net/http"
	"strconv"

	"hackathon-backend/internal/response"
)

type Handler struct{ service *Service }

func NewHandler(service *Service) *Handler { return &Handler{service: service} }

func (h *Handler) List(w http.ResponseWriter, r *http.Request) {
	limit, offset := parseInt(r, "limit", 20), parseInt(r, "offset", 0)
	items, err := h.service.List(r.Context(), limit, offset, r.URL.Query().Get("company_id"))
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

func parseInt(r *http.Request, key string, fallback int) int {
	n, err := strconv.Atoi(r.URL.Query().Get(key))
	if err != nil {
		return fallback
	}
	return n
}

func (h *Handler) Import(
	importer *Importer,
) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		results, err := importer.Import(r.Context())
		if err != nil {
			response.WriteServiceError(w, err)
			return
		}

		response.WriteJSON(w, http.StatusOK, map[string]any{
			"results": results,
		})
	}
}
