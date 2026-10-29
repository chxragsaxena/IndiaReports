// Package hub fans live report events out to WebSocket clients by geography.
package hub

import (
	"encoding/json"
	"errors"
	"sync"
	"sync/atomic"
	"time"

	"github.com/chxragsaxena/indiareports/notifier/internal/events"
)

const (
	// At or above this zoom the client gets individual reports; below it, a
	// throttled "refresh" hint so it re-fetches (cached) clusters instead.
	PinZoom         = 8.0
	RefreshInterval = 3 * time.Second
	sendBuffer      = 64
)

var ErrTooManyConnections = errors.New("too many connections")

type Stats struct {
	Connections int64 `json:"connections"`
	Delivered   int64 `json:"delivered"`
	Refreshes   int64 `json:"refreshes"`
	SlowDropped int64 `json:"slow_clients_dropped"`
}

type Hub struct {
	mu      sync.RWMutex
	tiles   map[Tile]map[*Client]struct{}
	clients map[*Client]struct{}
	max     int

	delivered   atomic.Int64
	refreshes   atomic.Int64
	slowDropped atomic.Int64
}

func New(maxConnections int) *Hub {
	return &Hub{
		tiles:   make(map[Tile]map[*Client]struct{}),
		clients: make(map[*Client]struct{}),
		max:     maxConnections,
	}
}

func (h *Hub) register(c *Client) error {
	h.mu.Lock()
	defer h.mu.Unlock()
	if len(h.clients) >= h.max {
		return ErrTooManyConnections
	}
	h.clients[c] = struct{}{}
	return nil
}

func (h *Hub) unregister(c *Client) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if _, ok := h.clients[c]; !ok {
		return
	}
	delete(h.clients, c)
	h.removeFromTilesLocked(c)
}

func (h *Hub) removeFromTilesLocked(c *Client) {
	for _, t := range c.tiles {
		if set := h.tiles[t]; set != nil {
			delete(set, c)
			if len(set) == 0 {
				delete(h.tiles, t)
			}
		}
	}
	c.tiles = nil
}

// setViewport moves the client to the tiles covering its new viewport.
func (h *Hub) setViewport(c *Client, box BBox, zoom float64) {
	tiles := TilesFor(box)

	h.mu.Lock()
	if _, ok := h.clients[c]; !ok {
		h.mu.Unlock()
		return
	}
	h.removeFromTilesLocked(c)
	for _, t := range tiles {
		set := h.tiles[t]
		if set == nil {
			set = make(map[*Client]struct{})
			h.tiles[t] = set
		}
		set[c] = struct{}{}
	}
	c.tiles = tiles
	h.mu.Unlock()

	c.mu.Lock()
	c.box, c.zoom, c.hasViewport = box, zoom, true
	c.mu.Unlock()
}

type reportMessage struct {
	Type  string       `json:"type"`
	Event string       `json:"event"`
	Data  events.Event `json:"report"`
}

// Broadcast offers an event to the clients whose viewport tile contains it.
func (h *Hub) Broadcast(ev events.Event) {
	h.mu.RLock()
	set := h.tiles[TileOf(ev.Latitude, ev.Longitude)]
	targets := make([]*Client, 0, len(set))
	for c := range set {
		targets = append(targets, c)
	}
	h.mu.RUnlock()

	if len(targets) == 0 {
		return
	}

	payload, err := json.Marshal(reportMessage{Type: "report", Event: ev.Type, Data: ev})
	if err != nil {
		return
	}
	refresh := []byte(`{"type":"refresh"}`)

	for _, c := range targets {
		c.mu.Lock()
		inView := c.hasViewport && c.box.Contains(ev.Latitude, ev.Longitude)
		zoom := c.zoom
		sendRefresh := false
		if inView && zoom < PinZoom && time.Since(c.lastRefresh) >= RefreshInterval {
			c.lastRefresh = time.Now()
			sendRefresh = true
		}
		c.mu.Unlock()

		switch {
		case !inView:
		case zoom >= PinZoom:
			if c.enqueue(payload) {
				h.delivered.Add(1)
			}
		case sendRefresh:
			if c.enqueue(refresh) {
				h.refreshes.Add(1)
			}
		}
	}
}

func (h *Hub) Stats() Stats {
	h.mu.RLock()
	n := len(h.clients)
	h.mu.RUnlock()
	return Stats{
		Connections: int64(n),
		Delivered:   h.delivered.Load(),
		Refreshes:   h.refreshes.Load(),
		SlowDropped: h.slowDropped.Load(),
	}
}
