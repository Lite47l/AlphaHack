package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

type Config struct {
	Port                   string
	DatabaseURL            string
	AppEnv                 string
	LogLevel               string
	ShutdownTimeoutSeconds int
}

func Load() (Config, error) {
	c := Config{Port: getEnv("PORT", "8080"), DatabaseURL: getEnv("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/hackathon?sslmode=disable"), AppEnv: getEnv("APP_ENV", "dev"), LogLevel: strings.ToLower(getEnv("LOG_LEVEL", "info")), ShutdownTimeoutSeconds: 10}
	if _, err := strconv.Atoi(c.Port); err != nil {
		return Config{}, fmt.Errorf("PORT must be a port number: %w", err)
	}
	if c.DatabaseURL == "" {
		return Config{}, fmt.Errorf("DATABASE_URL is required")
	}
	if c.ShutdownTimeoutSeconds < 1 {
		return Config{}, fmt.Errorf("SHUTDOWN_TIMEOUT_SECONDS must be positive")
	}
	return c, nil
}
func getEnv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
