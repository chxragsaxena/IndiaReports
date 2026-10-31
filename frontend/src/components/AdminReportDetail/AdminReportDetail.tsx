import { useEffect, useRef, useState } from "react";

import { StatusBadge, SeverityBadge, Tag } from "../UI/Badge/Badge";
import Button from "../UI/Button/Button";
import Skeleton from "../UI/Skeleton/Skeleton";
import { useToast } from "../UI/Toast/Toast";
import { getAdminReport, uploadFixPhoto } from "../../services/adminService";
import type { AdminImage, AdminReportDetail as Detail, Triage, Verification } from "../../services/adminService";
import { apiErrorMessage } from "../../services/reportService";
import { compressPhoto, photoProblem } from "../../utils/image";
import { formatDateTime } from "../../utils/format";
import styles from "./AdminReportDetail.module.css";

interface Props {
    reportId: string;
    onClose: () => void;
    /** Jump to this report on the queue map. */
    onShowOnMap?: (reportId: string) => void;
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

const VERDICT_LABEL: Record<Verification["verdict"], string> = {
    fixed: "Looks fixed",
    partly_fixed: "Partly fixed",
    not_fixed: "Not fixed",
    cannot_tell: "Cannot tell",
};

function VerificationPanel({ image }: { image: AdminImage }) {
    const v = image.verification;
    if (image.status === "failed") return <p className={styles.problem}>Fix check failed: {image.error ?? "unknown error"}</p>;
    if (!v) return <p className={styles.muted}>{image.status === "analyzing" ? "Comparing with the original photo..." : "Waiting for the fix check."}</p>;
    return (
        <div className={styles.finding}>
            <div className={styles.findingHead}>
                <strong className={v.verdict === "fixed" ? styles.good : v.verdict === "cannot_tell" ? styles.muted : styles.warn}>
                    {VERDICT_LABEL[v.verdict]}
                </strong>
                <span className={styles.muted}>{Math.round(v.confidence * 100)}% confidence</span>
            </div>
            <p>{v.summary}</p>
            {!v.same_location && <p className={styles.warn}>This may not be the same place as the original photo.</p>}
            {!v.compared_with_original && (
                <p className={styles.muted}>The reporter sent no photo, so this judges the repair photo on its own.</p>
            )}
            {v.remaining_issues.length > 0 && (
                <ul>
                    {v.remaining_issues.map((x) => (
                        <li key={x}>{x}</li>
                    ))}
                </ul>
            )}
            {image.provider === "mock" && <p className={styles.demo}>Demo output: no vision model is configured.</p>}
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
function AdminReportDetail({ reportId, onClose, onShowOnMap }: Props) {
    const [detail, setDetail] = useState<Detail | null>(null);
    const [failed, setFailed] = useState(false);
    const [reload, setReload] = useState(0);
    const [uploading, setUploading] = useState(false);
    const fileInput = useRef<HTMLInputElement>(null);
    const toast = useToast();

    // Load, and keep refreshing while any photo is still being analysed.
    useEffect(() => {
        const controller = new AbortController();
        let timer: number | undefined;

        const load = () =>
            getAdminReport(reportId, controller.signal)
                .then((d) => {
                    setDetail(d);
                    setFailed(false);
                    const unfinished =
                        d.images.some((i) => i.status === "pending" || i.status === "analyzing") ||
                        d.voice_notes.some((v) => v.status === "pending");
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
    }, [reportId, reload]);

    async function attachRepairPhoto(file: File | undefined) {
        if (!file) return;
        const problem = photoProblem(file);
        if (problem) {
            toast.show(problem, "error");
            return;
        }
        setUploading(true);
        try {
            await uploadFixPhoto(reportId, await compressPhoto(file));
            toast.show("Repair photo added. It is being compared with the original.", "success");
            setReload((n) => n + 1);
        } catch (e) {
            toast.show(apiErrorMessage(e), "error");
        } finally {
            setUploading(false);
            if (fileInput.current) fileInput.current.value = "";
        }
    }

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
                    {onShowOnMap && (
                        <div>
                            <Button variant="secondary" size="sm" onClick={() => onShowOnMap(detail.id)}>
                                View on map
                            </Button>
                        </div>
                    )}

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

                    {detail.voice_notes.length > 0 && (
                        <>
                            <h3>Voice note</h3>
                            {detail.voice_notes.map((v) => (
                                <div key={v.id} className={styles.voice}>
                                    <audio controls src={v.url} preload="none" />
                                    {v.status === "done" && v.transcript && (
                                        <p className={styles.description}>
                                            {v.transcript}
                                            <span className={styles.muted}>
                                                {" "}
                                                Transcribed{v.language ? ` from ${v.language}` : ""}. The transcript may contain mistakes; play the recording if it matters.
                                            </span>
                                        </p>
                                    )}
                                    {v.status === "pending" && <p className={styles.muted}>Transcribing...</p>}
                                    {v.status === "failed" && <p className={styles.warn}>Could not be transcribed: {v.error ?? "unknown error"}.</p>}
                                    {v.provider === "mock" && <p className={styles.demo}>Demo output: no speech model is configured.</p>}
                                </div>
                            ))}
                        </>
                    )}

                    <h3>Photos ({detail.images.filter((i) => i.kind === "report").length})</h3>

                    {detail.images.every((i) => i.kind !== "report") && (
                        <p className={styles.muted}>The reporter did not attach any photos.</p>
                    )}
                    {demo && (
                        <p className={styles.demo}>
                            Demo output: no vision model is configured, so these findings are samples and the photos were not examined.
                        </p>
                    )}
                    {!detail.analysis_enabled && detail.images.length > 0 && (
                        <p className={styles.muted}>AI analysis is not set up, so photos are shown without findings.</p>
                    )}

                    {detail.images
                        .filter((i) => i.kind === "report")
                        .map((image) => (
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

                    <h3>Repair photos ({detail.images.filter((i) => i.kind === "fix").length})</h3>
                    <p className={styles.muted}>
                        Add a photo of the finished repair. The vision model compares it with the original photo and says whether the
                        problem looks fixed.
                    </p>
                    {detail.images
                        .filter((i) => i.kind === "fix")
                        .map((image) => (
                            <figure key={image.id} className={styles.photo}>
                                <a href={image.url} target="_blank" rel="noopener noreferrer">
                                    <img src={image.url} alt={`Repair photo for ${detail.title}`} loading="lazy" />
                                </a>
                                <figcaption>
                                    <VerificationPanel image={image} />
                                    {image.model && image.provider !== "mock" && (
                                        <p className={styles.fine}>Compared by {image.model}. An assistive check, so verify before closing.</p>
                                    )}
                                </figcaption>
                            </figure>
                        ))}
                    {detail.images.filter((i) => i.kind === "fix").length < 2 && (
                        <div>
                            <input
                                ref={fileInput}
                                type="file"
                                accept="image/jpeg,image/png,image/webp"
                                hidden
                                onChange={(e) => void attachRepairPhoto(e.target.files?.[0])}
                            />
                            <Button variant="secondary" size="sm" loading={uploading} onClick={() => fileInput.current?.click()}>
                                Add repair photo
                            </Button>
                        </div>
                    )}
                </div>
            )}
        </aside>
    );
}

export default AdminReportDetail;
