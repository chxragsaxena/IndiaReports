// Mixed workload against report-service. Run: see docs/LOADTEST.md
import http from "k6/http";
import { check } from "k6";
import { Counter, Trend } from "k6/metrics";

// Diagnostics: every response counted by endpoint and status (shown in the summary).
const outcomes = new Counter("outcomes");

const BASE = __ENV.BASE_URL || "http://localhost:8000";
const VUS = Number(__ENV.VUS || 100);

const clusterMs = new Trend("clusters_ms", true);
const pinsMs = new Trend("pins_ms", true);
const dashMs = new Trend("dashboard_ms", true);
const writeMs = new Trend("write_ms", true);

export const options = {
  scenarios: {
    mixed: {
      executor: "ramping-vus",
      stages: [
        { duration: "10s", target: VUS },
        { duration: "40s", target: VUS },
        { duration: "5s", target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<500"],
  },
};

const CITIES = [
  [28.61, 77.21], [19.07, 72.87], [12.97, 77.59], [17.38, 78.48], [13.08, 80.27],
  [18.52, 73.85], [22.57, 88.36], [23.02, 72.57], [26.91, 75.78], [23.25, 77.41],
];
const CATEGORIES = ["Road", "Garbage", "Electricity", "Water Supply", "Fire"];

function pick(a) { return a[Math.floor(Math.random() * a.length)]; }

export default function () {
  const r = Math.random();
  // NOTE: pins use the lightweight endpoint (the map no longer downloads full records).
  if (r < 0.45) {
    // Zoomed-out map: clusters over a viewport. Several users share cache entries.
    const zoom = 4 + Math.floor(Math.random() * 3);
    const [lat, lng] = pick(CITIES);
    const span = 12 / (zoom - 2);
    const f = Math.random() < 0.3 ? `&category=${pick(CATEGORIES)}` : "";
    const res = http.get(`${BASE}/api/v1/reports/clusters?min_lat=${lat - span}&max_lat=${lat + span}&min_lng=${lng - span}&max_lng=${lng + span}&zoom=${zoom}${f}`);
    clusterMs.add(res.timings.duration);
    outcomes.add(1, { endpoint: "clusters", status: String(res.status) });
    check(res, { "clusters 200": (x) => x.status === 200 });
  } else if (r < 0.80) {
    // Zoomed-in map: individual pins in a small viewport.
    const [lat, lng] = pick(CITIES);
    const d = 0.05 + Math.random() * 0.1;
    const res = http.get(`${BASE}/api/v1/reports/pins?min_lat=${lat - d}&max_lat=${lat + d}&min_lng=${lng - d}&max_lng=${lng + d}`);
    pinsMs.add(res.timings.duration);
    outcomes.add(1, { endpoint: "pins", status: String(res.status) });
    check(res, { "pins 200": (x) => x.status === 200 });
  } else if (r < 0.92) {
    const res = http.get(`${BASE}/api/v1/reports/dashboard`);
    dashMs.add(res.timings.duration);
    outcomes.add(1, { endpoint: "dashboard", status: String(res.status) });
    check(res, { "dashboard 200": (x) => x.status === 200 });
  } else {
    const [lat, lng] = pick(CITIES);
    const res = http.post(`${BASE}/api/v1/reports/`, JSON.stringify({
      title: "Load test report", description: "created by the load test", category: pick(CATEGORIES),
      latitude: lat + (Math.random() - 0.5) * 0.1, longitude: lng + (Math.random() - 0.5) * 0.1,
      address: "x", landmark: "y", city: "Test", district: "Test", state: "Test", pincode: "110001",
    }), { headers: { "Content-Type": "application/json", "X-Forwarded-For": `10.${Math.floor(Math.random()*250)}.${Math.floor(Math.random()*250)}.${Math.floor(Math.random()*250)}` } });
    writeMs.add(res.timings.duration);
    outcomes.add(1, { endpoint: "write", status: String(res.status) });
    check(res, { "write 201": (x) => x.status === 201 });
  }
}
