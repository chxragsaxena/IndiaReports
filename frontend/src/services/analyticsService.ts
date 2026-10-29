import axios from "axios";
import { ANALYTICS_URL } from "../config/api";

// The analytics service is optional: callers treat a rejected promise as "no data".

export interface Bucket {
    name: string;
    created: number;
    resolved: number;
    avg_resolve_hours: number;
    resolution_rate: number;
}

export interface Summary {
    days: number;
    created: number;
    resolved: number;
    resolution_rate: number;
    avg_resolve_hours: number;
    by_category: Bucket[];
    top_states: Bucket[];
}

export interface TrendPoint {
    day: string;
    created: number;
    resolved: number;
}

export interface Hotspot {
    latitude: number;
    longitude: number;
    last_24h: number;
    daily_avg_prev_7d: number;
    score: number;
    top_category: string;
}

export const analyticsEnabled = ANALYTICS_URL !== "";

async function get<T>(path: string, params: Record<string, string | number>, signal?: AbortSignal): Promise<T> {
    const response = await axios.get<T>(`${ANALYTICS_URL}${path}`, { params, signal, timeout: 10000 });
    return response.data;
}

export const getSummary = (days: number, signal?: AbortSignal) =>
    get<Summary>("/v1/summary", { days }, signal);

export const getTrends = (days: number, signal?: AbortSignal) =>
    get<TrendPoint[]>("/v1/trends", { days }, signal);

export const getHotspots = (signal?: AbortSignal) =>
    get<Hotspot[]>("/v1/hotspots", { limit: 6, min_count: 3 }, signal);

export const getLeaderboard = (days: number, signal?: AbortSignal) =>
    get<Bucket[]>("/v1/leaderboard", { by: "state", days, min_reports: 1 }, signal);
