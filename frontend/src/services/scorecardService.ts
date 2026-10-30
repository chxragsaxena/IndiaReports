import axios from "axios";
import { API_URL } from "../config/api";

export interface AreaScore {
    area_id: string;
    area: string;
    officers: string[];
    received: number;
    resolved: number;
    open_now: number;
    late_open: number;
    escalated: number;
    reopened: number;
    /** Share of reports with a decided deadline that were resolved in time, 0 to 1. Null until something is judged. */
    in_time_rate: number | null;
    /** Share of ever-resolved reports the reporter said were not fixed, 0 to 1. */
    reopen_rate: number | null;
    median_resolution_hours: number | null;
    /** Enough judged reports for the percentage to mean something. */
    ranked: boolean;
}

export interface Scorecards {
    resolve_within_days: number;
    min_ranked: number;
    areas: AreaScore[];
}

export async function getScorecards(signal?: AbortSignal): Promise<Scorecards> {
    return (await axios.get<Scorecards>(`${API_URL}/api/v1/scorecards`, { signal, timeout: 60000 })).data;
}
