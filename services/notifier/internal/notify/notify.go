// Package notify turns stream events into messages for subscribers.
package notify

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/chxragsaxena/indiareports/notifier/internal/events"
	"github.com/chxragsaxena/indiareports/notifier/internal/store"
	"golang.org/x/time/rate"
)

const ChannelTelegram = "telegram"

// Sender delivers one message to one chat. Implementations must be safe for concurrent use.
type Sender interface {
	Send(ctx context.Context, chatID, text string) error
}

// ErrPermanent marks failures that retrying cannot fix (bad chat id, blocked bot).
var ErrPermanent = errors.New("permanent delivery failure")

// LogSender is used when no Telegram token is configured: the message is logged only.
type LogSender struct{ Log *slog.Logger }

func (l LogSender) Send(_ context.Context, chatID, text string) error {
	l.Log.Info("notification (no telegram token configured)", "chat_id", chatID, "text", text)
	return nil
}

type Telegram struct {
	token   string
	client  *http.Client
	limiter *rate.Limiter
}

func NewTelegram(token string, perSecond float64) *Telegram {
	return &Telegram{
		token:   token,
		client:  &http.Client{Timeout: 10 * time.Second},
		limiter: rate.NewLimiter(rate.Limit(perSecond), int(perSecond)),
	}
}

func (t *Telegram) Send(ctx context.Context, chatID, text string) error {
	// Telegram caps a bot at ~30 messages/second overall; stay under it.
	if err := t.limiter.Wait(ctx); err != nil {
		return err
	}
	body, _ := json.Marshal(map[string]any{
		"chat_id":                  chatID,
		"text":                     text,
		"disable_web_page_preview": true,
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		"https://api.telegram.org/bot"+t.token+"/sendMessage", bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := t.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	respBody, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))

	switch {
	case resp.StatusCode == http.StatusOK:
		return nil
	case resp.StatusCode == http.StatusTooManyRequests:
		return fmt.Errorf("telegram rate limited: %s", respBody)
	case resp.StatusCode >= 400 && resp.StatusCode < 500:
		// 400 chat not found, 403 bot blocked by user: do not retry.
		return fmt.Errorf("%w: telegram %d: %s", ErrPermanent, resp.StatusCode, respBody)
	default:
		return fmt.Errorf("telegram %d: %s", resp.StatusCode, respBody)
	}
}

// Message renders an event as plain text (no markup, so nothing needs escaping).
func Message(ev events.Event, appURL string) string {
	urgent := ev.Category == "Fire" || ev.Category == "Medical" || ev.Category == "Crime"
	prefix := ""
	if urgent {
		prefix = "URGENT - "
	}
	where := strings.Trim(strings.Join([]string{ev.City, ev.State}, ", "), ", ")

	var b strings.Builder
	switch ev.Type {
	case events.TypeReportStatusChanged:
		fmt.Fprintf(&b, "%sUpdate: %s in %s\n%q is now %s (was %s)",
			prefix, ev.Category, where, ev.Title, ev.NewStatus, ev.OldStatus)
	default:
		fmt.Fprintf(&b, "%sNew %s report in %s\n%s", prefix, ev.Category, where, ev.Title)
	}
	fmt.Fprintf(&b, "\n%s/?report=%s", strings.TrimRight(appURL, "/"), ev.ReportID)
	return b.String()
}

// Dispatcher matches events to subscriptions and sends through a bounded worker pool.
type Dispatcher struct {
	store   *store.Store
	sender  Sender
	log     *slog.Logger
	appURL  string
	workers int
}

func NewDispatcher(s *store.Store, sender Sender, log *slog.Logger, appURL string, workers int) *Dispatcher {
	return &Dispatcher{store: s, sender: sender, log: log, appURL: appURL, workers: workers}
}

// Handle delivers one event to every matching subscriber and returns only after
// all sends finished, so the caller can safely ack the stream entry. A returned
// error means the entry should be retried later (already-sent subscribers are
// skipped on the retry via ClaimDelivery).
func (d *Dispatcher) Handle(ctx context.Context, ev events.Event) error {
	subs, err := d.store.Match(ctx, ev)
	if err != nil {
		return fmt.Errorf("match subscriptions: %w", err)
	}
	if len(subs) == 0 {
		return nil
	}
	text := Message(ev, d.appURL)

	jobs := make(chan store.Subscription)
	var (
		wg       sync.WaitGroup
		mu       sync.Mutex
		firstErr error
	)
	n := min(d.workers, len(subs))
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for sub := range jobs {
				if err := d.deliver(ctx, sub, ev, text); err != nil {
					mu.Lock()
					if firstErr == nil {
						firstErr = err
					}
					mu.Unlock()
				}
			}
		}()
	}
	for _, sub := range subs {
		jobs <- sub
	}
	close(jobs)
	wg.Wait()
	return firstErr
}

func (d *Dispatcher) deliver(ctx context.Context, sub store.Subscription, ev events.Event, text string) error {
	sent, err := d.store.ClaimDelivery(ctx, sub.ID, ev.EventID)
	if err != nil {
		return err
	}
	if sent {
		return nil // idempotent: a redelivered event never sends twice
	}

	var sendErr error
	for attempt := 1; attempt <= 3; attempt++ {
		sendErr = d.sender.Send(ctx, sub.ChatID, text)
		if sendErr == nil || errors.Is(sendErr, ErrPermanent) || ctx.Err() != nil {
			break
		}
		time.Sleep(time.Duration(attempt) * 500 * time.Millisecond)
	}

	switch {
	case sendErr == nil:
		return d.store.MarkDelivery(ctx, sub.ID, ev.EventID, "sent", "")
	case errors.Is(sendErr, ErrPermanent):
		d.log.Warn("permanent delivery failure", "sub", sub.ID, "err", sendErr)
		_ = d.store.MarkDelivery(ctx, sub.ID, ev.EventID, "failed", sendErr.Error())
		return nil // do not retry the whole event for a dead chat
	default:
		_ = d.store.MarkDelivery(ctx, sub.ID, ev.EventID, "retry", sendErr.Error())
		return sendErr
	}
}
