package analysis

import (
	"encoding/json"
	"net/http"

	"hackathon-backend/internal/response"
)

type Handler struct{ service *Service }

func NewHandler(service *Service) *Handler { return &Handler{service: service} }

func (h *Handler) Create(w http.ResponseWriter, r *http.Request) {
	companyID := r.PathValue("id")
	item, err := h.service.Create(r.Context(), companyID)
	if err != nil {
		response.WriteServiceError(w, err)
		return
	}
	w.Header().Set("Location", "/api/v1/analyses/"+item.ID)
	response.WriteJSON(w, http.StatusAccepted, item)
}

func (h *Handler) GetByID(w http.ResponseWriter, r *http.Request) {
	item, err := h.service.GetByID(r.Context(), r.PathValue("id"))
	if err != nil {
		response.WriteServiceError(w, err)
		return
	}
	response.WriteJSON(w, http.StatusOK, item)
}

// decodeJSON — заготовка для будущих POST/PATCH endpoints.
func decodeJSON(r *http.Request, dst any) error {
	return json.NewDecoder(r.Body).Decode(dst)
}
