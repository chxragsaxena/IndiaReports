package notify

import (
	"context"
	"log/slog"
	"strings"
	"testing"

	"github.com/chxragsaxena/indiareports/notifier/internal/events"
)

func TestMessageMarksEmergenciesUrgent(t *testing.T) {
	ev := events.Event{
		Type: events.TypeReportCreated, ReportID: "abc", Title: "Fire in building",
		Category: "Fire", City: "Pune", State: "Maharashtra",
	}
	got := Message(ev, "https://example.org/")
	for _, want := range []string{"URGENT - ", "Pune, Maharashtra", "Fire in building", "https://example.org/?report=abc"} {
		if !strings.Contains(got, want) {
			t.Errorf("message %q missing %q", got, want)
		}
	}

	ev.Category = "Garbage"
	if strings.Contains(Message(ev, "https://example.org"), "URGENT") {
		t.Error("non-emergency report must not be marked urgent")
	}
}

func TestDirectMessages(t *testing.T) {
	ev := events.Event{
		Type: events.TypeReportCreated, ReportID: "abc", Title: "Burst pipe", Category: "Water Supply",
		City: "Mumbai", State: "Maharashtra",
		Recipient: &events.Recipient{Name: "Asha", ChatID: "1", AckToken: "tok123"},
	}
	got := DirectMessage(ev, "https://example.org/")
	for _, want := range []string{"Assigned to you", "Mumbai, Maharashtra", "https://example.org/ack?report=abc&token=tok123"} {
		if !strings.Contains(got, want) {
			t.Errorf("message %q missing %q", got, want)
		}
	}

	ev.Type = events.TypeReportEscalated
	ev.PreviousAssignee = "Asha"
	ev.UnackHours = 168
	got = DirectMessage(ev, "https://example.org")
	for _, want := range []string{"ESCALATED to you", "Asha", "168 hours"} {
		if !strings.Contains(got, want) {
			t.Errorf("escalation %q missing %q", got, want)
		}
	}
}

type captureHandler struct{ out *strings.Builder }

func (c captureHandler) Enabled(context.Context, slog.Level) bool { return true }
func (c captureHandler) Handle(_ context.Context, r slog.Record) error {
	c.out.WriteString(r.Message)
	r.Attrs(func(a slog.Attr) bool { c.out.WriteString(" " + a.Value.String()); return true })
	return nil
}
func (c captureHandler) WithAttrs([]slog.Attr) slog.Handler { return c }
func (c captureHandler) WithGroup(string) slog.Handler      { return c }

func TestLogSenderRedactsAckTokens(t *testing.T) {
	var out strings.Builder
	l := LogSender{Log: slog.New(captureHandler{&out})}
	_ = l.Send(context.Background(), "1", "Acknowledge: https://x/ack?report=abc&token=deadbeef1234")
	if strings.Contains(out.String(), "deadbeef1234") || !strings.Contains(out.String(), "<redacted>") {
		t.Fatalf("token was not redacted: %s", out.String())
	}
}

func TestMessageForStatusChange(t *testing.T) {
	ev := events.Event{
		Type: events.TypeReportStatusChanged, ReportID: "abc", Title: "Pothole",
		Category: "Road", City: "Delhi", State: "Delhi", OldStatus: "OPEN", NewStatus: "RESOLVED",
	}
	got := Message(ev, "https://example.org")
	if !strings.Contains(got, "now RESOLVED") || !strings.Contains(got, "was OPEN") {
		t.Errorf("unexpected message: %s", got)
	}
}
