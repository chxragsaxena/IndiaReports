import axios, { isAxiosError } from "axios";
import type { NewReport, Pin, Report } from "../types/report";
import { API_URL } from "../config/api";
import { attachAuth } from "./session";

const api = axios.create({
    baseURL: `${API_URL}/api/v1`,
    timeout: 15000,
});
attachAuth(api);

interface ViewportParams {
    minLat: number;
    maxLat: number;
    minLng: number;
    maxLng: number;
}

interface FilterParams {
    status?: string;
    category?: string;
}

interface GetReportsParams extends Partial<ViewportParams>, FilterParams {
    limit?: number;
}

export interface Cluster {
    latitude: number;
    longitude: number;
    count: number;
}

/** Human-readable message from an API error (FastAPI validation errors included). */
export function apiErrorMessage(err: unknown, fallback = "Something went wrong. Please try again."): string {
    if (!isAxiosError(err)) return fallback;
    if (err.code === "ERR_NETWORK") return "Cannot reach the server. Check your connection.";
    const status = err.response?.status;
    const detail = err.response?.data?.detail;
    if (status === 429) return "Too many requests. Please wait a minute and try again.";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
        const first = detail[0] as { loc?: unknown[]; msg?: string };
        const field = Array.isArray(first.loc) ? String(first.loc[first.loc.length - 1]) : "";
        return field ? `${field}: ${first.msg ?? "invalid"}` : (first.msg ?? fallback);
    }
    return fallback;
}

export async function getReports(params?: GetReportsParams, signal?: AbortSignal): Promise<Report[]> {
    const response = await api.get<Report[]>("/reports/", {
        signal,
        params: {
            min_lat: params?.minLat,
            max_lat: params?.maxLat,
            min_lng: params?.minLng,
            max_lng: params?.maxLng,
            status: params?.status,
            category: params?.category,
            limit: params?.limit,
        },
    });

    return response.data;
}

export async function getClusters(
    params: ViewportParams & FilterParams & { zoom: number },
    signal?: AbortSignal,
): Promise<Cluster[]> {
    const response = await api.get<Cluster[]>("/reports/clusters", {
        signal,
        params: {
            min_lat: params.minLat,
            max_lat: params.maxLat,
            min_lng: params.minLng,
            max_lng: params.maxLng,
            zoom: params.zoom,
            status: params.status,
            category: params.category,
        },
    });

    return response.data;
}

export async function getReport(id: string, signal?: AbortSignal): Promise<Report> {
    const response = await api.get<Report>(`/reports/${encodeURIComponent(id)}`, { signal });
    return response.data;
}

export async function createReport(report: NewReport): Promise<Report> {
    const response = await api.post<Report>("/reports/", report);
    return response.data;
}

export async function acknowledgeReport(id: string, token: string): Promise<Report> {
    const response = await api.post<Report>(`/reports/${encodeURIComponent(id)}/acknowledge`, { token });
    return response.data;
}

export interface PinsResult {
    pins: Pin[];
    /** More reports exist in this view than were returned: zoom in to see them all. */
    truncated: boolean;
}

/** Lightweight pins for the map (a fraction of the size of full reports, and cached). */
export async function getPins(
    params: ViewportParams & FilterParams,
    signal?: AbortSignal,
): Promise<PinsResult> {
    const response = await api.get<PinsResult>("/reports/pins", {
        signal,
        params: {
            min_lat: params.minLat,
            max_lat: params.maxLat,
            min_lng: params.minLng,
            max_lng: params.maxLng,
            status: params.status,
            category: params.category,
        },
    });
    return response.data;
}

/** The signed-in person's own reports, newest first. `before` pages to older ones. */
export async function getMyReports(before?: string | null, signal?: AbortSignal): Promise<Report[]> {
    const response = await api.get<Report[]>("/me/reports", { signal, params: { limit: 50, before: before ?? undefined } });
    return response.data;
}
