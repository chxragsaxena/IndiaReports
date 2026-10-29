// Package api exposes the notifier's HTTP endpoints: subscriptions and the WebSocket.
package api

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"regexp"
	"slices"
	"strings"
	"time"

	"github.com/chxragsaxena/indiareports/notifier/internal/hub"
	"github.com/chxragsaxena/indiareports/notifier/internal/notify"
	"github.com/chxragsaxena/indiareports/notifier/internal/store"
	"github.com/gorilla/websocket"
	"github.com/redis/go-redis/v9"
)

var categories = []string{
	"Road", "Water Supply", "Electricity", "Garbage", "Drainage", "Street Light",
	"Traffic", "Public Transport", "Crime", "Medical", "Fire", "Other",
}

var chatIDPattern = regexp.MustCompile(`^(-?\d{1,20}|@[A-Za-z0-9_]{5,32})$`)

type Server struct {
	Store          *store.Store
	Hub            *hub.Hub
	Redis          *redis.Client
	AllowedOrigins []string
	MaxSubsPerChat int
	SubscribeRate  int
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "healthy"})
	})
	mux.HandleFunc("GET /readyz", s.ready)
	mux.HandleFunc("GET /v1/stats", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, s.Hub.Stats())
	})
	mux.HandleFunc("POST /v1/subscriptions", s.createSubscription)
	mux.HandleFunc("GET /v1/subscriptions", s.listSubscriptions)
	mux.HandleFunc("DELETE /v1/subscriptions/{id}", s.deleteSubscription)

	upgrader := &websocket.Upgrader{
		ReadBufferSize:  1024,
		WriteBufferSize: 1024,
		CheckOrigin:     s.originAllowed,
	}
	mux.HandleFunc("GET /ws", func(w http.ResponseWriter, r *http.Request) {
		s.Hub.Serve(upgrader, w, r)
	})
	return s.cors(mux)
}

func (s *Server) originAllowed(r *http.Request) bool {
	origin := r.Header.Get("Origin")
	if origin == "" || slices.Contains(s.AllowedOrigins, "*") {
		return true
	}
	return slices.Contains(s.AllowedOrigins, origin)
}

func (s *Server) cors(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if origin != "" && s.originAllowed(r) {
			if slices.Contains(s.AllowedOrigins, "*") {
				w.Header().Set("Access-Control-Allow-Origin", "*")
			} else {
				w.Header().Set("Access-Control-Allow-Origin", origin)
				w.Header().Add("Vary", "Origin")
			}
			w.Header().Set("Access-Control-Allow-Methods", "GET,POST,DELETE,OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		}
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) ready(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := s.Store.Ping(ctx); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "database down"})
		return
	}
	if err := s.Redis.Ping(ctx).Err(); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "redis down"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
}

type createRequest struct {
	Channel   string   `json:"channel"`
	ChatID    string   `json:"chat_id"`
	Kind      string   `json:"kind"`
	Pincode   string   `json:"pincode"`
	City      string   `json:"city"`
	State     string   `json:"state"`
	Latitude  *float64 `json:"latitude"`
	Longitude *float64 `json:"longitude"`
	RadiusKm  *float64 `json:"radius_km"`
	Category  string   `json:"category"`
}

var pincodePattern = regexp.MustCompile(`^\d{6}$`)

