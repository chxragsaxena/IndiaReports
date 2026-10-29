package events

import "testing"

func TestParse(t *testing.T) {
	ev, err := Parse("1-0", map[string]any{
		"event_id": "42",
		"type":     TypeReportCreated,
		"data":     `{"report_id":"r1","title":"t","category":"Road","status":"OPEN","latitude":19.07,"longitude":72.87,"city":"Mumbai","state":"Maharashtra","pincode":"400001"}`,
	})
	if err != nil {
		t.Fatal(err)
	}
	if ev.EventID != "42" || ev.Type != TypeReportCreated || ev.ReportID != "r1" || ev.CurrentStatus() != "OPEN" {
		t.Fatalf("unexpected event: %+v", ev)
	}
}

func TestParseRejectsBadEntries(t *testing.T) {
	cases := map[string]map[string]any{
		"no data":        {"type": TypeReportCreated},
		"bad json":       {"data": "{not json"},
		"no report id":   {"data": `{"title":"t"}`},
		"data not a str": {"data": 5},
	}
	for name, fields := range cases {
		if _, err := Parse("1-0", fields); err == nil {
			t.Errorf("%s: expected an error", name)
		}
	}
}

func TestParseFallsBackToStreamIDForEventID(t *testing.T) {
	ev, err := Parse("9-1", map[string]any{"data": `{"report_id":"r"}`})
	if err != nil || ev.EventID != "9-1" {
		t.Fatalf("got %+v, %v", ev, err)
	}
}

func TestCurrentStatusPrefersNewStatus(t *testing.T) {
	if got := (Event{Status: "OPEN", NewStatus: "RESOLVED"}).CurrentStatus(); got != "RESOLVED" {
		t.Fatalf("got %s", got)
	}
}
