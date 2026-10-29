package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/chxragsaxena/indiareports/notifier/internal/api"
	"github.com/chxragsaxena/indiareports/notifier/internal/config"
	"github.com/chxragsaxena/indiareports/notifier/internal/consumer"
	"github.com/chxragsaxena/indiareports/notifier/internal/hub"
	"github.com/chxragsaxena/indiareports/notifier/internal/notify"
	"github.com/chxragsaxena/indiareports/notifier/internal/store"
	"github.com/redis/go-redis/v9"
)

func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))

	cfg, err := config.Load()
	if err != nil {
		log.Error("invalid configuration", "err", err)
		os.Exit(1)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	opts, err := redis.ParseURL(cfg.RedisURL)
	if err != nil {
		log.Error("invalid REDIS_URL", "err", err)
		os.Exit(1)
	}
	rdb := redis.NewClient(opts)
	defer rdb.Close()

	// Wait for dependencies instead of crashing: on a cold start (docker compose,
	// Render) Postgres and Redis may come up after this process.
	var st *store.Store
	for ctx.Err() == nil {
		st, err = store.Open(ctx, cfg.DatabaseURL)
		if err == nil {
			break
		}
		log.Warn("database not ready, retrying", "err", err)
		time.Sleep(2 * time.Second)
	}
	if st == nil {
		return
	}
	defer st.Close()

	var sender notify.Sender = notify.LogSender{Log: log}
	if cfg.TelegramToken != "" {
		sender = notify.NewTelegram(cfg.TelegramToken, cfg.TelegramRatePS)
		log.Info("telegram delivery enabled")
	} else {
		log.Info("TELEGRAM_BOT_TOKEN not set: alerts are logged, not sent")
	}

	h := hub.New(cfg.MaxConnections)
	disp := notify.NewDispatcher(st, sender, log, cfg.AppURL, cfg.SendWorkers)

	hostname, _ := os.Hostname()
	cons := consumer.New(rdb, consumer.Config{
		Stream:    cfg.Stream,
		Group:     cfg.Group,
		Name:      hostname + "-" + time.Now().Format("150405"),
		ClaimIdle: cfg.ClaimIdle,
		MaxTries:  int64(cfg.MaxDeliveryTries),
	}, h, disp, log)

	go cons.RunLive(ctx)
	go cons.RunGroup(ctx)
	go pruneLoop(ctx, st, log)

	srv := &http.Server{
		Addr: ":" + cfg.Port,
		Handler: (&api.Server{
			Store:          st,
			Hub:            h,
			Redis:          rdb,
			AllowedOrigins: cfg.AllowedOrigin,
			MaxSubsPerChat: cfg.MaxSubsPerChat,
			SubscribeRate:  cfg.SubscribeRatePM,
		}).Handler(),
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       120 * time.Second,
	}

	go func() {
		log.Info("notifier listening", "port", cfg.Port)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Error("http server failed", "err", err)
			stop()
		}
	}()

	<-ctx.Done()
	log.Info("shutting down")
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
			n, err := st.PruneDeliveries(ctx, 7*24*time.Hour)
			if err != nil {
				log.Warn("prune failed", "err", err)
				continue
			}
			log.Info("pruned old deliveries", "rows", n)
		}
	}
}
