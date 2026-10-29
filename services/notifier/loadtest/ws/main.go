// WebSocket soak test for the notifier: many concurrent map viewers, then new reports.
//
//	go run ./loadtest/ws -n 5000 -notifier http://localhost:8110 -reports http://localhost:8010
//
// It opens N connections (each registers a viewport somewhere in Mumbai, zoomed in),
// files a handful of reports inside that area through report-service, and measures how
// long each report takes to arrive at every viewer that should see it.
package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"math/rand"
	"net/http"
	"os"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"
)

func main() {
	n := flag.Int("n", 2000, "concurrent WebSocket clients")
	notifier := flag.String("notifier", "http://localhost:8110", "notifier base URL")
	reports := flag.String("reports", "http://localhost:8010", "report-service base URL")
	events := flag.Int("events", 10, "reports to file")
	flag.Parse()

	wsURL := "ws" + strings.TrimPrefix(*notifier, "http") + "/ws"
	title := fmt.Sprintf("wsload-%d", time.Now().UnixNano())

	var connected, failed, closed atomic.Int64
	var mu sync.Mutex
	arrivals := map[string][]time.Time{} // report title -> arrival times
	var wg sync.WaitGroup
	stop := make(chan struct{})

	// Ramp up so the test measures steady state, not a connection storm.
	for i := 0; i < *n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
			if err != nil {
				failed.Add(1)
				return
			}
			defer conn.Close()
			// Every viewer watches a ~0.3 degree window containing the test reports.
			dx, dy := rand.Float64()*0.05, rand.Float64()*0.05
			_ = conn.WriteJSON(map[string]any{
				"type": "viewport", "zoom": 12,
				"bbox": []float64{72.70 + dx, 18.95 + dy, 73.05 + dx, 19.25 + dy},
			})
			connected.Add(1)
			go func() { <-stop; conn.Close() }()
			for {
				var m map[string]any
				if err := conn.ReadJSON(&m); err != nil {
					closed.Add(1)
					return
				}
				if m["type"] == "report" {
					now := time.Now()
					id, _ := m["report"].(map[string]any)["title"].(string)
					mu.Lock()
					arrivals[id] = append(arrivals[id], now)
					mu.Unlock()
				}
			}
		}()
		if i%250 == 249 {
			time.Sleep(200 * time.Millisecond)
		}
	}

	time.Sleep(3 * time.Second)
	fmt.Printf("connected=%d failed=%d\n", connected.Load(), failed.Load())

	var latencies []time.Duration
	for e := 0; e < *events; e++ {
		t := fmt.Sprintf("%s-%d", title, e)
		body, _ := json.Marshal(map[string]any{
			"title": t, "description": "websocket soak test", "category": "Road",
			"latitude": 19.07 + rand.Float64()*0.02, "longitude": 72.87 + rand.Float64()*0.02,
			"address": "x", "landmark": "y", "city": "Mumbai", "district": "Mumbai", "state": "Maharashtra", "pincode": "400001",
		})
		req, _ := http.NewRequest(http.MethodPost, *reports+"/api/v1/reports/", bytes.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-Forwarded-For", fmt.Sprintf("10.9.%d.%d", rand.Intn(250), rand.Intn(250)))
		sent := time.Now()
		resp, err := http.DefaultClient.Do(req)
		if err != nil || resp.StatusCode != http.StatusCreated {
			fmt.Println("create failed:", err, resp)
			os.Exit(1)
		}
		resp.Body.Close()
		time.Sleep(2500 * time.Millisecond)

		mu.Lock()
		got := arrivals[t]
		mu.Unlock()
		for _, a := range got {
			latencies = append(latencies, a.Sub(sent))
		}
		fmt.Printf("report %d delivered to %d of %d viewers\n", e+1, len(got), connected.Load())
	}

	sort.Slice(latencies, func(i, j int) bool { return latencies[i] < latencies[j] })
	pct := func(p float64) time.Duration {
		if len(latencies) == 0 {
			return 0
		}
		return latencies[int(float64(len(latencies)-1)*p)]
	}
	fmt.Printf("delivery latency (request sent -> viewer received) over %d deliveries: p50=%v p95=%v p99=%v max=%v\n",
		len(latencies), pct(0.50), pct(0.95), pct(0.99), pct(1.0))
	fmt.Printf("dropped connections during test: %d\n", closed.Load())
	close(stop)
	wg.Wait()
}
