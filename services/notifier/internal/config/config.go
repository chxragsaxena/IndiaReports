package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	Port          string
	DatabaseURL   string
	RedisURL      string
	Stream        string
	Group         string
	TelegramToken string
	AppURL        string
	AllowedOrigin []string

	MaxConnections   int
	SendWorkers      int
	TelegramRatePS   float64
	MaxSubsPerChat   int
	SubscribeRatePM  int
	ClaimIdle        time.Duration
	MaxDeliveryTries int
}

func Load() (Config, error) {
	c := Config{
		Port:             env("PORT", "8100"),
		DatabaseURL:      os.Getenv("DATABASE_URL"),
		RedisURL:         os.Getenv("REDIS_URL"),
		Stream:           env("EVENT_STREAM", "reports.events"),
		Group:            env("CONSUMER_GROUP", "notifier"),
		TelegramToken:    os.Getenv("TELEGRAM_BOT_TOKEN"),
		AppURL:           env("APP_URL", "https://indiareports.vercel.app"),
		AllowedOrigin:    splitList(env("CORS_ORIGINS", "*")),
		MaxConnections:   envInt("MAX_CONNECTIONS", 50000),
		SendWorkers:      envInt("SEND_WORKERS", 16),
		TelegramRatePS:   float64(envInt("TELEGRAM_RATE_PER_SEC", 25)),
		MaxSubsPerChat:   envInt("MAX_SUBS_PER_CHAT", 20),
		SubscribeRatePM:  envInt("SUBSCRIBE_RATE_PER_MIN", 20),
		ClaimIdle:        time.Duration(envInt("CLAIM_IDLE_SECONDS", 60)) * time.Second,
		MaxDeliveryTries: envInt("MAX_DELIVERY_TRIES", 5),
	}
	if c.DatabaseURL == "" {
		return c, fmt.Errorf("DATABASE_URL is required")
	}
	if c.RedisURL == "" {
		return c, fmt.Errorf("REDIS_URL is required")
	}
	return c, nil
}

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func splitList(s string) []string {
	var out []string
	for _, p := range strings.Split(s, ",") {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}
