import { useEffect, useState } from "react";

import { StatusBadge, SeverityBadge, Tag } from "../UI/Badge/Badge";
import Skeleton from "../UI/Skeleton/Skeleton";
import { getAdminReport } from "../../services/adminService";
import type { AdminImage, AdminReportDetail as Detail, Triage } from "../../services/adminService";
import { formatDateTime } from "../../utils/format";
import styles from "./AdminReportDetail.module.css";

interface Props {
    reportId: string;
    onClose: () => void;
}

const FLAG_LABEL: Record<string, string> = {
    inappropriate: "Inappropriate content",
    people_visible: "People visible",
    license_plate_visible: "Number plate visible",
    screenshot_or_stock_photo: "Screenshot or stock photo",
    likely_unrelated: "Probably not a civic issue",
};

function TriagePanel({ triage }: { triage: Triage }) {
    const translated = triage.language.toLowerCase() !== "english";
    return (
        <div className={styles.finding}>
            <div className={styles.findingHead}>
                <SeverityBadge severity={triage.urgency} prefix="Urgency:" />
                <span className={styles.muted}>{triage.language} &middot; {Math.round(triage.confidence * 100)}% confidence</span>
            </div>
            <p>{triage.summary}</p>
            {triage.is_spam && (
                <p className={styles.warn}>This may be spam{triage.spam_reason ? `: ${triage.spam_reason}` : "."}</p>
            )}
            {!triage.category_matches_report && (
                <p className={styles.warn}>The text reads more like &ldquo;{triage.suggested_category}&rdquo; than the chosen category.</p>
            )}
            {translated && (
                <p className={styles.muted}>
                    In English: <strong>{triage.title_en}</strong>. {triage.description_en}
                </p>
            )}
            {triage.provider !== "mock" ? (
                <p className={styles.fine}>Read by {triage.model}. An assistive check from an open-weight model, so verify before acting.</p>
            ) : (
                <p className={styles.demo}>Demo output: no text model is configured.</p>
            )}
        </div>
    );
}

function Finding({ image }: { image: AdminImage }) {
    const f = image.findings;

    if (image.status === "failed") {
        return <p className={styles.problem}>Analysis failed: {image.error ?? "unknown error"}</p>;
    }
    if (!f) {
        return (
            <p className={styles.muted}>
                {image.status === "analyzing" ? "The vision model is looking at this photo..." : "Waiting for analysis."}
            </p>
        );
    }

    return (
        <div className={styles.finding}>
            <div className={styles.findingHead}>
                <SeverityBadge severity={f.severity} prefix="AI:" />
                <span className={styles.muted}>{Math.round(f.confidence * 100)}% confidence</span>
            </div>
            <p>{f.summary}</p>

            {!f.issue_visible && <p className={styles.warn}>No civic problem is visible in this photo.</p>}
            {!f.category_matches_report && (
                <p className={styles.warn}>The photo looks more like &ldquo;{f.suggested_category}&rdquo; than the chosen category.</p>
            )}

            {f.hazards.length > 0 && (
                <div>
                    <strong>Hazards</strong>
                    <ul>
                        {f.hazards.map((h) => (
                            <li key={h}>{h}</li>
                        ))}
                    </ul>
                </div>
            )}

            <p>
                <strong>Suggested action:</strong> {f.recommended_action}
            </p>

            <div className={styles.chips}>
                {f.image_quality !== "good" && <Tag>{`Photo quality: ${f.image_quality}`}</Tag>}
                {f.flags.map((flag) => (
                    <Tag key={flag}>{FLAG_LABEL[flag] ?? flag}</Tag>
                ))}
            </div>
        </div>
    );
}

