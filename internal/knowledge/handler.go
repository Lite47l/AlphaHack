package knowledge

import (
    "net/http"
    "os"
    "path/filepath"
    "strconv"
    "strings"
    "time"

    "hackathon-backend/internal/response"
)

type Handler struct{ service *Service }

func NewHandler(service *Service) *Handler { return &Handler{service: service} }

func (h *Handler) List(w http.ResponseWriter, r *http.Request) {
    limit, offset := parseInt(r, "limit", 20), parseInt(r, "offset", 0)
    items, err := h.service.List(r.Context(), limit, offset)
    if err != nil { response.WriteServiceError(w, err); return }
    response.WriteJSON(w, http.StatusOK, map[string]any{"items":items,"limit":limit,"offset":offset})
}

func parseInt(r *http.Request, key string, fallback int) int {
    n, err := strconv.Atoi(r.URL.Query().Get(key))
    if err != nil { return fallback }
    return n
}

func (h *Handler) ImportPDF(w http.ResponseWriter, r *http.Request) {
    const maxUploadSize = 110 << 20
    r.Body = http.MaxBytesReader(w, r.Body, maxUploadSize)
    if err := r.ParseMultipartForm(10 << 20); err != nil {
        http.Error(w, "invalid multipart form or request exceeds 110 MB", http.StatusBadRequest)
        return
    }
    file, header, err := r.FormFile("file")
    if err != nil { http.Error(w, "PDF file is required in field 'file'", http.StatusBadRequest); return }
    defer file.Close()
    if strings.ToLower(filepath.Ext(header.Filename)) != ".pdf" {
        http.Error(w, "file must have .pdf extension", http.StatusBadRequest); return
    }
    tmp, err := os.CreateTemp("", "knowledge-*.pdf")
    if err != nil { http.Error(w, "could not create temporary file", http.StatusInternalServerError); return }
    path := tmp.Name()
    defer os.Remove(path)
    if _, err := tmp.ReadFrom(file); err != nil {
        tmp.Close(); http.Error(w, "could not read PDF", http.StatusBadRequest); return
    }
    if err := tmp.Close(); err != nil { http.Error(w, "could not save temporary PDF", http.StatusInternalServerError); return }
    var publishedAt *time.Time
    if value := r.FormValue("published_at"); value != "" {
        date, err := time.Parse("2006-01-02", value)
        if err != nil { http.Error(w, "published_at must use YYYY-MM-DD", http.StatusBadRequest); return }
        publishedAt = &date
    }
    id, inserted, err := h.service.ImportPDF(r.Context(), path, r.FormValue("title"), r.FormValue("document_url"), publishedAt)
    if err != nil { http.Error(w, "PDF import failed: "+err.Error(), http.StatusInternalServerError); return }
    response.WriteJSON(w, http.StatusOK, map[string]any{"id":id,"inserted":inserted})
}
