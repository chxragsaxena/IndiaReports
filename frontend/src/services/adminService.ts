import axios from "axios";
import { API_URL } from "../config/api";
import type { ReportStatus } from "../types/report";
import { attachAuth } from "./session";

// Authentication comes from the signed-in session (see session.ts); the server
// accepts these calls only from an administrator.
const client = axios.create({ baseURL: `${API_URL}/api/v1`, timeout: 15000 });
attachAuth(client);

export interface AdminReport {
    id: string;
    title: string;
    category: string;
    status: ReportStatus;
    city: string;
    state: string;
    latitude: number;
    longitude: number;
    created_at: string | null;
    assigned_at: string | null;
    acknowledged_at: string | null;
    escalated_at: string | null;
    assignee_name: string | null;
    assignee_role: string | null;
}

export interface AdminReportPage {
    items: AdminReport[];
    next_before: string | null;
}

export interface Officer {
    id: string;
    name: string;
    role: string;
    telegram_chat_id: string;
    area_id: string | null;
    active: boolean;
}

export type AdminFilter = "attention" | "escalated" | "all" | "OPEN" | "IN_PROGRESS" | "RESOLVED";

export async function listOfficers(): Promise<Officer[]> {
    return (await client.get<Officer[]>("/admin/officers")).data;
}

export async function listAdminReports(filter: AdminFilter, before?: string | null): Promise<AdminReportPage> {
    const params: Record<string, string | boolean | number> = { limit: 25 };
    if (filter === "attention") params.needs_attention = true;
    else if (filter === "escalated") params.escalated = true;
    else if (filter !== "all") params.status = filter;
    if (before) params.before = before;
    return (await client.get<AdminReportPage>("/admin/reports", { params })).data;
}

export async function updateStatus(id: string, status: ReportStatus): Promise<void> {
    await client.patch(`/reports/${encodeURIComponent(id)}/status`, { status });
}
