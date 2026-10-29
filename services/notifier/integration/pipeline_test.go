//go:build integration

// End-to-end test across services: report-service -> Redis stream -> notifier.
// Requires the compose stack to be running:
//
//	REPORT_URL=http://localhost:8010 NOTIFIER_URL=http://localhost:8110 \
//	DATABASE_URL=postgres://postgres:postgres@localhost:5433/notifier_db?sslmode=disable \
//	go test -tags integration ./integration/ -v
package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"github.com/jackc/pgx/v5"
)

func env(t *testing.T, key, def string) string {
	t.Helper()
	if v := os.Getenv(key); v != "" {
		return v
	}
	if def == "" {
		t.Skipf("%s not set", key)
	}
	return def
}

type wsClient struct {
	conn *websocket.Conn
	msgs chan map[string]any
}

func dialWS(t *testing.T, notifierURL string, bbox [4]float64, zoom float64) *wsClient {
	t.Helper()
	url := "ws" + strings.TrimPrefix(notifierURL, "http") + "/ws"
	conn, _, err := websocket.DefaultDialer.Dial(url, nil)
	if err != nil {
		t.Fatalf("dial %s: %v", url, err)
	}
	t.Cleanup(func() { conn.Close() })

	c := &wsClient{conn: conn, msgs: make(chan map[string]any, 64)}
	go func() {
		for {
			var m map[string]any
			if err := conn.ReadJSON(&m); err != nil {
				close(c.msgs)
				return
			}
			c.msgs <- m
		}
	}()
	if first := c.next(t, 3*time.Second); first["type"] != "ready" {
		t.Fatalf("expected ready, got %v", first)
	}
	if err := conn.WriteJSON(map[string]any{"type": "viewport", "bbox": bbox, "zoom": zoom}); err != nil {
		t.Fatal(err)
	}
	time.Sleep(300 * time.Millisecond) // let the server apply the viewport
	return c
}

func (c *wsClient) next(t *testing.T, wait time.Duration) map[string]any {
	t.Helper()
	select {
	case m, ok := <-c.msgs:
		if !ok {
			t.Fatal("websocket closed")
		}
		return m
	case <-time.After(wait):
		t.Fatalf("no websocket message within %s", wait)
		return nil
	}
}

func (c *wsClient) expectSilence(t *testing.T, wait time.Duration) {
	t.Helper()
	select {
	case m := <-c.msgs:
		t.Fatalf("expected no message, got %v", m)
	case <-time.After(wait):
	}
}

