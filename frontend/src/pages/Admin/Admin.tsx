import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import Button from "../../components/UI/Button/Button";
import Skeleton from "../../components/UI/Skeleton/Skeleton";
import AdminReportDetail from "../../components/AdminReportDetail/AdminReportDetail";
import { StatusBadge, SeverityBadge, Tag } from "../../components/UI/Badge/Badge";
import { useToast } from "../../components/UI/Toast/Toast";
import { useLiveSocket } from "../../hooks/useLiveSocket";
import { getStaffProfile, listAdminReports, updateStatus } from "../../services/adminService";
import type { AdminFilter, AdminReport, StaffProfile } from "../../services/adminService";
import { apiErrorMessage } from "../../services/reportService";
import type { ReportStatus } from "../../types/report";
import { formatDateTime, timeAgo } from "../../utils/format";
import ResolveDialog from "./ResolveDialog";
import styles from "./Admin.module.css";

const DAY = 86_400_000;

// Whole of India. Zoomed out, the server only sends a throttled "something changed"
// hint, which is exactly what a list that reloads itself needs.
const INDIA_VIEW: [number, number, number, number] = [68, 6, 98, 37];

type Tone = "ok" | "wait" | "alert";

/** What the Deadline column says: when it must be resolved by, or what happened to it. */
function deadline(r: AdminReport, visibleSeconds: number, now: number): { text: string; sub?: string; tone: Tone } {
    if (r.status === "RESOLVED") {
        const when = r.resolved_at ? `Resolved ${timeAgo(r.resolved_at, now)}` : "Resolved";
        if (r.archived_at) return { text: when, sub: "Off the public map", tone: "ok" };
        const left = r.resolved_at ? Math.ceil((new Date(r.resolved_at).getTime() + visibleSeconds * 1000 - now) / DAY) : 0;
        return {
            text: when,
            sub: left > 0 ? `On the map ${left} more day${left === 1 ? "" : "s"} for the citizen to check` : "Leaving the map soon",
            tone: "ok",
        };
    }
    if (r.escalated_at) return { text: "Escalated to the main administrator", sub: formatDateTime(r.escalated_at), tone: "alert" };
    if (!r.due_at) return { text: "Not assigned", tone: "wait" };

    const left = Math.ceil((new Date(r.due_at).getTime() - now) / DAY);
    if (r.overdue || left <= 0) return { text: "Overdue: escalating now", sub: `Was due ${formatDateTime(r.due_at)}`, tone: "alert" };
    return {
        text: `Due in ${left} day${left === 1 ? "" : "s"}`,
        sub: `Resolve by ${formatDateTime(r.due_at)}`,
        tone: left <= 2 ? "alert" : "wait",
    };
}

