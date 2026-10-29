import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import Button from "../../components/UI/Button/Button";
import Skeleton from "../../components/UI/Skeleton/Skeleton";
import { StatusBadge, Tag } from "../../components/UI/Badge/Badge";
import { getMyReports } from "../../services/reportService";
import type { Report } from "../../types/report";
import { timeAgo } from "../../utils/format";
import styles from "./MyReports.module.css";

function MyReports() {
    const [reports, setReports] = useState<Report[]>([]);
    const [loading, setLoading] = useState(true);
    const [failed, setFailed] = useState(false);
    const [more, setMore] = useState(false);

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
                        <p className={styles.progress}>
                            {r.status === "RESOLVED"
                                ? "Resolved."
                                : r.escalated_at
                                  ? "Nobody acknowledged it in time, so it was escalated to the administrator."
                                  : r.acknowledged_at
                                    ? "The responsible officer has acknowledged it."
                                    : r.assigned_at
                                      ? "Sent to the responsible officer. Waiting for them to acknowledge."
                                      : "Received."}
                        </p>
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
