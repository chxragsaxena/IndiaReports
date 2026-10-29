// Package store holds the analytics rollups. The service never keeps raw reports:
// every event updates a few counters, and every query reads small rollup tables.
package store

import (
	"context"
	"fmt"
	"math"
	"time"
	_ "time/tzdata" // IST day boundaries must work in minimal containers

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// CellSize is the hotspot grid edge in degrees (~5 km).
const CellSize = 0.05

var IST = mustLoad("Asia/Kolkata")

func mustLoad(name string) *time.Location {
	loc, err := time.LoadLocation(name)
	if err != nil {
		panic(err)
	}
	return loc
}

type Store struct{ pool *pgxpool.Pool }

func Open(ctx context.Context, url string) (*Store, error) {
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, err
	}
	cfg.MaxConns = 15
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, err
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, err
	}
	s := &Store{pool: pool}
	if err := s.migrate(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("migrate: %w", err)
	}
	return s, nil
}

func (s *Store) Close()                         { s.pool.Close() }
func (s *Store) Ping(ctx context.Context) error { return s.pool.Ping(ctx) }

const schema = `
CREATE TABLE IF NOT EXISTS processed_events (
    event_id     text PRIMARY KEY,
    processed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_processed_at ON processed_events (processed_at);

CREATE TABLE IF NOT EXISTS daily_counts (
    day             date NOT NULL,
    state           text NOT NULL,
    city            text NOT NULL,
    category        text NOT NULL,
    created         bigint NOT NULL DEFAULT 0,
    resolved        bigint NOT NULL DEFAULT 0,
    resolve_seconds double precision NOT NULL DEFAULT 0,
    PRIMARY KEY (day, state, city, category)
);

CREATE TABLE IF NOT EXISTS cell_counts (
    hour     timestamptz NOT NULL,
    cell_lat int NOT NULL,
    cell_lng int NOT NULL,
    category text NOT NULL,
    count    bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (hour, cell_lat, cell_lng, category)
);
`

func (s *Store) migrate(ctx context.Context) error {
	conn, err := s.pool.Acquire(ctx)
	if err != nil {
		return err
	}
	defer conn.Release()
	const lockID = 727002
	if _, err := conn.Exec(ctx, "SELECT pg_advisory_lock($1)", lockID); err != nil {
		return err
	}
	defer conn.Exec(context.Background(), "SELECT pg_advisory_unlock($1)", lockID)
	_, err = conn.Exec(ctx, schema)
	return err
}

// Event is the subset of the stream payload analytics needs.
type Event struct {
	EventID   string
	Type      string
	Category  string
	City      string
	State     string
	Latitude  float64
	Longitude float64
	OldStatus string
	NewStatus string
	CreatedAt time.Time
	ChangedAt time.Time
}

func istDay(t time.Time) time.Time {
	y, m, d := t.In(IST).Date()
	return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) // date column: only Y-M-D matters
}

func cellOf(v float64) int { return int(math.Floor(v / CellSize)) }

// Apply folds one event into the rollups. It is idempotent: the processed_events
// insert and the counter updates share one transaction, so a redelivered event
// changes nothing.
func (s *Store) Apply(ctx context.Context, ev Event) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	tag, err := tx.Exec(ctx,
		"INSERT INTO processed_events (event_id) VALUES ($1) ON CONFLICT DO NOTHING", ev.EventID)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return nil // already counted
	}

	switch ev.Type {
	case "ReportCreated":
		if err := bumpDaily(ctx, tx, istDay(ev.CreatedAt), ev, 1, 0, 0); err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `
			INSERT INTO cell_counts (hour, cell_lat, cell_lng, category, count)
			VALUES ($1,$2,$3,$4,1)
			ON CONFLICT (hour, cell_lat, cell_lng, category)
			DO UPDATE SET count = cell_counts.count + 1`,
			ev.CreatedAt.UTC().Truncate(time.Hour), cellOf(ev.Latitude), cellOf(ev.Longitude), ev.Category)
		if err != nil {
			return err
		}
	case "ReportStatusChanged":
		if ev.NewStatus == "RESOLVED" && ev.OldStatus != "RESOLVED" {
			secs := ev.ChangedAt.Sub(ev.CreatedAt).Seconds()
			if secs < 0 {
				secs = 0
			}
			if err := bumpDaily(ctx, tx, istDay(ev.ChangedAt), ev, 0, 1, secs); err != nil {
				return err
			}
		}
	}
	return tx.Commit(ctx)
}

