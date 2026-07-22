import axios from "axios";
import type { Report } from "../types/report";
import { API_URL } from "../config/api";

const api = axios.create({
    baseURL: `${API_URL}/api/v1`,
});

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

interface GetReportsParams
    extends Partial<ViewportParams>,
        FilterParams {}

export interface Cluster {
    latitude: number;
    longitude: number;
    count: number;
}

export async function getReports(
    params?: GetReportsParams
): Promise<Report[]> {

    const response = await api.get("/reports/", {
        params: {
            min_lat: params?.minLat,
            max_lat: params?.maxLat,
            min_lng: params?.minLng,
            max_lng: params?.maxLng,
            status: params?.status,
            category: params?.category,
        },
    });

    return response.data;
}

export async function getClusters(
    params: ViewportParams &
        FilterParams & {
            zoom: number;
        }
): Promise<Cluster[]> {

    const response = await api.get("/reports/clusters", {
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

export async function createReport(report: {
    title: string;
    description: string;
    category: string;
    latitude: number;
    longitude: number;
    address: string;
    landmark: string;
    city: string;
    district: string;
    state: string;
    pincode: string;
}) {

    const response = await api.post(
        "/reports/",
        report
    );

    return response.data;
}