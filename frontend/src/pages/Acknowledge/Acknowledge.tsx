import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { isAxiosError } from "axios";

import Button from "../../components/UI/Button/Button";
import { StatusBadge, Tag } from "../../components/UI/Badge/Badge";
import Skeleton from "../../components/UI/Skeleton/Skeleton";
import { acknowledgeReport, getReport } from "../../services/reportService";
import type { Report } from "../../types/report";
import { formatDateTime } from "../../utils/format";
import styles from "./Acknowledge.module.css";

type Outcome = "idle" | "working" | "done" | "invalid" | "missing" | "failed";

/**
 * Opened from the link in an officer's alert. Acknowledging is an explicit button
 * press, not an automatic request, so link previews and scanners cannot trigger it.
 */
function Acknowledge() {
    const [params] = useSearchParams();
    const reportId = params.get("report") ?? "";
    const token = params.get("token") ?? "";

    const [report, setReport] = useState<Report | null>(null);
    const [loadFailed, setLoadFailed] = useState(false);
    const [outcome, setOutcome] = useState<Outcome>(reportId && token ? "idle" : "invalid");

    useEffect(() => {
        if (!reportId) return;
        const controller = new AbortController();
        getReport(reportId, controller.signal)
            .then(setReport)
            .catch((err) => {
                if ((err as { code?: string }).code !== "ERR_CANCELED") setLoadFailed(true);
            });
        return () => controller.abort();
    }, [reportId]);

    async function acknowledge() {
        setOutcome("working");
        try {
            const updated = await acknowledgeReport(reportId, token);
            setReport(updated);
            setOutcome("done");
        } catch (err) {
            const status = isAxiosError(err) ? err.response?.status : undefined;
            setOutcome(status === 403 ? "invalid" : status === 404 ? "missing" : "failed");
        }
    }

    const alreadyAcknowledged = report?.acknowledged_at && outcome === "idle";

    return (
        <div className={styles.wrap}>
            <div className={styles.card}>
                <h1>Acknowledge a report</h1>

                {report ? (
                    <div className={styles.summary}>
                        <strong>{report.title}</strong>
                        <div className={styles.chips}>
                            <StatusBadge status={report.status} />
                            <Tag>{report.category}</Tag>
                        </div>
                        <span className={styles.where}>
                            {[report.city, report.state].filter(Boolean).join(", ")} &middot; reported{" "}
                            {formatDateTime(report.created_at)}
                        </span>
                    </div>
                ) : loadFailed ? null : (
                    <Skeleton height={70} />
                )}

                {outcome === "idle" && !alreadyAcknowledged && (
                    <>
                        <p>
                            Confirm that you have seen this report and will deal with it. It moves to &ldquo;In
                            progress&rdquo; and will not be escalated to the administrator.
                        </p>
                        <Button onClick={acknowledge}>Acknowledge report</Button>
                    </>
                )}

                {outcome === "idle" && alreadyAcknowledged && (
                    <p className={styles.ok}>This report has already been acknowledged. Nothing more to do.</p>
                )}

                {outcome === "working" && <p>Recording your acknowledgement...</p>}

                {outcome === "done" && (
                    <p className={styles.ok} role="status">
                        Thank you. The report is acknowledged and marked in progress.
                    </p>
                )}

                {outcome === "invalid" && (
                    <p className={styles.bad} role="alert">
                        This link is not valid any more. If the report was escalated, the administrator now holds it.
                    </p>
                )}
                {outcome === "missing" && (
                    <p className={styles.bad} role="alert">
                        We could not find this report.
                    </p>
                )}
                {outcome === "failed" && (
                    <p className={styles.bad} role="alert">
                        Something went wrong. Please try again in a moment.
                    </p>
                )}

                <Link to="/">Back to the map</Link>
            </div>
        </div>
    );
}

export default Acknowledge;
