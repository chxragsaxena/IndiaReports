package notify

import (
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