func (r createRequest) validate() (store.Subscription, string) {
	sub := store.Subscription{
		Channel:  strings.ToLower(strings.TrimSpace(r.Channel)),
		ChatID:   strings.TrimSpace(r.ChatID),
		Kind:     r.Kind,
		Pincode:  strings.TrimSpace(r.Pincode),
		City:     strings.TrimSpace(r.City),
		State:    strings.TrimSpace(r.State),
		Category: strings.TrimSpace(r.Category),
	}
	if sub.Channel != notify.ChannelTelegram {
		return sub, "channel must be \"telegram\""
	}
	if !chatIDPattern.MatchString(sub.ChatID) {
		return sub, "chat_id must be a numeric Telegram chat id or @channelname"
	}
	if sub.Category != "" && !slices.Contains(categories, sub.Category) {
		return sub, "unknown category"
	}
	switch sub.Kind {
	case store.KindPincode:
		if !pincodePattern.MatchString(sub.Pincode) {
			return sub, "pincode must be 6 digits"
		}
	case store.KindCity:
		if sub.City == "" || sub.State == "" || len(sub.City) > 100 || len(sub.State) > 100 {
			return sub, "city and state are required"
		}
	case store.KindState:
		if sub.State == "" || len(sub.State) > 100 {
			return sub, "state is required"
		}
	case store.KindRadius:
		if r.Latitude == nil || r.Longitude == nil || r.RadiusKm == nil {
			return sub, "latitude, longitude and radius_km are required"
		}
		if *r.Latitude < 6 || *r.Latitude > 38 || *r.Longitude < 68 || *r.Longitude > 98 {
			return sub, "location must be inside India"
		}
		if *r.RadiusKm < 0.5 || *r.RadiusKm > store.MaxRadiusKm {
			return sub, "radius_km must be between 0.5 and 50"
		}
		sub.Latitude, sub.Longitude, sub.RadiusKm = r.Latitude, r.Longitude, r.RadiusKm
	default:
		return sub, "kind must be one of pincode, city, state, radius"
	}
	return sub, ""
}

func (s *Server) createSubscription(w http.ResponseWriter, r *http.Request) {
	if !s.allowSubscribe(r) {
		writeError(w, http.StatusTooManyRequests, "too many requests, try again in a minute")
		return
	}
	var req createRequest
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4096))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	sub, problem := req.validate()
	if problem != "" {
		writeError(w, http.StatusUnprocessableEntity, problem)
		return
	}
	created, err := s.Store.Create(r.Context(), sub, s.MaxSubsPerChat)
	if errors.Is(err, store.ErrTooManySubscriptions) {
		writeError(w, http.StatusConflict, err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not create subscription")
		return
	}
	writeJSON(w, http.StatusCreated, created)
}

func (s *Server) listSubscriptions(w http.ResponseWriter, r *http.Request) {
	chatID := r.URL.Query().Get("chat_id")
	if !chatIDPattern.MatchString(chatID) {
		writeError(w, http.StatusUnprocessableEntity, "chat_id is required")
		return
	}
	subs, err := s.Store.List(r.Context(), notify.ChannelTelegram, chatID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list subscriptions")
		return
	}
	if subs == nil {
		subs = []store.Subscription{}
	}
	writeJSON(w, http.StatusOK, subs)
}

func (s *Server) deleteSubscription(w http.ResponseWriter, r *http.Request) {
	chatID := r.URL.Query().Get("chat_id")
	if !chatIDPattern.MatchString(chatID) {
		writeError(w, http.StatusUnprocessableEntity, "chat_id is required")
		return
	}
	ok, err := s.Store.Delete(r.Context(), r.PathValue("id"), chatID)
	if err != nil {
		writeError(w, http.StatusNotFound, "subscription not found")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "subscription not found")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// allowSubscribe is a per-IP fixed-window limiter. It fails open if Redis is down.
func (s *Server) allowSubscribe(r *http.Request) bool {
	ctx, cancel := context.WithTimeout(r.Context(), time.Second)
	defer cancel()
	key := "ratelimit:subscribe:" + clientIP(r)
	n, err := s.Redis.Incr(ctx, key).Result()
	if err != nil {
		return true
	}
	if n == 1 {
		s.Redis.Expire(ctx, key, time.Minute)
	}
	return n <= int64(s.SubscribeRate)
}

func clientIP(r *http.Request) string {
	if fwd := r.Header.Get("X-Forwarded-For"); fwd != "" {
		return strings.TrimSpace(strings.Split(fwd, ",")[0])
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"detail": msg})
}
