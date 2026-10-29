import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import Button from "../../components/UI/Button/Button";
import { TextArea } from "../../components/UI/Input/Input";
import Skeleton from "../../components/UI/Skeleton/Skeleton";
import { StatusBadge, Tag } from "../../components/UI/Badge/Badge";
import { useToast } from "../../components/UI/Toast/Toast";
import { apiErrorMessage, confirmResolved, getMyReports, reopenReport } from "../../services/reportService";
import type { Report } from "../../types/report";
import { formatDateTime, timeAgo } from "../../utils/format";
import styles from "./MyReports.module.css";

/** One plain sentence about where a report stands. */
function progressText(r: Report): string {
    if (r.status === "RESOLVED") {
        if (r.archived_at) return "Resolved. It has been taken off the public map.";
        if (r.confirmed_at) return "Resolved, and you confirmed it. It will leave the public map shortly.";
        return `Resolved ${timeAgo(r.resolved_at ?? r.updated_at)}.`;
    }
    if (r.escalated_at) return "It was not resolved in time, so it was escalated to the administrator.";
    if (r.status === "IN_PROGRESS") return "The responsible officer is working on it.";
    if (r.acknowledged_at) return "The responsible officer has seen it.";
    if (r.assigned_at) return "Sent to the responsible officer. Waiting for them to act.";
    return "Received.";
}

/** Whether the person can still check a resolved report (it is on the map and not yet closed). */
function canCheck(r: Report): boolean {
    return r.status === "RESOLVED" && !r.archived_at;
}

function MyReports() {
    const toast = useToast();
    const [reports, setReports] = useState<Report[]>([]);
    const [loading, setLoading] = useState(true);
    const [failed, setFailed] = useState(false);
    const [more, setMore] = useState(false);
    const [reopening, setReopening] = useState<string | null>(null);
    const [reason, setReason] = useState("");
    const [busy, setBusy] = useState<string | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        getMyReports(undefined, controller.signal)
            .then((list) => {
                setReports(list);
                setMore(list.length === 50);
            })
            .catch((err) => (err as { code?: string }).code !== "ERR_CANCELED" && setFailed(true))
            .finally(() => setLoading(false));
        return () => controller.abort();
    }, []);

    async function loadMore() {
        const last = reports[reports.length - 1]?.created_at;
        if (!last) return;
        const list = await getMyReports(last);
        setReports((current) => [...current, ...list]);
        setMore(list.length === 50);
    }

    function replace(updated: Report) {
        setReports((current) => current.map((r) => (r.id === updated.id ? updated : r)));
    }

    async function confirm(r: Report) {
        setBusy(r.id);
        try {
            replace(await confirmResolved(r.id));
            toast.show("Thank you for confirming.", "success");
        } catch (err) {
            toast.show(apiErrorMessage(err), "error");
        } finally {
            setBusy(null);
        }
    }

    async function reopen(r: Report) {
        setBusy(r.id);
        try {
            replace(await reopenReport(r.id, reason));
            setReopening(null);
            setReason("");
            toast.show("Reopened. It has gone back to the officer.", "success");
        } catch (err) {
            toast.show(apiErrorMessage(err), "error");
        } finally {
            setBusy(null);
        }
    }

    return (
        <div className={styles.page}>
            <header className={styles.header}>
                <div>
                    <h1>My reports</h1>
                    <p className={styles.sub}>The issues you have reported and what has happened to them.</p>
                </div>
                <Link to="/report" className={styles.cta}>
                    Report an issue
                </Link>
            </header>

            {loading && (
                <div className={styles.list}>
                    <Skeleton height={76} />
                    <Skeleton height={76} />
                </div>
            )}

            {failed && <p className={styles.empty}>Your reports could not be loaded. Please try again.</p>}

            {!loading && !failed && reports.length === 0 && (
                <div className={styles.emptyBox}>
                    <p>You have not reported anything yet.</p>
                    <Link to="/report">Report your first issue</Link>
                </div>
            )}

            <ul className={styles.list}>
                {reports.map((r) => (
                    <li key={r.id} className={styles.item}>
                        <div className={styles.top}>
                            <Link
                                to={`/?report=${r.id}&lat=${r.latitude}&lng=${r.longitude}&z=14`}
                                className={styles.title}
                            >
                                {r.title}
                            </Link>
                            <StatusBadge status={r.status} />
                        </div>
                        <div className={styles.meta}>
                            <Tag>{r.category}</Tag>
                            <span>{[r.city, r.state].filter(Boolean).join(", ")}</span>
                            <span>reported {timeAgo(r.created_at)}</span>
                        </div>
                        <p className={styles.progress}>{progressText(r)}</p>

                        {r.status === "RESOLVED" && r.resolution_note && (
                            <blockquote className={styles.answer}>
                                <span className={styles.answerLabel}>What the officer says was done</span>
                                {r.resolution_note}
                            </blockquote>
                        )}

                        {canCheck(r) && (
                            <div className={styles.check}>
                                <p>
                                    <strong>Is it really fixed?</strong> It stays on the map until{" "}
                                    {formatDateTime(r.leaves_map_at)} so you can go and look. If it is not fixed, reopen it and it
                                    goes straight back to the officer.
                                </p>
                                {reopening === r.id ? (
                                    <div className={styles.reopenForm}>
                                        <TextArea
                                            label="What is still wrong? (optional)"
                                            value={reason}
                                            onChange={(e) => setReason(e.target.value)}
                                            maxLength={500}
                                            rows={3}
                                        />
                                        <div className={styles.checkActions}>
                                            <Button variant="secondary" size="sm" onClick={() => setReopening(null)}>
                                                Cancel
                                            </Button>
                                            <Button size="sm" loading={busy === r.id} onClick={() => reopen(r)}>
                                                Reopen this report
                                            </Button>
                                        </div>
                                    </div>
                                ) : (
                                    <div className={styles.checkActions}>
                                        {!r.confirmed_at && (
                                            <Button size="sm" loading={busy === r.id} onClick={() => confirm(r)}>
                                                Yes, it is fixed
                                            </Button>
                                        )}
                                        <Button
                                            size="sm"
                                            variant="secondary"
                                            onClick={() => {
                                                setReopening(r.id);
                                                setReason("");
                                            }}
                                        >
                                            No, reopen it
                                        </Button>
                                    </div>
                                )}
                            </div>
                        )}
                    </li>
                ))}
            </ul>

            {more && (
                <div className={styles.moreRow}>
                    <Button variant="secondary" onClick={loadMore}>
                        Load older reports
                    </Button>
                </div>
            )}
        </div>
    );
}

export default MyReports;
