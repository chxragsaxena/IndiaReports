import axios, { isAxiosError } from "axios";
import type { NewReport, Pin, Report } from "../types/report";
import { API_URL } from "../config/api";
import { attachAuth } from "./session";

const api = axios.create({
    baseURL: `${API_URL}/api/v1`,
    // A free-tier server can take close to a minute to wake up; do not give up before it does.
    timeout: 60000,
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
    if (pinsEndpointMissing) return legacyPins(params, signal);
    try {
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
    } catch (err) {
        // A backend that has not been updated yet has no /pins. Fall back to the full-record
        // list it does have, so the map still shows reports instead of going blank.
        if (isAxiosError(err) && err.response?.status === 404) {
            pinsEndpointMissing = true;
            return legacyPins(params, signal);
        }
        throw err;
    }
}

let pinsEndpointMissing = false;

async function legacyPins(params: ViewportParams & FilterParams, signal?: AbortSignal): Promise<PinsResult> {
    const reports = await getReports(params, signal);
    return {
        truncated: reports.length >= 500,
        pins: reports.slice(0, 500).map((r) => ({
            id: r.id,
            status: r.status,
            latitude: r.latitude,
            longitude: r.longitude,
        })),
    };
}

/** The signed-in person's own reports, newest first. `before` pages to older ones. */
export async function getMyReports(before?: string | null, signal?: AbortSignal): Promise<Report[]> {
    const response = await api.get<Report[]>("/me/reports", { signal, params: { limit: 50, before: before ?? undefined } });
    return response.data;
}

/** The reporter says the fix is real; the report then leaves the public map. */
export async function confirmResolved(id: string): Promise<Report> {
    return (await api.post<Report>(`/reports/${encodeURIComponent(id)}/confirm`)).data;
}

/** The reporter says it is not fixed: it goes back to the responsible officer. */
export async function reopenReport(id: string, reason?: string): Promise<Report> {
    return (await api.post<Report>(`/reports/${encodeURIComponent(id)}/reopen`, { reason: reason?.trim() || null })).data;
}

export class PhotosUnavailableError extends Error {}

/** Attach one photo to a report you filed. Uploads can be slow on mobile, so allow a minute. */
export async function uploadReportPhoto(reportId: string, photo: Blob): Promise<void> {
    const form = new FormData();
    form.append("file", photo, "photo.jpg");
    try {
        await api.post(`/reports/${encodeURIComponent(reportId)}/images`, form, { timeout: 60000 });
    } catch (err) {
        if (isAxiosError(err) && err.response?.status === 503) throw new PhotosUnavailableError();
        throw err;
    }
}
