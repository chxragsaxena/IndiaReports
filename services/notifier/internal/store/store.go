// Package store persists subscriptions and delivery attempts (the notifier owns this data).
package store

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/chxragsaxena/indiareports/notifier/internal/events"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	KindPincode = "pincode"
	KindCity    = "city"
	KindState   = "state"
	KindRadius  = "radius"

	MaxRadiusKm = 50.0
)

var ErrTooManySubscriptions = errors.New("too many subscriptions for this chat")

type Subscription struct {
	ID        string    `json:"id"`
	Channel   string    `json:"channel"`
	ChatID    string    `json:"chat_id"`
	Kind      string    `json:"kind"`
	Pincode   string    `json:"pincode,omitempty"`
	City      string    `json:"city,omitempty"`
	State     string    `json:"state,omitempty"`
	Latitude  *float64  `json:"latitude,omitempty"`
	Longitude *float64  `json:"longitude,omitempty"`
	RadiusKm  *float64  `json:"radius_km,omitempty"`
	Category  string    `json:"category,omitempty"`
	CreatedAt time.Time `json:"created_at"`
}

type Store struct {
	pool *pgxpool.Pool
}

func Open(ctx context.Context, url string) (*Store, error) {
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, err
	}
	cfg.MaxConns = 20
	cfg.MaxConnLifetime = 30 * time.Minute
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, err
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, err
	}
	s := &Store{pool: pool}
	if err := s.migrate(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("migrate: %w", err)
	}
	return s, nil
}

func (s *Store) Close()                         { s.pool.Close() }
func (s *Store) Ping(ctx context.Context) error { return s.pool.Ping(ctx) }

const schema = `
CREATE TABLE IF NOT EXISTS subscriptions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    channel     text NOT NULL,
    chat_id     text NOT NULL,
    kind        text NOT NULL CHECK (kind IN ('pincode','city','state','radius')),
    pincode     text,
    city_norm   text,
    state_norm  text,
    lat         double precision,
    lng         double precision,
    radius_km   double precision,
    category    text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_subs_chat    ON subscriptions (channel, chat_id);
CREATE INDEX IF NOT EXISTS ix_subs_pincode ON subscriptions (pincode) WHERE kind = 'pincode';
CREATE INDEX IF NOT EXISTS ix_subs_city    ON subscriptions (state_norm, city_norm) WHERE kind = 'city';
CREATE INDEX IF NOT EXISTS ix_subs_state   ON subscriptions (state_norm) WHERE kind = 'state';
CREATE INDEX IF NOT EXISTS ix_subs_radius  ON subscriptions (lat) WHERE kind = 'radius';

CREATE TABLE IF NOT EXISTS deliveries (
    subscription_id uuid NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    event_id        text NOT NULL,
    status          text NOT NULL DEFAULT 'pending',
    attempts        int  NOT NULL DEFAULT 0,
    error           text,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (subscription_id, event_id)
);
CREATE INDEX IF NOT EXISTS ix_deliveries_updated ON deliveries (updated_at);
`

// migrate runs under an advisory lock so several instances starting together are safe.
func (s *Store) migrate(ctx context.Context) error {
	conn, err := s.pool.Acquire(ctx)
	if err != nil {
		return err
	}
	defer conn.Release()
	const lockID = 727001
	if _, err := conn.Exec(ctx, "SELECT pg_advisory_lock($1)", lockID); err != nil {
		return err
	}
	defer conn.Exec(context.Background(), "SELECT pg_advisory_unlock($1)", lockID)
	_, err = conn.Exec(ctx, schema)
	return err
}

func norm(s string) string { return strings.ToLower(strings.TrimSpace(s)) }

// Create stores a subscription, enforcing the per-chat cap atomically.
func (s *Store) Create(ctx context.Context, sub Subscription, maxPerChat int) (Subscription, error) {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return sub, err
	}
	defer tx.Rollback(ctx)

	// Serialise concurrent creates for the same chat so the cap cannot be raced.
	if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock(hashtext($1))", sub.Channel+":"+sub.ChatID); err != nil {
		return sub, err
	}
	var n int
	if err := tx.QueryRow(ctx,
		"SELECT count(*) FROM subscriptions WHERE channel=$1 AND chat_id=$2", sub.Channel, sub.ChatID,
	).Scan(&n); err != nil {
		return sub, err
	}
	if n >= maxPerChat {
		return sub, ErrTooManySubscriptions
	}

	err = tx.QueryRow(ctx, `
		INSERT INTO subscriptions
		    (channel, chat_id, kind, pincode, city_norm, state_norm, lat, lng, radius_km, category)
		VALUES ($1,$2,$3,NULLIF($4,''),NULLIF($5,''),NULLIF($6,''),$7,$8,$9,NULLIF($10,''))
		RETURNING id, created_at`,
		sub.Channel, sub.ChatID, sub.Kind, sub.Pincode, norm(sub.City), norm(sub.State),
		sub.Latitude, sub.Longitude, sub.RadiusKm, sub.Category,
	).Scan(&sub.ID, &sub.CreatedAt)
	if err != nil {
		return sub, err
	}
	return sub, tx.Commit(ctx)
}

