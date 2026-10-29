import axios from "axios";
import { API_URL } from "../config/api";
import type { Report } from "../types/report";

export interface DashboardData {
    total_reports: number;
    open_reports: number;
    in_progress_reports: number;
    resolved_reports: number;
    by_category: Record<string, number>;
    recent_reports: Report[];
}

export async function getDashboard(signal?: AbortSignal): Promise<DashboardData> {
    const response = await axios.get<DashboardData>(`${API_URL}/api/v1/reports/dashboard`, {
        signal,
        timeout: 60000,
    });
    return { ...response.data, by_category: response.data.by_category ?? {} };
}
