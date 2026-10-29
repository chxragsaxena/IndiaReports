package hub

import (
	"encoding/json"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

const (
	writeWait  = 10 * time.Second
	pongWait   = 70 * time.Second
	pingPeriod = 30 * time.Second
	maxMessage = 4096
)

type Client struct {
	hub  *Hub
	conn *websocket.Conn
	send chan []byte

	closeOnce sync.Once
	done      chan struct{}

	// tiles is guarded by hub.mu; the rest by mu.
	tiles       []Tile
	mu          sync.Mutex
	box         BBox
	zoom        float64
	hasViewport bool
	lastRefresh time.Time
}

// enqueue never blocks: a client that cannot keep up is disconnected so one slow
// consumer cannot stall fan-out for everyone else.
func (c *Client) enqueue(msg []byte) bool {
	select {
	case <-c.done:
		return false
	default:
	}
	select {
	case c.send <- msg:
		return true
	default:
		c.hub.slowDropped.Add(1)
		c.close()
		return false
	}
}

func (c *Client) close() {
	c.closeOnce.Do(func() {
		close(c.done)
		if c.conn != nil {
			c.conn.Close()
		}
	})
}

type inbound struct {
	Type string     `json:"type"`
	BBox [4]float64 `json:"bbox"` // west, south, east, north (MapLibre order)
	Zoom float64    `json:"zoom"`
}

func (c *Client) readPump() {
	defer func() {
		c.hub.unregister(c)
		c.close()
	}()
	c.conn.SetReadLimit(maxMessage)
	_ = c.conn.SetReadDeadline(time.Now().Add(pongWait))
	c.conn.SetPongHandler(func(string) error {
		return c.conn.SetReadDeadline(time.Now().Add(pongWait))
	})
	for {
		_, data, err := c.conn.ReadMessage()
		if err != nil {
			return
		}
		var msg inbound
		if json.Unmarshal(data, &msg) != nil || msg.Type != "viewport" {
			continue
		}
		box := BBox{MinLng: msg.BBox[0], MinLat: msg.BBox[1], MaxLng: msg.BBox[2], MaxLat: msg.BBox[3]}
		if !box.Valid() {
			continue
		}
		c.hub.setViewport(c, box, msg.Zoom)
	}
}

func (c *Client) writePump() {
	ticker := time.NewTicker(pingPeriod)
	defer func() {
		ticker.Stop()
		c.close()
	}()
	for {
		select {
		case msg := <-c.send:
			_ = c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := c.conn.WriteMessage(websocket.TextMessage, msg); err != nil {
				return
			}
		case <-ticker.C:
			_ = c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		case <-c.done:
			return
		}
	}
}

// Serve upgrades the request and runs the client until it disconnects.
func (h *Hub) Serve(upgrader *websocket.Upgrader, w http.ResponseWriter, r *http.Request) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	c := &Client{
		hub:  h,
		conn: conn,
		send: make(chan []byte, sendBuffer),
		done: make(chan struct{}),
	}
	if err := h.register(c); err != nil {
		_ = conn.WriteControl(
			websocket.CloseMessage,
			websocket.FormatCloseMessage(websocket.CloseTryAgainLater, "server busy"),
			time.Now().Add(time.Second),
		)
		conn.Close()
		return
	}
	c.enqueue([]byte(`{"type":"ready"}`))
	go c.writePump()
	c.readPump()
}
