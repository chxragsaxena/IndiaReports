// Package consumer folds the report event stream into the analytics rollups.
package consumer

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/chxragsaxena/indiareports/analytics/internal/store"
	"github.com/redis/go-redis/v9"
)

type Config struct {
	Stream    string
	Group     string
	Name      string
	ClaimIdle time.Duration
	MaxTries  int64
}

type Consumer struct {
	rdb   *redis.Client
	store *store.Store
	cfg   Config
	log   *slog.Logger
}

func New(rdb *redis.Client, st *store.Store, cfg Config, log *slog.Logger) *Consumer {
	return &Consumer{rdb: rdb, store: st, cfg: cfg, log: log}
}

type payload struct {
	Category  string    `json:"category"`
	City      string    `json:"city"`
	State     string    `json:"state"`
	Latitude  float64   `json:"latitude"`
	Longitude float64   `json:"longitude"`
	OldStatus string    `json:"old_status"`
	NewStatus string    `json:"new_status"`
	CreatedAt time.Time `json:"created_at"`
	ChangedAt time.Time `json:"changed_at"`
}

func parse(msg redis.XMessage) (store.Event, error) {
	raw, ok := msg.Values["data"].(string)
	if !ok {
		return store.Event{}, fmt.Errorf("entry %s has no data", msg.ID)
	}
	var p payload
	if err := json.Unmarshal([]byte(raw), &p); err != nil {
		return store.Event{}, fmt.Errorf("entry %s: %w", msg.ID, err)
	}
	typ, _ := msg.Values["type"].(string)
	id, _ := msg.Values["event_id"].(string)
	if id == "" {
		id = msg.ID
	}
	if p.CreatedAt.IsZero() {
		return store.Event{}, fmt.Errorf("entry %s: missing created_at", msg.ID)
	}
	return store.Event{
		EventID: id, Type: typ, Category: p.Category, City: p.City, State: p.State,
		Latitude: p.Latitude, Longitude: p.Longitude, OldStatus: p.OldStatus,
		NewStatus: p.NewStatus, CreatedAt: p.CreatedAt, ChangedAt: p.ChangedAt,
	}, nil
}

func sleepCtx(ctx context.Context, d time.Duration) {
	select {
	case <-ctx.Done():
	case <-time.After(d):
	}
}

func (c *Consumer) Run(ctx context.Context) {
	for ctx.Err() == nil {
		err := c.rdb.XGroupCreateMkStream(ctx, c.cfg.Stream, c.cfg.Group, "0").Err()
		if err == nil || strings.Contains(fmt.Sprint(err), "BUSYGROUP") {
			break
		}
		c.log.Warn("cannot create consumer group, retrying", "err", err)
		sleepCtx(ctx, 2*time.Second)
	}
	go c.reclaimLoop(ctx)

	backoff := time.Second
	for ctx.Err() == nil {
		res, err := c.rdb.XReadGroup(ctx, &redis.XReadGroupArgs{
			Group: c.cfg.Group, Consumer: c.cfg.Name,
			Streams: []string{c.cfg.Stream, ">"}, Count: 100, Block: 5 * time.Second,
		}).Result()
		if err != nil {
			if errors.Is(err, redis.Nil) || ctx.Err() != nil {
				continue
			}
			c.log.Warn("group read failed", "err", err)
			sleepCtx(ctx, backoff)
			backoff = min(backoff*2, 15*time.Second)
			continue
		}
		backoff = time.Second
		for _, stream := range res {
			for _, msg := range stream.Messages {
				c.process(ctx, msg)
			}
		}
	}
}

func (c *Consumer) process(ctx context.Context, msg redis.XMessage) {
	ev, err := parse(msg)
	if err != nil {
		c.log.Error("unparseable event, dead-lettering", "err", err)
		c.deadLetter(ctx, msg, err.Error())
		return
	}
	if err := c.store.Apply(ctx, ev); err != nil {
		c.log.Warn("apply failed, will retry", "id", msg.ID, "err", err)
		return // stays pending; the reclaim loop retries it
	}
	if err := c.rdb.XAck(ctx, c.cfg.Stream, c.cfg.Group, msg.ID).Err(); err != nil {
		c.log.Warn("ack failed", "id", msg.ID, "err", err)
	}
}

func (c *Consumer) deadLetter(ctx context.Context, msg redis.XMessage, reason string) {
	values := map[string]any{"reason": reason, "original_id": msg.ID, "consumer": c.cfg.Group}
	for k, v := range msg.Values {
		values[k] = v
	}
	if err := c.rdb.XAdd(ctx, &redis.XAddArgs{
		Stream: c.cfg.Stream + ".dead", Values: values, MaxLen: 10000, Approx: true,
	}).Err(); err != nil {
		c.log.Error("dead-letter write failed, leaving entry pending", "err", err)
		return
	}
	_ = c.rdb.XAck(ctx, c.cfg.Stream, c.cfg.Group, msg.ID).Err()
}

func (c *Consumer) reclaimLoop(ctx context.Context) {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			c.reclaimOnce(ctx)
		}
	}
}

func (c *Consumer) reclaimOnce(ctx context.Context) {
	start := "0-0"
	for ctx.Err() == nil {
		msgs, next, err := c.rdb.XAutoClaim(ctx, &redis.XAutoClaimArgs{
			Stream: c.cfg.Stream, Group: c.cfg.Group, Consumer: c.cfg.Name,
			MinIdle: c.cfg.ClaimIdle, Start: start, Count: 50,
		}).Result()
		if err != nil {
			c.log.Warn("autoclaim failed", "err", err)
			return
		}
		for _, msg := range msgs {
			pending, err := c.rdb.XPendingExt(ctx, &redis.XPendingExtArgs{
				Stream: c.cfg.Stream, Group: c.cfg.Group, Start: msg.ID, End: msg.ID, Count: 1,
			}).Result()
			if err == nil && len(pending) == 1 && pending[0].RetryCount > c.cfg.MaxTries {
				c.deadLetter(ctx, msg, "max delivery attempts exceeded")
				continue
			}
			c.process(ctx, msg)
		}
		if next == "0-0" || next == "" {
			return
		}
		start = next
	}
}