func bumpDaily(ctx context.Context, tx pgx.Tx, day time.Time, ev Event, created, resolved int, secs float64) error {
	_, err := tx.Exec(ctx, `
		INSERT INTO daily_counts (day, state, city, category, created, resolved, resolve_seconds)
		VALUES ($1,$2,$3,$4,$5,$6,$7)
		ON CONFLICT (day, state, city, category) DO UPDATE SET
		    created = daily_counts.created + EXCLUDED.created,
		    resolved = daily_counts.resolved + EXCLUDED.resolved,
		    resolve_seconds = daily_counts.resolve_seconds + EXCLUDED.resolve_seconds`,
		day, ev.State, ev.City, ev.Category, created, resolved, secs)
	return err
}

// Prune bounds table growth.
func (s *Store) Prune(ctx context.Context) error {
	if _, err := s.pool.Exec(ctx, "DELETE FROM processed_events WHERE processed_at < now() - interval '14 days'"); err != nil {
		return err
	}
	_, err := s.pool.Exec(ctx, "DELETE FROM cell_counts WHERE hour < now() - interval '30 days'")
	return err
}

// ---- queries ----

type Bucket struct {
	Name     string  `json:"name"`
	Created  int64   `json:"created"`
	Resolved int64   `json:"resolved"`
	AvgHours float64 `json:"avg_resolve_hours"`
	Rate     float64 `json:"resolution_rate"`
}

type Summary struct {
	Days       int      `json:"days"`
	Created    int64    `json:"created"`
	Resolved   int64    `json:"resolved"`
	Rate       float64  `json:"resolution_rate"`
	AvgHours   float64  `json:"avg_resolve_hours"`
	ByCategory []Bucket `json:"by_category"`
	TopStates  []Bucket `json:"top_states"`
}

func ratio(a, b float64) float64 {
	if b == 0 {
		return 0
	}
	return a / b
}

func (s *Store) buckets(ctx context.Context, col string, days, limit, minCreated int) ([]Bucket, error) {
	// col is chosen by the caller from a fixed list, never from user input.
	rows, err := s.pool.Query(ctx, fmt.Sprintf(`
		SELECT %[1]s, sum(created), sum(resolved), sum(resolve_seconds)
		FROM daily_counts
		WHERE day >= (now() AT TIME ZONE 'Asia/Kolkata')::date - $1::int
		GROUP BY %[1]s HAVING sum(created) >= $3
		ORDER BY sum(created) DESC LIMIT $2`, col), days, limit, minCreated)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Bucket{}
	for rows.Next() {
		var b Bucket
		var secs float64
		if err := rows.Scan(&b.Name, &b.Created, &b.Resolved, &secs); err != nil {
			return nil, err
		}
		b.Rate = ratio(float64(b.Resolved), float64(b.Created))
		b.AvgHours = ratio(secs, float64(b.Resolved)) / 3600
		out = append(out, b)
	}
	return out, rows.Err()
}

func (s *Store) Summary(ctx context.Context, days int) (Summary, error) {
	sum := Summary{Days: days}
	var secs float64
	err := s.pool.QueryRow(ctx, `
		SELECT COALESCE(sum(created),0), COALESCE(sum(resolved),0), COALESCE(sum(resolve_seconds),0)
		FROM daily_counts WHERE day >= (now() AT TIME ZONE 'Asia/Kolkata')::date - $1::int`, days,
	).Scan(&sum.Created, &sum.Resolved, &secs)
	if err != nil {
		return sum, err
	}
	sum.Rate = ratio(float64(sum.Resolved), float64(sum.Created))
	sum.AvgHours = ratio(secs, float64(sum.Resolved)) / 3600
	if sum.ByCategory, err = s.buckets(ctx, "category", days, 20, 1); err != nil {
		return sum, err
	}
	sum.TopStates, err = s.buckets(ctx, "state", days, 10, 1)
	return sum, err
}