function Admin() {
    const toast = useToast();
    const [profile, setProfile] = useState<StaffProfile | null>(null);
    const [filter, setFilter] = useState<AdminFilter>("todo");
    const [rows, setRows] = useState<AdminReport[]>([]);
    const [next, setNext] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [reload, setReload] = useState(0);
    const [openId, setOpenId] = useState<string | null>(null);
    const [resolving, setResolving] = useState<AdminReport | null>(null);
    const firstLoad = useRef(true);

    // Live updates: any new report or change reloads the list (the server throttles hints).
    const { status: liveStatus, setViewport } = useLiveSocket({
        onReport: () => setReload((n) => n + 1),
        onRefresh: () => setReload((n) => n + 1),
    });
    useEffect(() => setViewport(INDIA_VIEW, 4), [setViewport]);

    const fail = useCallback((err: unknown) => toast.show(apiErrorMessage(err), "error"), [toast]);

    useEffect(() => {
        getStaffProfile().then(setProfile).catch(fail);
    }, [fail]);

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

    async function move(report: AdminReport, status: ReportStatus, note?: string): Promise<boolean> {
        try {
            await updateStatus(report.id, status, note);
            toast.show(
                status === "RESOLVED"
                    ? "Marked resolved. The citizen has been told."
                    : status === "IN_PROGRESS"
                      ? "Marked in progress"
                      : "Reopened",
                "success",
            );
            setReload((n) => n + 1);
            return true;
        } catch (err) {
            fail(err);
            return false;
        }
    }

    const now = Date.now();
    const isMain = profile?.is_main ?? false;
    const visibleSeconds = profile?.resolved_visible_seconds ?? 3 * 86_400;
    const resolveDays = profile ? Math.round(profile.resolve_within_seconds / 86_400) : 7;
    const visibleDays = Math.max(1, Math.round(visibleSeconds / 86_400));

    const filters: { value: AdminFilter; label: string }[] = [
        { value: "todo", label: "To do" },
        { value: "overdue", label: "Overdue" },
        ...(isMain ? [{ value: "escalated" as AdminFilter, label: "Escalated" }] : []),
        { value: "IN_PROGRESS", label: "In progress" },
        { value: "RESOLVED", label: "Resolved" },
        { value: "all", label: "All" },
    ];

    const columns = isMain ? 5 : 4;

    return (
        <div className={styles.page}>
            <header className={styles.header}>
                <div>
                    <h1>{isMain ? "Administration" : "Your queue"}</h1>
                    <p className={styles.sub}>
                        {!profile
                            ? "Loading..."
                            : isMain
                              ? `All areas. Officers have ${resolveDays} days to resolve a report; after that it comes to you.`
                              : `${profile.area_name ?? "Your area"}. Resolve each report within ${resolveDays} days of it arriving, or it is escalated to the main administrator.`}
                    </p>
                </div>
                <div className={styles.headerSide}>
                    <span className={styles.live} role="status">
                        <span className={`${styles.liveDot} ${styles[liveStatus]}`} aria-hidden="true" />
                        {liveStatus === "live" ? "Live" : liveStatus === "off" ? "Live updates off" : "Connecting"}
                    </span>
                    {isMain && <Link to="/admin/team">Team and areas</Link>}
                    <Link to="/dashboard">Insights</Link>
                </div>
            </header>

            <div className={styles.filters} role="group" aria-label="Filter reports">
                {filters.map((f) => (
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
                            {isMain && <th scope="col">Assigned to</th>}
                            <th scope="col">Deadline</th>
                            <th scope="col">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading &&
                            [0, 1, 2, 3].map((i) => (
                                <tr key={i}>
                                    <td colSpan={columns}>
                                        <Skeleton height={34} />
                                    </td>
                                </tr>
                            ))}
                        {!loading && rows.length === 0 && (
                            <tr>
                                <td colSpan={columns} className={styles.empty}>
                                    {filter === "todo"
                                        ? isMain
                                            ? "Nothing waiting. Every report has been resolved."
                                            : "Your queue is clear. New reports in your area will appear here."
                                        : "Nothing here."}
                                </td>
                            </tr>
                        )}
                        {!loading &&
                            rows.map((r) => {
                                const d = deadline(r, visibleSeconds, now);
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
                                            <span className={styles.meta}>
                                                <button className={styles.detailBtn} onClick={() => setOpenId(r.id)}>
                                                    {r.image_count > 0
                                                        ? `${r.image_count} photo${r.image_count === 1 ? "" : "s"}`
                                                        : "Details"}
                                                </button>
                                                {r.affected_count > 1 && <span className={styles.muted}>{r.affected_count} affected</span>}
                                                {r.ai_spam && <span className={styles.spam}>Possible spam</span>}
                                                {r.language && <span className={styles.muted}>{r.language}</span>}
                                                {r.ai_severity ? (
                                                    <SeverityBadge severity={r.ai_severity} prefix="AI:" />
                                                ) : r.ai_pending ? (
                                                    <span className={styles.muted}>AI analysing...</span>
                                                ) : null}
                                            </span>
                                        </th>
                                        <td>{[r.city, r.state].filter(Boolean).join(", ")}</td>
                                        {isMain && (
                                            <td>
                                                {r.assignee_name ?? <span className={styles.muted}>Nobody</span>}
                                                {r.assignee_role === "admin" && <span className={styles.muted}> (admin)</span>}
                                            </td>
                                        )}
                                        <td>
                                            <span className={styles[d.tone]}>{d.text}</span>
                                            {d.sub && <span className={styles.subline}>{d.sub}</span>}
                                            {r.resolution_note && <span className={styles.note}>&ldquo;{r.resolution_note}&rdquo;</span>}
                                        </td>
                                        <td>
                                            <div className={styles.statusCell}>
                                                <StatusBadge status={r.status} />
                                                <div className={styles.actions}>
                                                    {r.status === "OPEN" && (
                                                        <Button size="sm" variant="secondary" onClick={() => move(r, "IN_PROGRESS")}>
                                                            Start work
                                                        </Button>
                                                    )}
                                                    {r.status !== "RESOLVED" && (
                                                        <Button size="sm" onClick={() => setResolving(r)}>
                                                            Mark resolved
                                                        </Button>
                                                    )}
                                                    {r.status === "RESOLVED" && !r.archived_at && (
                                                        <Button size="sm" variant="ghost" onClick={() => move(r, "OPEN")}>
                                                            Reopen
                                                        </Button>
                                                    )}
                                                </div>
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                    </tbody>
                </table>
            </div>

            {openId && <AdminReportDetail key={openId} reportId={openId} onClose={() => setOpenId(null)} />}

            {resolving && (
                <ResolveDialog
                    title={resolving.title}
                    visibleDays={visibleDays}
                    onClose={() => setResolving(null)}
                    onSubmit={async (note) => {
                        if (await move(resolving, "RESOLVED", note)) setResolving(null);
                    }}
                />
            )}

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
