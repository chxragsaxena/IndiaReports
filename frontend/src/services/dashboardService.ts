import { API_URL } from "../config/api";

export interface DashboardData {
    total_reports: number;
    open_reports: number;
    in_progress_reports: number;
    resolved_reports: number;
    recent_reports: any[];
}

export async function getDashboard(): Promise<DashboardData> {
    const response = await fetch(
        `${API_URL}/api/v1/reports/dashboard`
    );

    if (!response.ok) {
        throw new Error("Failed to fetch dashboard.");
    }

    return await response.json();
}