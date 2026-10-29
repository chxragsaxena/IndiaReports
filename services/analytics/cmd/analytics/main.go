package main

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"slices"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/chxragsaxena/indiareports/analytics/internal/consumer"
	"github.com/chxragsaxena/indiareports/analytics/internal/store"
	"github.com/redis/go-redis/v9"
)

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))

	dbURL, redisURL := os.Getenv("DATABASE_URL"), os.Getenv("REDIS_URL")
	if dbURL == "" || redisURL == "" {
		log.Error("DATABASE_URL and REDIS_URL are required")
		os.Exit(1)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	opts, err := redis.ParseURL(redisURL)
	if err != nil {
		log.Error("invalid REDIS_URL", "err", err)
		os.Exit(1)
	}
	rdb := redis.NewClient(opts)
	defer rdb.Close()

	var st *store.Store
	for ctx.Err() == nil {
		if st, err = store.Open(ctx, dbURL); err == nil {
			break
		}
		log.Warn("database not ready, retrying", "err", err)
		time.Sleep(2 * time.Second)
	}
	if st == nil {
		return
	}
	defer st.Close()

	hostname, _ := os.Hostname()
	cons := consumer.New(rdb, st, consumer.Config{
		Stream:    env("EVENT_STREAM", "reports.events"),
		Group:     env("CONSUMER_GROUP", "analytics"),
		Name:      hostname + "-" + time.Now().Format("150405"),
		ClaimIdle: 60 * time.Second,
		MaxTries:  5,
	}, log)
	go cons.Run(ctx)
	go pruneLoop(ctx, st, log)

	srv := &http.Server{
		Addr:              ":" + env("PORT", "8200"),
		Handler:           newAPI(st, rdb, strings.Split(env("CORS_ORIGINS", "*"), ",")).handler(),
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       120 * time.Second,
	}
	go func() {
		log.Info("analytics listening", "addr", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Error("http server failed", "err", err)
			stop()
		}
	}()

	<-ctx.Done()
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = srv.Shutdown(shutdownCtx)
}

func pruneLoop(ctx context.Context, st *store.Store, log *slog.Logger) {
	ticker := time.NewTicker(6 * time.Hour)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if err := st.Prune(ctx); err != nil {
				log.Warn("prune failed", "err", err)
			}
		}
	}
}

// ---- HTTP ----

type api struct {
	store   *store.Store
	redis   *redis.Client
	origins []string
	cache   *ttlCache
}

func newAPI(st *store.Store, rdb *redis.Client, origins []string) *api {
	return &api{store: st, redis: rdb, origins: origins, cache: newTTLCache(15*time.Second, 2000)}
}

func (a *api) handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "healthy"})
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
		defer cancel()
		if a.store.Ping(ctx) != nil || a.redis.Ping(ctx).Err() != nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "dependency down"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
	})
	mux.HandleFunc("GET /v1/summary", a.cached(func(r *http.Request) (any, error) {
		return a.store.Summary(r.Context(), intParam(r, "days", 30, 1, 365))
	}))
	mux.HandleFunc("GET /v1/trends", a.cached(func(r *http.Request) (any, error) {
		return a.store.Trends(r.Context(), intParam(r, "days", 30, 1, 365),
			strings.TrimSpace(r.URL.Query().Get("state")), strings.TrimSpace(r.URL.Query().Get("category")))
	}))
	mux.HandleFunc("GET /v1/leaderboard", a.cached(func(r *http.Request) (any, error) {
		return a.store.Leaderboard(r.Context(), r.URL.Query().Get("by"),
			intParam(r, "days", 30, 1, 365), intParam(r, "min_reports", 5, 1, 100000))
	}))
	mux.HandleFunc("GET /v1/hotspots", a.cached(func(r *http.Request) (any, error) {
		return a.store.Hotspots(r.Context(), intParam(r, "limit", 10, 1, 50), intParam(r, "min_count", 5, 1, 100000))
	}))
	return a.cors(mux)
}

func (a *api) cors(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if origin := r.Header.Get("Origin"); origin != "" {
			switch {
			case slices.Contains(a.origins, "*"):
				w.Header().Set("Access-Control-Allow-Origin", "*")
			case slices.Contains(a.origins, origin):
				w.Header().Set("Access-Control-Allow-Origin", origin)
				w.Header().Add("Vary", "Origin")
			}
			w.Header().Set("Access-Control-Allow-Methods", "GET,OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		}
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// cached serves a short-lived in-process copy keyed by the full query string, so a
// burst of identical dashboard requests costs one database query per instance.
func (a *api) cached(fn func(*http.Request) (any, error)) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		key := r.URL.Path + "?" + r.URL.RawQuery
		if body, ok := a.cache.get(key); ok {
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("X-Cache", "HIT")
			w.Write(body)
			return
		}
		v, err := fn(r)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "query failed"})
			return
		}
		body, _ := json.Marshal(v)
		a.cache.set(key, body)
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("X-Cache", "MISS")
		w.Write(body)
	}
}

func intParam(r *http.Request, name string, def, lo, hi int) int {
	n, err := strconv.Atoi(r.URL.Query().Get(name))
	if err != nil {
		return def
	}
	return max(lo, min(hi, n))
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

type ttlEntry struct {
	body    []byte
	expires time.Time
}

type ttlCache struct {
	mu      sync.Mutex
	ttl     time.Duration
	maxKeys int
	items   map[string]ttlEntry
}

func newTTLCache(ttl time.Duration, maxKeys int) *ttlCache {
	return &ttlCache{ttl: ttl, maxKeys: maxKeys, items: map[string]ttlEntry{}}
}

func (c *ttlCache) get(key string) ([]byte, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.items[key]
	if !ok || time.Now().After(e.expires) {
		delete(c.items, key)
		return nil, false
	}
	return e.body, true
}

func (c *ttlCache) set(key string, body []byte) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.items) >= c.maxKeys { // bounded: callers choose arbitrary query strings
		clear(c.items)
	}
	c.items[key] = ttlEntry{body: body, expires: time.Now().Add(c.ttl)}
}
