import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { useAuth } from "../../auth/AuthContext";
import Button from "../../components/UI/Button/Button";
import Skeleton from "../../components/UI/Skeleton/Skeleton";
import { StatusBadge, Tag } from "../../components/UI/Badge/Badge";
import { useToast } from "../../components/UI/Toast/Toast";
import { ESCALATION_DAYS } from "../../config/api";
import { useLiveSocket } from "../../hooks/useLiveSocket";
import { listAdminReports, listOfficers, updateStatus } from "../../services/adminService";
import type { AdminFilter, AdminReport, Officer } from "../../services/adminService";
import { apiErrorMessage } from "../../services/reportService";
import { STATUS_LABEL } from "../../types/report";
import type { ReportStatus } from "../../types/report";
import { timeAgo } from "../../utils/format";
import styles from "./Admin.module.css";

const FILTERS: { value: AdminFilter; label: string }[] = [
    { value: "attention", label: "Needs attention" },
    { value: "escalated", label: "Escalated" },
    { value: "OPEN", label: "Open" },
    { value: "IN_PROGRESS", label: "In progress" },
    { value: "RESOLVED", label: "Resolved" },
    { value: "all", label: "All" },
];

// Whole of India. Zoomed out, the server only sends a throttled "something changed"
// hint, which is exactly what a list that reloads itself needs.
const INDIA_VIEW: [number, number, number, number] = [68, 6, 98, 37];

function progress(r: AdminReport, now: number): { text: string; tone: "ok" | "wait" | "alert" } {
    if (r.escalated_at) return { text: "Escalated to the administrator", tone: "alert" };
    if (r.acknowledged_at) return { text: `Acknowledged ${timeAgo(r.acknowledged_at, now)}`, tone: "ok" };
    if (!r.assigned_at) return { text: "Not assigned", tone: "wait" };
    const left = Math.ceil((new Date(r.assigned_at).getTime() + ESCALATION_DAYS * 86_400_000 - now) / 86_400_000);
    return {
        text: left > 0 ? `Awaiting acknowledgement, escalates in ${left} d` : "Escalating now",
        tone: "wait",
    };
}