// Leaderboard ranks states or cities by resolution rate; tiny samples are excluded.
func (s *Store) Leaderboard(ctx context.Context, by string, days, minCreated int) ([]Bucket, error) {
	col := "state"
	if by == "city" {
		col = "city"
	}
	list, err := s.buckets(ctx, col, days, 200, minCreated)
	if err != nil {
		return nil, err
	}
	// Sort by resolution rate, then by volume.
	for i := 1; i < len(list); i++ {
		for j := i; j > 0 && (list[j].Rate > list[j-1].Rate ||
			(list[j].Rate == list[j-1].Rate && list[j].Created > list[j-1].Created)); j-- {
			list[j], list[j-1] = list[j-1], list[j]
		}
	}
	if len(list) > 20 {
		list = list[:20]
	}
	return list, nil
}

type Point struct {
	Day      string `json:"day"`
	Created  int64  `json:"created"`
	Resolved int64  `json:"resolved"`
}

func (s *Store) Trends(ctx context.Context, days int, state, category string) ([]Point, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT d::date, COALESCE(sum(c.created),0), COALESCE(sum(c.resolved),0)
		FROM generate_series((now() AT TIME ZONE 'Asia/Kolkata')::date - $1::int,
		                     (now() AT TIME ZONE 'Asia/Kolkata')::date, interval '1 day') d
		LEFT JOIN daily_counts c ON c.day = d::date
		     AND ($2 = '' OR c.state = $2) AND ($3 = '' OR c.category = $3)
		GROUP BY d ORDER BY d`, days, state, category)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Point{}
	for rows.Next() {
		var p Point
		var day time.Time
		if err := rows.Scan(&day, &p.Created, &p.Resolved); err != nil {
			return nil, err
		}
		p.Day = day.Format("2006-01-02")
		out = append(out, p)
	}
	return out, rows.Err()
}

type Hotspot struct {
	Latitude    float64 `json:"latitude"`
	Longitude   float64 `json:"longitude"`
	Last24h     int64   `json:"last_24h"`
	DailyAvg7d  float64 `json:"daily_avg_prev_7d"`
	Score       float64 `json:"score"`
	TopCategory string  `json:"top_category"`
}

// Hotspots finds ~5 km cells whose last-24h volume is well above their own recent
// baseline. Cells with little history need a higher absolute count to qualify.
func (s *Store) Hotspots(ctx context.Context, limit, minCount int) ([]Hotspot, error) {
	rows, err := s.pool.Query(ctx, `
		WITH recent AS (
		    SELECT cell_lat, cell_lng, sum(count) AS c
		    FROM cell_counts WHERE hour >= now() - interval '24 hours'
		    GROUP BY cell_lat, cell_lng
		), base AS (
		    SELECT cell_lat, cell_lng, sum(count) / 7.0 AS daily
		    FROM cell_counts
		    WHERE hour >= now() - interval '8 days' AND hour < now() - interval '24 hours'
		    GROUP BY cell_lat, cell_lng
		)
		SELECT r.cell_lat, r.cell_lng, r.c, COALESCE(b.daily, 0),
		       r.c / GREATEST(COALESCE(b.daily, 0), 1.0) AS score,
		       (SELECT category FROM cell_counts k
		         WHERE k.cell_lat = r.cell_lat AND k.cell_lng = r.cell_lng
		           AND k.hour >= now() - interval '24 hours'
		         GROUP BY category ORDER BY sum(count) DESC LIMIT 1)
		FROM recent r LEFT JOIN base b USING (cell_lat, cell_lng)
		WHERE r.c >= $2
		ORDER BY score DESC, r.c DESC
		LIMIT $1`, limit, minCount)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Hotspot{}
	for rows.Next() {
		var h Hotspot
		var cellLat, cellLng int
		if err := rows.Scan(&cellLat, &cellLng, &h.Last24h, &h.DailyAvg7d, &h.Score, &h.TopCategory); err != nil {
			return nil, err
		}
		h.Latitude = (float64(cellLat) + 0.5) * CellSize
		h.Longitude = (float64(cellLng) + 0.5) * CellSize
		out = append(out, h)
	}
	return out, rows.Err()
}