func (s *Store) List(ctx context.Context, channel, chatID string) ([]Subscription, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT id, channel, chat_id, kind, COALESCE(pincode,''), COALESCE(city_norm,''),
		       COALESCE(state_norm,''), lat, lng, radius_km, COALESCE(category,''), created_at
		FROM subscriptions WHERE channel=$1 AND chat_id=$2 ORDER BY created_at DESC LIMIT 100`,
		channel, chatID)
	if err != nil {
		return nil, err
	}
	return scanSubs(rows)
}

func (s *Store) Delete(ctx context.Context, id, chatID string) (bool, error) {
	tag, err := s.pool.Exec(ctx, "DELETE FROM subscriptions WHERE id=$1 AND chat_id=$2", id, chatID)
	if err != nil {
		return false, err
	}
	return tag.RowsAffected() > 0, nil
}

// Match returns the subscriptions that should hear about this event.
func (s *Store) Match(ctx context.Context, ev events.Event) ([]Subscription, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT id, channel, chat_id, kind, COALESCE(pincode,''), COALESCE(city_norm,''),
		       COALESCE(state_norm,''), lat, lng, radius_km, COALESCE(category,''), created_at
		FROM subscriptions
		WHERE (category IS NULL OR category = $1)
		  AND (
		        (kind = 'pincode' AND pincode = $2)
		     OR (kind = 'city'    AND state_norm = $3 AND city_norm = $4)
		     OR (kind = 'state'   AND state_norm = $3)
		     OR (kind = 'radius'
		         AND lat BETWEEN $5 - 0.5 AND $5 + 0.5
		         AND 2 * 6371 * asin(sqrt(
		               power(sin(radians(lat - $5) / 2), 2) +
		               cos(radians($5)) * cos(radians(lat)) *
		               power(sin(radians(lng - $6) / 2), 2)
		             )) <= radius_km)
		      )`,
		ev.Category, ev.Pincode, norm(ev.State), norm(ev.City), ev.Latitude, ev.Longitude)
	if err != nil {
		return nil, err
	}
	return scanSubs(rows)
}

func scanSubs(rows pgx.Rows) ([]Subscription, error) {
	defer rows.Close()
	var out []Subscription
	for rows.Next() {
		var sub Subscription
		if err := rows.Scan(&sub.ID, &sub.Channel, &sub.ChatID, &sub.Kind, &sub.Pincode, &sub.City,
			&sub.State, &sub.Latitude, &sub.Longitude, &sub.RadiusKm, &sub.Category, &sub.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, sub)
	}
	return out, rows.Err()
}

// ClaimDelivery registers an attempt and reports whether the message was already
// sent. This makes at-least-once stream delivery idempotent per subscription.
func (s *Store) ClaimDelivery(ctx context.Context, subID, eventID string) (alreadySent bool, err error) {
	var status string
	err = s.pool.QueryRow(ctx, `
		INSERT INTO deliveries (subscription_id, event_id, attempts) VALUES ($1,$2,1)
		ON CONFLICT (subscription_id, event_id)
		DO UPDATE SET attempts = deliveries.attempts + 1, updated_at = now()
		RETURNING status`, subID, eventID).Scan(&status)
	return status == "sent", err
}

func (s *Store) MarkDelivery(ctx context.Context, subID, eventID, status, errMsg string) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE deliveries SET status=$3, error=NULLIF($4,''), updated_at=now()
		WHERE subscription_id=$1 AND event_id=$2`, subID, eventID, status, errMsg)
	return err
}

// PruneDeliveries keeps the deliveries table bounded.
func (s *Store) PruneDeliveries(ctx context.Context, olderThan time.Duration) (int64, error) {
	tag, err := s.pool.Exec(ctx,
		"DELETE FROM deliveries WHERE updated_at < now() - make_interval(secs => $1)", olderThan.Seconds())
	if err != nil {
		return 0, err
	}
	return tag.RowsAffected(), nil
}
