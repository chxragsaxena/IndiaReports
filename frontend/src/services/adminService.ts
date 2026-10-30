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
    resolved_at: string | null;
    archived_at: string | null;
    resolution_note: string | null;
    /** When it must be resolved by before it escalates. Null once resolved or escalated. */
    due_at: string | null;
    overdue: boolean;
    assignee_name: string | null;
    assignee_role: string | null;
    image_count: number;
    ai_severity: Severity | null;
    ai_pending: boolean;
    ai_urgency: Severity | null;
    ai_spam: boolean;
    language: string | null;
}

export interface AdminReportPage {
    items: AdminReport[];
    next_before: string | null;
}

export interface Officer {
    id: string;
    name: string;
    role: string;
    telegram_chat_id: string | null;
    area_id: string | null;
    area_name: string | null;
    /** The account they sign in with. */
    email: string | null;
    active: boolean;
}

export interface Area {
    id: string;
    name: string;
}

/** Who is signed in as staff, and what their scope is. */
export interface StaffProfile {
    is_main: boolean;
    name: string | null;
    area_id: string | null;
    area_name: string | null;
    resolve_within_seconds: number;
    resolved_visible_seconds: number;
}

export type AdminFilter = "todo" | "overdue" | "escalated" | "all" | "IN_PROGRESS" | "RESOLVED";

export async function getStaffProfile(): Promise<StaffProfile> {
    return (await client.get<StaffProfile>("/admin/me")).data;
}

export async function listOfficers(): Promise<Officer[]> {
    return (await client.get<Officer[]>("/admin/officers")).data;
}

export async function listAreas(): Promise<Area[]> {
    return (await client.get<Area[]>("/admin/areas")).data;
}

export interface NewOfficer {
    name: string;
    area_id: string;
    email: string;
    /** Only needed when the email has no account yet. */
    password?: string;
    telegram_chat_id?: string;
}

export async function createOfficer(officer: NewOfficer): Promise<Officer> {
    const body = { ...officer, role: "officer", password: officer.password || undefined, telegram_chat_id: officer.telegram_chat_id || undefined };
    return (await client.post<Officer>("/admin/officers", body)).data;
}

/** Give an existing officer an account to sign in with (links it if the email already has one). */
export async function setOfficerAccount(officerId: string, email: string, password?: string): Promise<Officer> {
    return (
        await client.put<Officer>(`/admin/officers/${encodeURIComponent(officerId)}/account`, {
            email,
            password: password || undefined,
        })
    ).data;
}

/** `geometry` is a GeoJSON Polygon or MultiPolygon in [longitude, latitude] order. */
export async function createArea(name: string, geometry: unknown): Promise<Area> {
    return (await client.post<Area>("/admin/areas", { name, geometry })).data;
}

export async function listAdminReports(filter: AdminFilter, before?: string | null): Promise<AdminReportPage> {
    const params: Record<string, string | boolean | number> = { limit: 25 };
    if (filter === "todo") params.unresolved = true;
    else if (filter === "overdue") params.overdue = true;
    else if (filter === "escalated") params.escalated = true;
    else if (filter !== "all") params.status = filter;
    if (before) params.before = before;
    return (await client.get<AdminReportPage>("/admin/reports", { params })).data;
}

/** Move a report along. Resolving takes a note for the citizen, who is also emailed. */
export async function updateStatus(id: string, status: ReportStatus, note?: string): Promise<void> {
    await client.patch(`/reports/${encodeURIComponent(id)}/status`, { status, note: note?.trim() || null });
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
    assigned_at: string | null;
    due_at: string | null;
    acknowledged_at: string | null;
    escalated_at: string | null;
    resolved_at: string | null;
    resolution_note: string | null;
    assignee_name: string | null;
    images: AdminImage[];
    analysis_enabled: boolean;
    triage: Triage | null;
}

/** What the ai-service made of the report text. Assistive, for staff only. */
export interface Triage {
    language: string;
    title_en: string;
    description_en: string;
    suggested_category: string;
    category_matches_report: boolean;
    urgency: Severity;
    is_spam: boolean;
    spam_reason: string;
    summary: string;
    confidence: number;
    provider: string;
    model: string;
}

export async function getAdminReport(id: string, signal?: AbortSignal): Promise<AdminReportDetail> {
    return (await client.get<AdminReportDetail>(`/admin/reports/${encodeURIComponent(id)}`, { signal })).data;
}
