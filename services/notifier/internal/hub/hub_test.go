package hub

import (
	"strings"
	"testing"

	"github.com/chxragsaxena/indiareports/notifier/internal/events"
)

func newTestClient(h *Hub) *Client {
	c := &Client{hub: h, send: make(chan []byte, sendBuffer), done: make(chan struct{})}
	_ = h.register(c)
	return c
}

func TestTileOf(t *testing.T) {
	if got := TileOf(28.6, 77.2); got != (Tile{28, 77}) {
		t.Fatalf("got %+v", got)
	}
}

func TestTilesForClampsToIndia(t *testing.T) {
	// A whole-world viewport must not register more tiles than India covers.
	tiles := TilesFor(BBox{MinLat: -85, MinLng: -180, MaxLat: 85, MaxLng: 180})
	if len(tiles) > 33*31 {
		t.Fatalf("expected clamped tile set, got %d", len(tiles))
	}
	if got := TilesFor(BBox{MinLat: 40, MinLng: 0, MaxLat: 50, MaxLng: 10}); got != nil {
		t.Fatalf("viewport outside India should have no tiles, got %d", len(got))
	}
}

func TestBroadcastRoutesByViewportAndZoom(t *testing.T) {
	h := New(10)
	delhiZoomedIn := newTestClient(h)
	mumbai := newTestClient(h)
	indiaWide := newTestClient(h)

	h.setViewport(delhiZoomedIn, BBox{MinLat: 28, MinLng: 76, MaxLat: 29, MaxLng: 78}, 11)
	h.setViewport(mumbai, BBox{MinLat: 18, MinLng: 72, MaxLat: 20, MaxLng: 74}, 11)
	h.setViewport(indiaWide, BBox{MinLat: 6, MinLng: 68, MaxLat: 37, MaxLng: 97}, 4.5)

	ev := events.Event{Type: events.TypeReportCreated, ReportID: "r1", Latitude: 28.6, Longitude: 77.2}
	h.Broadcast(ev)

	if len(delhiZoomedIn.send) != 1 {
		t.Fatalf("delhi client should get the pin, got %d msgs", len(delhiZoomedIn.send))
	}
	if len(mumbai.send) != 0 {
		t.Fatalf("mumbai client must not receive a Delhi report")
	}
	if msg := string(<-indiaWide.send); msg != `{"type":"refresh"}` {
		t.Fatalf("zoomed-out client should get a refresh hint, got %s", msg)
	}

	// Refresh hints are throttled: a burst must not produce one message per report.
	for i := 0; i < 50; i++ {
		h.Broadcast(ev)
	}
	if len(indiaWide.send) != 0 {
		t.Fatalf("refresh hints were not throttled: %d queued", len(indiaWide.send))
	}
}

func TestBroadcastNeverLeaksRecipientSecrets(t *testing.T) {
	h := New(10)
	c := newTestClient(h)
	h.setViewport(c, BBox{MinLat: 28, MinLng: 76, MaxLat: 29, MaxLng: 78}, 11)

	h.Broadcast(events.Event{
		Type: events.TypeReportCreated, ReportID: "r1", Latitude: 28.6, Longitude: 77.2,
		PreviousAssignee: "Asha Rao",
		Recipient:        &events.Recipient{Name: "Asha Rao", ChatID: "123456789", AckToken: "s3cr3t-token-value"},
	})

	msg := string(<-c.send)
	for _, secret := range []string{"123456789", "s3cr3t-token-value", "Asha Rao", "ack_token", "chat_id"} {
		if strings.Contains(msg, secret) {
			t.Fatalf("websocket payload leaked %q: %s", secret, msg)
		}
	}
}

func TestMovingViewportStopsDeliveryToOldArea(t *testing.T) {
	h := New(10)
	c := newTestClient(h)
	h.setViewport(c, BBox{MinLat: 28, MinLng: 76, MaxLat: 29, MaxLng: 78}, 11)
	h.setViewport(c, BBox{MinLat: 18, MinLng: 72, MaxLat: 20, MaxLng: 74}, 11)

	h.Broadcast(events.Event{ReportID: "r1", Latitude: 28.6, Longitude: 77.2})
	if len(c.send) != 0 {
		t.Fatal("client moved away from Delhi but still received a Delhi report")
	}
}

func TestSlowClientIsDroppedNotBlocking(t *testing.T) {
	h := New(10)
	c := &Client{hub: h, send: make(chan []byte, 1), done: make(chan struct{})}
	c.send <- []byte("x")
	if c.enqueue([]byte("y")) {
		t.Fatal("enqueue into a full buffer must fail")
	}
	if h.Stats().SlowDropped != 1 {
		t.Fatalf("expected slow client to be counted, got %d", h.Stats().SlowDropped)
	}
}

func TestConnectionCap(t *testing.T) {
	h := New(1)
	newTestClient(h)
	c2 := &Client{hub: h, send: make(chan []byte, 1), done: make(chan struct{})}
	if err := h.register(c2); err != ErrTooManyConnections {
		t.Fatalf("expected cap error, got %v", err)
	}
}
