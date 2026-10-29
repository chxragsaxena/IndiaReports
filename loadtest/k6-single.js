// One endpoint at a time, to see what each path costs. Run: see docs/LOADTEST.md
import http from "k6/http";
import { check } from "k6";

const BASE = __ENV.BASE_URL || "http://localhost:8000";
const MODE = __ENV.MODE || "dashboard";

export const options = {
  vus: Number(__ENV.VUS || 100),
  duration: __ENV.DURATION || "10s",
};

function ip() { return `10.${Math.floor(Math.random()*250)}.${Math.floor(Math.random()*250)}.${Math.floor(Math.random()*250)}`; }

export default function () {
  let res;
  if (MODE === "dashboard") {
    res = http.get(`${BASE}/api/v1/reports/dashboard`);
  } else if (MODE === "pins-hit") {
    res = http.get(`${BASE}/api/v1/reports/pins?min_lat=28.55&max_lat=28.7&min_lng=77.1&max_lng=77.3`);
  } else if (MODE === "clusters-hit") {
    res = http.get(`${BASE}/api/v1/reports/clusters?min_lat=6&max_lat=38&min_lng=68&max_lng=98&zoom=4`);
  } else if (MODE === "write") {
    res = http.post(`${BASE}/api/v1/reports/`, JSON.stringify({
      title: "Load test report", description: "created by the load test", category: "Road",
      latitude: 19.0 + Math.random() * 0.2, longitude: 72.8 + Math.random() * 0.2,
      address: "x", landmark: "y", city: "Test", district: "Test", state: "Test", pincode: "110001",
    }), { headers: { "Content-Type": "application/json", "X-Forwarded-For": ip() } });
  } else if (MODE === "health") {
    res = http.get(`${BASE}/health`);
  }
  check(res, { ok: (r) => r.status === 200 || r.status === 201 });
}
