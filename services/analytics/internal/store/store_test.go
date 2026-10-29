package store

import (
	"testing"
	"time"
)

func TestISTDayBoundary(t *testing.T) {
	// 20:00 UTC is 01:30 IST the next calendar day.
	got := istDay(time.Date(2026, 10, 28, 20, 0, 0, 0, time.UTC))
	if got.Format("2006-01-02") != "2026-10-29" {
		t.Fatalf("expected IST day 2026-10-29, got %s", got.Format("2006-01-02"))
	}
	// 18:00 UTC is 23:30 IST, still the same day.
	got = istDay(time.Date(2026, 10, 28, 18, 0, 0, 0, time.UTC))
	if got.Format("2006-01-02") != "2026-10-28" {
		t.Fatalf("expected IST day 2026-10-28, got %s", got.Format("2006-01-02"))
	}
}

func TestCellOf(t *testing.T) {
	if cellOf(19.07) != cellOf(19.0749) {
		t.Fatal("points 500 m apart should share a cell")
	}
	if cellOf(19.07) == cellOf(19.20) {
		t.Fatal("points 14 km apart should not share a cell")
	}
}

func TestRatioHandlesZero(t *testing.T) {
	if ratio(5, 0) != 0 {
		t.Fatal("division by zero must yield 0")
	}
}
