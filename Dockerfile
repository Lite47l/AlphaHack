FROM golang:1.27-alpine AS build

WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN go mod tidy && CGO_ENABLED=0 GOOS=linux go build -o /out/api ./cmd/api

FROM alpine:3.21

RUN apk add --no-cache ca-certificates

COPY Russian_Trusted_Root_CA.cer /usr/local/share/ca-certificates/Russian_Trusted_Root_CA.crt
RUN update-ca-certificates && adduser -D -H appuser

USER appuser
WORKDIR /app

COPY --from=build /out/api /app/api

EXPOSE 8080
ENTRYPOINT ["/app/api"]

