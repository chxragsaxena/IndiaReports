// Service endpoints. In production these come from Vercel environment variables.
// In development they default to the local docker compose ports.

function fromEnv(value: string | undefined, devDefault: string): string {
    const resolved = value ?? (import.meta.env.DEV ? devDefault : "");
    return resolved.replace(/\/+$/, "");
}

/** report-service (Python/FastAPI) */
export const API_URL = fromEnv(import.meta.env.VITE_API_URL, "http://localhost:8000");

/** notifier (Go): WebSocket live updates + alert subscriptions. Optional. */
export const NOTIFIER_URL = fromEnv(import.meta.env.VITE_NOTIFIER_URL, "http://localhost:8100");

/** analytics (Go): trends, hotspots, leaderboard. Optional. */
export const ANALYTICS_URL = fromEnv(import.meta.env.VITE_ANALYTICS_URL, "http://localhost:8200");

export const MAP_STYLE: string =
    import.meta.env.VITE_MAP_STYLE || "https://tiles.openfreemap.org/styles/positron";

/** Days an officer has to acknowledge a report before it escalates to the admin. */
export const ESCALATION_DAYS = Number(import.meta.env.VITE_ESCALATION_DAYS ?? 7);

export function toWebSocketUrl(httpUrl: string): string {
    return httpUrl.replace(/^http/, "ws");
}