/** A report with its photos and what the vision model found in each. */
function AdminReportDetail({ reportId, onClose }: Props) {
    const [detail, setDetail] = useState<Detail | null>(null);
    const [failed, setFailed] = useState(false);

    // Load, and keep refreshing while any photo is still being analysed.
    useEffect(() => {
        const controller = new AbortController();
        let timer: number | undefined;

        const load = () =>
            getAdminReport(reportId, controller.signal)
                .then((d) => {
                    setDetail(d);
                    setFailed(false);
                    const unfinished = d.images.some((i) => i.status === "pending" || i.status === "analyzing");
                    if (unfinished && d.analysis_enabled) timer = window.setTimeout(load, 5000);
                })
                .catch((err) => {
                    if ((err as { code?: string }).code !== "ERR_CANCELED") setFailed(true);
                });

        void load();
        return () => {
            controller.abort();
            window.clearTimeout(timer);
        };
    }, [reportId]);

    useEffect(() => {
        const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
        document.addEventListener("keydown", onKey);
        return () => document.removeEventListener("keydown", onKey);
    }, [onClose]);

    const demo = detail?.images.some((i) => i.provider === "mock");

    return (
        <aside className={styles.drawer} aria-label="Report details">
            <div className={styles.header}>
                <div className={styles.headerText}>{detail ? <h2>{detail.title}</h2> : <Skeleton width="70%" height={24} />}</div>
                <button className={styles.close} onClick={onClose} aria-label="Close details">
                    &times;
                </button>
            </div>

            {failed && <p className={styles.problem}>This report could not be loaded.</p>}
            {!detail && !failed && (
                <div className={styles.body}>
                    <Skeleton height={80} />
                    <Skeleton height={160} />
                </div>
            )}

            {detail && (
                <div className={styles.body}>
                    <div className={styles.chips}>
                        <StatusBadge status={detail.status} />
                        <Tag>{detail.category}</Tag>
                        <span className={styles.muted}>{formatDateTime(detail.created_at)}</span>
                    </div>
                    <p className={styles.description}>{detail.description}</p>
                    {detail.affected_count > 1 && (
                        <p className={styles.muted}>{detail.affected_count} people have reported or confirmed this problem.</p>
                    )}
                    {detail.possible_duplicate && (
                        <p className={styles.warn}>
                            May be a copy of an older report: &ldquo;{detail.possible_duplicate.title}&rdquo; (
                            {detail.possible_duplicate.status.toLowerCase().replace("_", " ")}).
                        </p>
                    )}
                    {detail.triage && <TriagePanel triage={detail.triage} />}
                    <p className={styles.muted}>
                        {[detail.address, detail.city, detail.district, detail.state, detail.pincode].filter(Boolean).join(", ")}
                    </p>

                    <p className={styles.muted}>
                        {detail.assignee_name ? `Assigned to ${detail.assignee_name}` : "Not assigned"}
                        {detail.assigned_at ? ` on ${formatDateTime(detail.assigned_at)}` : ""}.
                        {detail.status === "RESOLVED"
                            ? ` Resolved ${formatDateTime(detail.resolved_at)}.`
                            : detail.escalated_at
                              ? ` Escalated ${formatDateTime(detail.escalated_at)}.`
                              : detail.due_at
                                ? ` Resolve by ${formatDateTime(detail.due_at)}.`
                                : ""}
                    </p>
                    {detail.resolution_note && <p className={styles.description}>&ldquo;{detail.resolution_note}&rdquo;</p>}

                    <h3>Photos ({detail.images.length})</h3>

                    {detail.images.length === 0 && <p className={styles.muted}>The reporter did not attach any photos.</p>}
                    {demo && (
                        <p className={styles.demo}>
                            Demo output: no vision model is configured, so these findings are samples and the photos were not examined.
                        </p>
                    )}
                    {!detail.analysis_enabled && detail.images.length > 0 && (
                        <p className={styles.muted}>AI analysis is not set up, so photos are shown without findings.</p>
                    )}

                    {detail.images.map((image) => (
                        <figure key={image.id} className={styles.photo}>
                            <a href={image.url} target="_blank" rel="noopener noreferrer">
                                <img src={image.url} alt={`Photo for ${detail.title}`} loading="lazy" />
                            </a>
                            <figcaption>
                                <Finding image={image} />
                                {image.model && image.provider !== "mock" && (
                                    <p className={styles.fine}>
                                        Analysed by {image.model}{image.provider === "groq" ? " on Groq" : ""}. This is an assistive check from an open-weight model, so verify before acting.
                                    </p>
                                )}
                            </figcaption>
                        </figure>
                    ))}
                </div>
            )}
        </aside>
    );
}

export default AdminReportDetail;
