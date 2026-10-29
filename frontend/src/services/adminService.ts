import axios from "axios";
import { API_URL } from "../config/api";
import type { ReportStatus } from "../types/report";
import { attachAuth } from "./session";

// Authentication comes from the signed-in session (see session.ts); the server
// accepts these calls only from an administrator.
const client = axios.create({ baseURL: `${API_URL}/api/v1`, timeout: 60000 });
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
    image_count: number;
    ai_severity: Severity | null;
    ai_pending: boolean;
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

export interface Findings {
    summary: string;
    issue_visible: boolean;
    suggested_category: string;
    category_matches_report: boolean;
    severity: Severity;
    hazards: string[];
    recommended_action: string;
    image_quality: string;
    flags: string[];
    confidence: number;
}

export type Severity = "low" | "medium" | "high" | "critical";

export interface AdminImage {
    id: string;
    url: string;
    width: number;
    height: number;
    status: "pending" | "analyzing" | "done" | "failed";
    severity: Severity | null;
    findings: Findings | null;
    provider: string | null;
    model: string | null;
    error: string | null;
    analyzed_at: string | null;
}

export interface AdminReportDetail {
    id: string;
    title: string;
    description: string;
    category: string;
    status: ReportStatus;
    address: string;
    city: string;
    district: string;
    state: string;
    pincode: string;
    latitude: number;
    longitude: number;
    created_at: string | null;
    images: AdminImage[];
    analysis_enabled: boolean;
}

export async function getAdminReport(id: string, signal?: AbortSignal): Promise<AdminReportDetail> {
    return (await client.get<AdminReportDetail>(`/admin/reports/${encodeURIComponent(id)}`, { signal })).data;
}