function Admin() {
    const toast = useToast();
    const { user } = useAuth();
    const [filter, setFilter] = useState<AdminFilter>("attention");
    const [rows, setRows] = useState<AdminReport[]>([]);
    const [next, setNext] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [officers, setOfficers] = useState<Officer[]>([]);
    const [reload, setReload] = useState(0);
    const firstLoad = useRef(true);

    // Live updates: any new report or change reloads the list (the server throttles hints).
    const { status: liveStatus, setViewport } = useLiveSocket({
        onReport: () => setReload((n) => n + 1),
        onRefresh: () => setReload((n) => n + 1),
    });
    useEffect(() => setViewport(INDIA_VIEW, 4), [setViewport]);

    const fail = useCallback((err: unknown) => toast.show(apiErrorMessage(err), "error"), [toast]);

    useEffect(() => {
        let cancelled = false;
        // Reloads caused by live events should not flash the skeleton.
        if (firstLoad.current || reload === 0) setLoading(true);
        listAdminReports(filter)
            .then((page) => {
                if (cancelled) return;
                setRows(page.items);
                setNext(page.next_before);
            })
            .catch(fail)
            .finally(() => {
                firstLoad.current = false;
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [filter, reload, fail]);

    useEffect(() => {
        listOfficers().then(setOfficers).catch(() => undefined);
    }, []);

    async function loadMore() {
        if (!next) return;
        setLoadingMore(true);
        try {
            const page = await listAdminReports(filter, next);
            setRows((current) => [...current, ...page.items]);
            setNext(page.next_before);
        } catch (err) {
            fail(err);
        } finally {
            setLoadingMore(false);
        }
    }

    async function changeStatus(report: AdminReport, status: ReportStatus) {
        try {
            await updateStatus(report.id, status);
            setRows((current) =>
                current.map((r) =>
                    r.id === report.id
                        ? { ...r, status, acknowledged_at: r.acknowledged_at ?? new Date().toISOString() }
                        : r,
                ),
            );
            toast.show(`Marked ${STATUS_LABEL[status].toLowerCase()}`, "success");
        } catch (err) {
            fail(err);
        }
    }

    const now = Date.now();

    return (
        <div className={styles.page}>
            <header className={styles.header}>
                <div>
                    <h1>Administration</h1>
                    <p className={styles.sub}>
                        Signed in as {user?.name} &middot; {officers.filter((o) => o.role === "officer").length} area officers
                        &middot; {officers.some((o) => o.role === "admin") ? "main admin set" : "no main admin set"}
                    </p>
                </div>
                <div className={styles.headerSide}>
                    <span className={styles.live} role="status">
                        <span className={`${styles.liveDot} ${styles[liveStatus]}`} aria-hidden="true" />
                        {liveStatus === "live" ? "Live" : liveStatus === "off" ? "Live updates off" : "Connecting"}
                    </span>
                    <Link to="/dashboard">Insights</Link>
                </div>
            </header>

            <div className={styles.filters} role="group" aria-label="Filter reports">
                {FILTERS.map((f) => (
                    <button
                        key={f.value}
                        className={f.value === filter ? styles.filterActive : styles.filter}
                        onClick={() => setFilter(f.value)}
                        aria-pressed={f.value === filter}
                    >
                        {f.label}
                    </button>
                ))}
            </div>

            <div className={styles.tableWrap}>
                <table className={styles.table}>
                    <thead>
                        <tr>
                            <th scope="col">Report</th>
                            <th scope="col">Where</th>
                            <th scope="col">Sent to</th>
                            <th scope="col">Progress</th>
                            <th scope="col">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading &&
                            [0, 1, 2, 3].map((i) => (
                                <tr key={i}>
                                    <td colSpan={5}>
                                        <Skeleton height={34} />
                                    </td>
                                </tr>
                            ))}
                        {!loading && rows.length === 0 && (
                            <tr>
                                <td colSpan={5} className={styles.empty}>
                                    Nothing here. {filter === "attention" ? "Every open report has been acknowledged." : ""}
                                </td>
                            </tr>
                        )}
                        {!loading &&
                            rows.map((r) => {
                                const p = progress(r, now);
                                return (
                                    <tr key={r.id}>
                                        <th scope="row">
                                            <Link
                                                className={styles.title}
                                                to={`/?report=${r.id}&lat=${r.latitude}&lng=${r.longitude}&z=14`}
                                            >
                                                {r.title}
                                            </Link>
                                            <span className={styles.meta}>
                                                <Tag>{r.category}</Tag> {timeAgo(r.created_at, now)}
                                            </span>
                                        </th>
                                        <td>{[r.city, r.state].filter(Boolean).join(", ")}</td>
                                        <td>
                                            {r.assignee_name ?? <span className={styles.muted}>Nobody</span>}
                                            {r.assignee_role === "admin" && <span className={styles.muted}> (admin)</span>}
                                        </td>
                                        <td className={styles[p.tone]}>{p.text}</td>
                                        <td>
                                            <div className={styles.statusCell}>
                                                <StatusBadge status={r.status} />
                                                <select
                                                    className={styles.select}
                                                    aria-label={`Change status of ${r.title}`}
                                                    value={r.status}
                                                    onChange={(e) => changeStatus(r, e.target.value as ReportStatus)}
                                                >
                                                    {(Object.keys(STATUS_LABEL) as ReportStatus[]).map((s) => (
                                                        <option key={s} value={s}>
                                                            {STATUS_LABEL[s]}
                                                        </option>
                                                    ))}
                                                </select>
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                    </tbody>
                </table>
            </div>

            {next && (
                <div className={styles.more}>
                    <Button variant="secondary" onClick={loadMore} loading={loadingMore}>
                        Load older reports
                    </Button>
                </div>
            )}
        </div>
    );
}

export default Admin;
