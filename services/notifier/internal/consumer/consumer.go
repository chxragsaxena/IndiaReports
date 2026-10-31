// Package consumer reads report events from the Redis stream.
//
// Two independent readers run in every notifier instance:
//
//   - Live: a plain XREAD of the whole stream. Every instance sees every event, so
//     any instance can push pins to the WebSocket clients connected to it.
//   - Group: an XREADGROUP consumer group. Each event is handled by exactly one
//     instance, which sends the alerts. Crashed consumers are recovered with
//     XAUTOCLAIM; entries that keep failing go to a dead-letter stream.
package consumer

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/chxragsaxena/indiareports/notifier/internal/events"
	"github.com/chxragsaxena/indiareports/notifier/internal/hub"
	"github.com/chxragsaxena/indiareports/notifier/internal/notify"
	"github.com/redis/go-redis/v9"
)

type Config struct {
	Stream      string
	Group       string
	Name        string
	ClaimIdle   time.Duration
	MaxTries    int64
	ReadBlock   time.Duration
	ReclaimEach time.Duration
}

type Consumer struct {
	rdb  *redis.Client
	cfg  Config
	hub  *hub.Hub
	disp *notify.Dispatcher
	log  *slog.Logger
}

func New(rdb *redis.Client, cfg Config, h *hub.Hub, d *notify.Dispatcher, log *slog.Logger) *Consumer {
	if cfg.ReadBlock == 0 {
		cfg.ReadBlock = 5 * time.Second
	}
	if cfg.ReclaimEach == 0 {
		cfg.ReclaimEach = 30 * time.Second
	}
	return &Consumer{rdb: rdb, cfg: cfg, hub: h, disp: d, log: log}
}

func sleepCtx(ctx context.Context, d time.Duration) {
	select {
	case <-ctx.Done():
	case <-time.After(d):
	}
}

// RunLive feeds the WebSocket hub. It starts at the current end of the stream:
// live pins are only meaningful for events that happen while a client is watching.
func (c *Consumer) RunLive(ctx context.Context) {
	lastID := "0-0"
	if last, err := c.rdb.XRevRangeN(ctx, c.cfg.Stream, "+", "-", 1).Result(); err == nil && len(last) == 1 {
		lastID = last[0].ID
	}
	backoff := time.Second
	for ctx.Err() == nil {
		res, err := c.rdb.XRead(ctx, &redis.XReadArgs{
			Streams: []string{c.cfg.Stream, lastID},
			Count:   200,
			Block:   c.cfg.ReadBlock,
		}).Result()
		if err != nil {
			if errors.Is(err, redis.Nil) || ctx.Err() != nil {
				continue
			}
			c.log.Warn("live read failed", "err", err)
			sleepCtx(ctx, backoff)
			backoff = min(backoff*2, 15*time.Second)
			continue
		}
		backoff = time.Second
		for _, stream := range res {
			for _, msg := range stream.Messages {
				lastID = msg.ID
				ev, err := events.Parse(msg.ID, msg.Values)
				if err != nil {
					c.log.Warn("skipping bad event", "err", err)
					continue
				}
				// AI findings are for administrators only: never offered to map viewers.
				if !ev.Historical && ev.Type != events.TypeReportImageAnalyzed {
					c.hub.Broadcast(ev)
				}
			}
		}
	}
}

// RunGroup sends alerts. Safe to run in many instances at once.
func (c *Consumer) RunGroup(ctx context.Context) {
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
			Group:    c.cfg.Group,
			Consumer: c.cfg.Name,
			Streams:  []string{c.cfg.Stream, ">"},
			Count:    50,
			Block:    c.cfg.ReadBlock,
		}).Result()
		if err != nil {
			if errors.Is(err, redis.Nil) || ctx.Err() != nil {
				continue
			}
			c.log.Warn("group read failed", "err", err)
			if strings.Contains(fmt.Sprint(err), "NOGROUP") {
				// Redis lost the stream or the group (it restarted without its data, or was flushed). Make it again, or this notifier
				// would fail forever. Events published while it was gone are lost, but the reports themselves stay in Postgres.
				if e := c.rdb.XGroupCreateMkStream(ctx, c.cfg.Stream, c.cfg.Group, "0").Err(); e != nil && !strings.Contains(fmt.Sprint(e), "BUSYGROUP") {
					c.log.Warn("cannot recreate consumer group", "err", e)
				} else {
					c.log.Info("consumer group recreated")
				}
			}
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

// process handles one entry and acks it only when it is fully handled.
func (c *Consumer) process(ctx context.Context, msg redis.XMessage) {
	ev, err := events.Parse(msg.ID, msg.Values)
	if err != nil {
		c.log.Error("unparseable event, dead-lettering", "id", msg.ID, "err", err)
		c.deadLetter(ctx, msg, err.Error())
		return
	}
	if err := c.disp.Handle(ctx, ev); err != nil {
		// Not acked: stays pending and is retried by the reclaim loop.
		c.log.Warn("event handling failed, will retry", "id", msg.ID, "err", err)
		return
	}
	c.ack(ctx, msg.ID)
}

func (c *Consumer) ack(ctx context.Context, id string) {
	if err := c.rdb.XAck(ctx, c.cfg.Stream, c.cfg.Group, id).Err(); err != nil {
		c.log.Warn("ack failed", "id", id, "err", err)
	}
}

func (c *Consumer) deadLetter(ctx context.Context, msg redis.XMessage, reason string) {
	values := map[string]any{"reason": reason, "original_id": msg.ID}
	for k, v := range msg.Values {
		values[k] = v
	}
	if err := c.rdb.XAdd(ctx, &redis.XAddArgs{
		Stream: c.cfg.Stream + ".dead", Values: values, MaxLen: 10000, Approx: true,
	}).Err(); err != nil {
		c.log.Error("dead-letter write failed, leaving entry pending", "id", msg.ID, "err", err)
		return
	}
	c.ack(ctx, msg.ID)
}

// reclaimLoop takes over entries that another (crashed) consumer never acked, and
// retries entries whose handling failed.
func (c *Consumer) reclaimLoop(ctx context.Context) {
	ticker := time.NewTicker(c.cfg.ReclaimEach)
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
			Stream:   c.cfg.Stream,
			Group:    c.cfg.Group,
			Consumer: c.cfg.Name,
			MinIdle:  c.cfg.ClaimIdle,
			Start:    start,
			Count:    50,
		}).Result()
		if err != nil {
			c.log.Warn("autoclaim failed", "err", err)
			return
		}
		for _, msg := range msgs {
			if c.tooManyTries(ctx, msg.ID) {
				c.log.Error("event exceeded retries, dead-lettering", "id", msg.ID)
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

func (c *Consumer) tooManyTries(ctx context.Context, id string) bool {
	pending, err := c.rdb.XPendingExt(ctx, &redis.XPendingExtArgs{
		Stream: c.cfg.Stream, Group: c.cfg.Group, Start: id, End: id, Count: 1,
	}).Result()
	return err == nil && len(pending) == 1 && pending[0].RetryCount > c.cfg.MaxTries
}