func post(t *testing.T, url string, body any) (int, map[string]any) {
	t.Helper()
	b, _ := json.Marshal(body)
	resp, err := http.Post(url, "application/json", bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out map[string]any
	_ = json.NewDecoder(resp.Body).Decode(&out)
	return resp.StatusCode, out
}

func TestReportFlowsToWebSocketAndSubscribers(t *testing.T) {
	reportURL := env(t, "REPORT_URL", "http://localhost:8010")
	notifierURL := env(t, "NOTIFIER_URL", "http://localhost:8110")
	dbURL := env(t, "DATABASE_URL", "")

	mumbaiZoomedIn := dialWS(t, notifierURL, [4]float64{72.5, 18.8, 73.2, 19.4}, 11)
	delhiZoomedIn := dialWS(t, notifierURL, [4]float64{76.8, 28.4, 77.5, 28.9}, 11)
	indiaWide := dialWS(t, notifierURL, [4]float64{68, 6, 97, 37}, 4.5)

	chatID := fmt.Sprintf("%d", time.Now().UnixNano()%1_000_000_000)
	status, sub := post(t, notifierURL+"/v1/subscriptions", map[string]any{
		"channel": "telegram", "chat_id": chatID, "kind": "radius",
		"latitude": 19.07, "longitude": 72.87, "radius_km": 10, "category": "Road",
	})
	if status != http.StatusCreated {
		t.Fatalf("create subscription: %d %v", status, sub)
	}
	subID := sub["id"].(string)

	// An out-of-area (Delhi) subscription for the same category must NOT be notified.
	_, farSub := post(t, notifierURL+"/v1/subscriptions", map[string]any{
		"channel": "telegram", "chat_id": chatID, "kind": "radius",
		"latitude": 28.61, "longitude": 77.21, "radius_km": 10,
	})

	title := fmt.Sprintf("Integration pothole %d", time.Now().UnixNano())
	status, created := post(t, reportURL+"/api/v1/reports/", map[string]any{
		"title": title, "description": "integration test report", "category": "Road",
		"latitude": 19.076, "longitude": 72.877, "address": "a", "landmark": "b",
		"city": "Mumbai", "district": "Mumbai", "state": "Maharashtra", "pincode": "400001",
	})
	if status != http.StatusCreated {
		t.Fatalf("create report: %d %v", status, created)
	}

	// 1. The zoomed-in Mumbai client receives the pin live.
	msg := mumbaiZoomedIn.next(t, 10*time.Second)
	report, _ := msg["report"].(map[string]any)
	if msg["type"] != "report" || report["title"] != title {
		t.Fatalf("unexpected message: %v", msg)
	}

	// 2. The India-wide client gets a refresh hint, not the individual pin.
	if m := indiaWide.next(t, 5*time.Second); m["type"] != "refresh" {
		t.Fatalf("expected refresh hint, got %v", m)
	}

	// 3. The Delhi client hears nothing about a Mumbai report.
	delhiZoomedIn.expectSilence(t, 1500*time.Millisecond)

	// 4. The matching subscriber is delivered exactly once; the Delhi one is not.
	ctx := context.Background()
	conn, err := pgx.Connect(ctx, dbURL)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)

	deadline := time.Now().Add(10 * time.Second)
	var delivered, attempts int
	for time.Now().Before(deadline) {
		err = conn.QueryRow(ctx,
			"SELECT count(*), COALESCE(max(attempts),0) FROM deliveries WHERE subscription_id=$1 AND status='sent'",
			subID).Scan(&delivered, &attempts)
		if err == nil && delivered == 1 {
			break
		}
		time.Sleep(300 * time.Millisecond)
	}
	if delivered != 1 || attempts != 1 {
		t.Fatalf("expected 1 sent delivery after 1 attempt, got delivered=%d attempts=%d err=%v", delivered, attempts, err)
	}

	var farCount int
	if id, ok := farSub["id"].(string); ok {
		_ = conn.QueryRow(ctx, "SELECT count(*) FROM deliveries WHERE subscription_id=$1", id).Scan(&farCount)
	}
	if farCount != 0 {
		t.Fatalf("out-of-area subscription was notified %d times", farCount)
	}
}

func TestSubscriptionValidation(t *testing.T) {
	notifierURL := env(t, "NOTIFIER_URL", "http://localhost:8110")

	cases := []struct {
		name string
		body map[string]any
		want int
	}{
		{"bad channel", map[string]any{"channel": "sms", "chat_id": "123", "kind": "state", "state": "Delhi"}, 422},
		{"bad chat id", map[string]any{"channel": "telegram", "chat_id": "not valid!", "kind": "state", "state": "Delhi"}, 422},
		{"bad pincode", map[string]any{"channel": "telegram", "chat_id": "123", "kind": "pincode", "pincode": "12"}, 422},
		{"radius too large", map[string]any{"channel": "telegram", "chat_id": "123", "kind": "radius", "latitude": 19, "longitude": 72.8, "radius_km": 500}, 422},
		{"outside india", map[string]any{"channel": "telegram", "chat_id": "123", "kind": "radius", "latitude": 51, "longitude": 0, "radius_km": 5}, 422},
		{"unknown category", map[string]any{"channel": "telegram", "chat_id": "123", "kind": "state", "state": "Delhi", "category": "Nope"}, 422},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if status, body := post(t, notifierURL+"/v1/subscriptions", tc.body); status != tc.want {
				t.Fatalf("got %d (%v), want %d", status, body, tc.want)
			}
		})
	}
}
