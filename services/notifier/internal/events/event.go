// Package events defines the messages published by report-service on the Redis stream.
package events

import (
	"encoding/json"
	"fmt"
)

const (
	TypeReportCreated       = "ReportCreated"
	TypeReportStatusChanged = "ReportStatusChanged"
)

// Event is a decoded stream entry. EventID is the outbox id: stable across
// redelivery, so it is the idempotency key for every consumer.
type Event struct {
	StreamID string `json:"stream_id"`
	EventID  string `json:"event_id"`
	Type     string `json:"type"`

	ReportID  string  `json:"report_id"`
	Title     string  `json:"title"`
	Category  string  `json:"category"`
	Status    string  `json:"status,omitempty"`
	OldStatus string  `json:"old_status,omitempty"`
	NewStatus string  `json:"new_status,omitempty"`
	City      string  `json:"city"`
	State     string  `json:"state"`
	Pincode   string  `json:"pincode"`
	Latitude  float64 `json:"latitude"`
	Longitude float64 `json:"longitude"`
	CreatedAt string  `json:"created_at,omitempty"`
	ChangedAt string  `json:"changed_at,omitempty"`

	// Seeded or replayed data: counted by analytics but never alerted or pushed live.
	Historical bool `json:"historical,omitempty"`

	// Direct recipient (the responsible officer, or the admin on escalation).
	// Private: never forward these fields to WebSocket clients; use Public().
	Recipient        *Recipient `json:"recipient,omitempty"`
	PreviousAssignee string     `json:"previous_assignee,omitempty"`
	UnackHours       float64    `json:"unacknowledged_hours,omitempty"`
}

// Recipient is who must act on a report. AckToken is a bearer secret for the
// acknowledge link, so it is as sensitive as the chat id.
type Recipient struct {
	OfficerID string `json:"officer_id"`
	Name      string `json:"name"`
	Role      string `json:"role"`
	ChatID    string `json:"chat_id"`
	AckToken  string `json:"ack_token"`
}

const TypeReportEscalated = "ReportEscalated"

// Public returns a copy that is safe to show to any map viewer.
func (e Event) Public() Event {
	e.Recipient = nil
	e.PreviousAssignee = ""
	return e
}

// Parse decodes the field map of a Redis stream entry.
func Parse(streamID string, fields map[string]any) (Event, error) {
	var ev Event
	raw, ok := fields["data"].(string)
	if !ok {
		return ev, fmt.Errorf("entry %s has no data field", streamID)
	}
	if err := json.Unmarshal([]byte(raw), &ev); err != nil {
		return ev, fmt.Errorf("entry %s: bad payload: %w", streamID, err)
	}
	ev.StreamID = streamID
	ev.Type, _ = fields["type"].(string)
	ev.EventID, _ = fields["event_id"].(string)
	if ev.EventID == "" {
		ev.EventID = streamID
	}
	if ev.ReportID == "" {
		return ev, fmt.Errorf("entry %s: missing report_id", streamID)
	}
	return ev, nil
}

// CurrentStatus is the status the report has after this event.
func (e Event) CurrentStatus() string {
	if e.NewStatus != "" {
		return e.NewStatus
	}
	return e.Status
}
