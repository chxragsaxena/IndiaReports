import { useEffect, useState } from "react";

import styles from "./ReportDetailsDrawer.module.css";
import { StatusBadge, Tag } from "../UI/Badge/Badge";
import Button from "../UI/Button/Button";
import Skeleton from "../UI/Skeleton/Skeleton";
import { useToast } from "../UI/Toast/Toast";
import { ESCALATION_DAYS } from "../../config/api";
import MeToo from "../MeToo/MeToo";
import { getReport } from "../../services/reportService";
import type { Report } from "../../types/report";
import { formatDateTime } from "../../utils/format";

interface Props {
    reportId: string | null;
    onClose: () => void;
}

interface Step {
    label: string;
    detail?: string;
    state: "done" | "pending" | "alert";
}

/** The accountability trail: who was told, whether they acted, and what happens next. */
function buildTimeline(r: Report, now: number): Step[] {
    const steps: Step[] = [{ label: "Reported", detail: formatDateTime(r.created_at), state: "done" }];

    if (r.assigned_at) {
        steps.push({ label: "Sent to the responsible officer", detail: formatDateTime(r.assigned_at), state: "done" });
    }

    if (r.acknowledged_at) {
        steps.push({ label: "Acknowledged", detail: formatDateTime(r.acknowledged_at), state: "done" });
    }

    if (r.status !== "RESOLVED") {
        if (r.escalated_at) {
            steps.push({
                label: "Not resolved in time: escalated to the administrator",
                detail: formatDateTime(r.escalated_at),
                state: "alert",
            });
        } else if (r.assigned_at) {
            const deadline = new Date(r.assigned_at).getTime() + ESCALATION_DAYS * 86_400_000;
            const daysLeft = Math.ceil((deadline - now) / 86_400_000);
            steps.push({
                label: "Waiting to be resolved",
                detail:
                    daysLeft > 0
                        ? `Escalates to the administrator in ${daysLeft} day${daysLeft === 1 ? "" : "s"} if it is not resolved`
                        : "Escalating to the administrator",
                state: "pending",
            });
        }
        return steps;
    }

    steps.push({
        label: "Resolved",
        detail: [formatDateTime(r.resolved_at ?? r.updated_at), r.resolution_note ? `“${r.resolution_note}”` : ""]
            .filter(Boolean)
            .join(" · "),
        state: "done",
    });
    if (r.leaves_map_at) {
        steps.push({
            label: "Open for the reporter to check",
            detail: `Leaves the map ${formatDateTime(r.leaves_map_at)}`,
            state: "pending",
        });
    }
    return steps;
}

function ReportDetailsDrawer({ reportId, onClose }: Props) {
    const toast = useToast();
    const [state, setState] = useState<{ id: string; report?: Report; error?: boolean } | null>(null);

    useEffect(() => {
        if (!reportId) return;
        const controller = new AbortController();
        getReport(reportId, controller.signal)
            .then((report) => setState({ id: reportId, report }))
            .catch((err) => {
                if ((err as { code?: string }).code !== "ERR_CANCELED") setState({ id: reportId, error: true });
            });
        return () => controller.abort();
    }, [reportId]);

    useEffect(() => {
        if (!reportId) return;
        const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
        document.addEventListener("keydown", onKey);
        return () => document.removeEventListener("keydown", onKey);
    }, [reportId, onClose]);

    if (!reportId) return null;

    const current = state && state.id === reportId ? state : null;
    const report = current?.report;

    async function copyLink() {
        try {
            await navigator.clipboard.writeText(`${window.location.origin}/?report=${reportId}`);
            toast.show("Link copied", "success");
        } catch {
            toast.show("Could not copy the link", "error");
        }
    }

    return (
        <aside className={styles.drawer} aria-label="Report details">
            <div className={styles.header}>
                <div className={styles.headerText}>
                    {report ? <h2>{report.title}</h2> : <Skeleton width="70%" height={24} />}
                </div>
                <button className={styles.close} onClick={onClose} aria-label="Close details">
                    &times;
                </button>
            </div>

            {current?.error && (
                <p className={styles.error} role="alert">
                    This report could not be loaded. It may have been removed.
                </p>
            )}

            {!current && (
                <div className={styles.skeletons}>
                    <Skeleton width="40%" />
                    <Skeleton />
                    <Skeleton />
                    <Skeleton width="60%" />
                </div>
            )}

            {report && (
                <div className={styles.body}>
                    <div className={styles.chips}>
                        <StatusBadge status={report.status} />
                        <Tag>{report.category}</Tag>
                    </div>

                    <p className={styles.description}>{report.description}</p>

                    <MeToo key={report.id} reportId={report.id} count={report.affected_count ?? 1} open={report.status !== "RESOLVED"} />

                    <section>
                        <h3>Location</h3>
                        <p>{[report.address, report.landmark].filter(Boolean).join(", ") || "No address given"}</p>
                        <p className={styles.muted}>
                            {[report.city, report.district, report.state, report.pincode].filter(Boolean).join(", ")}
                        </p>
                    </section>

                    <section>
                        <h3>Progress</h3>
                        <ol className={styles.timeline}>
                            {buildTimeline(report, Date.now()).map((step) => (
                                <li key={step.label} className={`${styles.step} ${styles[step.state]}`}>
                                    <span className={styles.stepLabel}>{step.label}</span>
                                    {step.detail && <span className={styles.stepDetail}>{step.detail}</span>}
                                </li>
                            ))}
                        </ol>
                    </section>

                    <div className={styles.actions}>
                        <Button variant="secondary" size="sm" onClick={copyLink}>
                            Copy link
                        </Button>
                        <a
                            className={styles.mapLink}
                            href={`https://www.google.com/maps?q=${report.latitude},${report.longitude}`}
                            target="_blank"
                            rel="noopener noreferrer"
                        >
                            Open in Google Maps
                        </a>
                    </div>
                </div>
            )}
        </aside>
    );
}

export default ReportDetailsDrawer;
