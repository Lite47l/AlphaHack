FROM golang:1.27-alpine AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal
COPY migrations ./migrations
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/api ./cmd/api

FROM alpine:3.21

# poppler/tesseract: извлечение текста и OCR для POST /api/v1/knowledge/import
RUN apk add --no-cache ca-certificates poppler-utils tesseract-ocr tesseract-ocr-data-rus tesseract-ocr-data-eng

COPY Russian_Trusted_Root_CA.cer /usr/local/share/ca-certificates/Russian_Trusted_Root_CA.crt
RUN update-ca-certificates && adduser -D -H appuser

USER appuser
WORKDIR /app

COPY --from=build /out/api /app/api

EXPOSE 8080
ENTRYPOINT ["/app/api"]
