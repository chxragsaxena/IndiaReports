import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import Card from "../../components/UI/Card/Card";
import Skeleton from "../../components/UI/Skeleton/Skeleton";
import { StatusBadge, Tag } from "../../components/UI/Badge/Badge";
import TrendChart from "../../components/Charts/TrendChart";
import BarList from "../../components/Charts/BarList";
import { getDashboard } from "../../services/dashboardService";
import type { DashboardData } from "../../services/dashboardService";
import {
    analyticsEnabled,
    getHotspots,
    getLeaderboard,
    getSummary,
    getTrends,
} from "../../services/analyticsService";
import type { Bucket, Hotspot, Summary, TrendPoint } from "../../services/analyticsService";
import { formatDuration, formatNumber, formatPercent, timeAgo } from "../../utils/format";

import styles from "./Dashboard.module.css";

const RANGES = [7, 30, 90];

type Loadable<T> = { state: "loading" } | { state: "error" } | { state: "ready"; data: T };

function useLoad<T>(load: (signal: AbortSignal) => Promise<T>, deps: unknown[]): Loadable<T> {
    const [result, setResult] = useState<Loadable<T>>({ state: "loading" });
    useEffect(() => {
        const controller = new AbortController();
        setResult({ state: "loading" });
        load(controller.signal)
            .then((data) => setResult({ state: "ready", data }))
            .catch((err) => {
                if ((err as { code?: string }).code !== "ERR_CANCELED") setResult({ state: "error" });
            });
        return () => controller.abort();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, deps);
    return result;
}

function Kpi({ label, value, hint }: { label: string; value: string | null; hint?: string }) {
    return (
        <Card className={styles.kpi}>
            <span className={styles.kpiLabel}>{label}</span>
            <span className={styles.kpiValue}>{value ?? <Skeleton width={70} height={30} />}</span>
            {hint && <span className={styles.kpiHint}>{hint}</span>}
        </Card>
    );
}

function Panel({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
    return (
        <Card className={styles.panel}>
            <div className={styles.panelHead}>
                <h2>{title}</h2>
                {note && <span className={styles.note}>{note}</span>}
            </div>
            {children}
        </Card>
    );
}

function Unavailable({ what }: { what: string }) {
    return <p className={styles.empty}>{what} is not available right now.</p>;
}

function Dashboard() {
    const [days, setDays] = useState(30);

    const counts = useLoad<DashboardData>((s) => getDashboard(s), []);
    const summary = useLoad<Summary | null>(
        (s) => (analyticsEnabled ? getSummary(days, s) : Promise.resolve(null)),
        [days],
    );
    const trends = useLoad<TrendPoint[] | null>(
        (s) => (analyticsEnabled ? getTrends(days, s) : Promise.resolve(null)),
        [days],
    );
    const hotspots = useLoad<Hotspot[] | null>(
        (s) => (analyticsEnabled ? getHotspots(s) : Promise.resolve(null)),
        [],
    );
    const leaderboard = useLoad<Bucket[] | null>(
        (s) => (analyticsEnabled ? getLeaderboard(days, s) : Promise.resolve(null)),
        [days],
    );

    const sum = summary.state === "ready" ? summary.data : null;
    const cnt = counts.state === "ready" ? counts.data : null;

    const categoryItems = sum
        ? sum.by_category.map((b) => ({ label: b.name, value: b.created }))
        : cnt
          ? Object.entries(cnt.by_category).map(([label, value]) => ({ label, value }))
          : [];

    return (
        <div className={styles.page}>
            <header className={styles.header}>
                <div>
                    <h1>Insights</h1>
                    <p className={styles.subtitle}>How many issues are being reported across India, and how fast they get fixed.</p>
                </div>
                <div className={styles.range} role="group" aria-label="Time range">
                    {RANGES.map((r) => (
                        <button
                            key={r}
                            className={r === days ? styles.rangeActive : styles.rangeBtn}
                            onClick={() => setDays(r)}
                            aria-pressed={r === days}
                        >
                            {r} days
                        </button>
                    ))}
                </div>
            </header>

            <section className={styles.kpis} aria-label="Key figures">
                {analyticsEnabled && summary.state !== "error" ? (
                    <>
                        <Kpi label="Reported" value={sum ? formatNumber(sum.created) : null} hint={`Last ${days} days`} />
                        <Kpi label="Resolved" value={sum ? formatNumber(sum.resolved) : null} hint={`Last ${days} days`} />
                        <Kpi label="Resolution rate" value={sum ? formatPercent(sum.resolution_rate) : null} />
                        <Kpi label="Average time to resolve" value={sum ? formatDuration(sum.avg_resolve_hours) : null} />
                    </>
                ) : (
                    <>
                        <Kpi label="Total reports" value={cnt ? formatNumber(cnt.total_reports) : null} />
                        <Kpi label="Open" value={cnt ? formatNumber(cnt.open_reports) : null} />
                        <Kpi label="In progress" value={cnt ? formatNumber(cnt.in_progress_reports) : null} />
                        <Kpi label="Resolved" value={cnt ? formatNumber(cnt.resolved_reports) : null} />
                    </>
                )}
            </section>

            <div className={styles.grid}>
                {analyticsEnabled && (
                    <Panel title="Reports per day" note={`Last ${days} days`}>
                        {trends.state === "loading" && <Skeleton height={200} />}
                        {trends.state === "error" && <Unavailable what="The trend chart" />}
                        {trends.state === "ready" && trends.data && <TrendChart data={trends.data} />}
                    </Panel>
                )}

                <Panel title="By category" note={sum ? `Last ${days} days` : "All time"}>
                    {categoryItems.length > 0 ? (
                        <BarList items={categoryItems} />
                    ) : counts.state === "loading" ? (
                        <Skeleton height={160} />
                    ) : (
                        <p className={styles.empty}>No reports yet.</p>
                    )}
                </Panel>

                {analyticsEnabled && (
                    <Panel title="Hotspots" note="Last 24 hours vs the usual">
                        {hotspots.state === "loading" && <Skeleton height={140} />}
                        {hotspots.state === "error" && <Unavailable what="Hotspot detection" />}
                        {hotspots.state === "ready" && hotspots.data && hotspots.data.length === 0 && (
                            <p className={styles.empty}>No unusual spikes right now.</p>
                        )}
                        {hotspots.state === "ready" && hotspots.data && hotspots.data.length > 0 && (
                            <ul className={styles.hotspots}>
                                {hotspots.data.map((h) => (
                                    <li key={`${h.latitude}-${h.longitude}`}>
                                        <div>
                                            <strong>{h.last_24h} new {h.top_category} reports</strong>
                                            <span className={styles.note}>
                                                {h.daily_avg_prev_7d > 0
                                                    ? `usually ${h.daily_avg_prev_7d.toFixed(1)} a day`
                                                    : "no history here yet"}
                                            </span>
                                        </div>
                                        <Link to={`/?lat=${h.latitude}&lng=${h.longitude}&z=12`}>View on map</Link>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </Panel>
                )}

                {analyticsEnabled && (
                    <Panel title="States by resolution rate" note={`Last ${days} days`}>
                        {leaderboard.state === "loading" && <Skeleton height={140} />}
                        {leaderboard.state === "error" && <Unavailable what="The leaderboard" />}
                        {leaderboard.state === "ready" && leaderboard.data && (
                            <table className={styles.table}>
                                <thead>
                                    <tr>
                                        <th scope="col">State</th>
                                        <th scope="col" className={styles.num}>Reports</th>
                                        <th scope="col" className={styles.num}>Resolved</th>
                                        <th scope="col" className={styles.num}>Avg time</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {leaderboard.data.slice(0, 8).map((b) => (
                                        <tr key={b.name}>
                                            <th scope="row">{b.name}</th>
                                            <td className={styles.num}>{formatNumber(b.created)}</td>
                                            <td className={styles.num}>{formatPercent(b.resolution_rate)}</td>
                                            <td className={styles.num}>{formatDuration(b.avg_resolve_hours)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                    </Panel>
                )}
            </div>

            <Panel title="Latest reports">
                {counts.state === "loading" && <Skeleton height={160} />}
                {counts.state === "error" && <Unavailable what="The report list" />}
                {cnt && cnt.recent_reports.length === 0 && <p className={styles.empty}>No reports yet.</p>}
                {cnt && cnt.recent_reports.length > 0 && (
                    <div className={styles.tableWrap}>
                        <table className={styles.table}>
                            <thead>
                                <tr>
                                    <th scope="col">Issue</th>
                                    <th scope="col">Where</th>
                                    <th scope="col">Category</th>
                                    <th scope="col">Status</th>
                                    <th scope="col" className={styles.num}>Reported</th>
                                </tr>
                            </thead>
                            <tbody>
                                {cnt.recent_reports.map((r) => (
                                    <tr key={r.id}>
                                        <th scope="row">
                                            <Link
                                                to={`/?report=${r.id}&lat=${r.latitude}&lng=${r.longitude}&z=14`}
                                                className={styles.rowLink}
                                            >
                                                {r.title}
                                            </Link>
                                        </th>
                                        <td>{[r.city, r.state].filter(Boolean).join(", ")}</td>
                                        <td><Tag>{r.category}</Tag></td>
                                        <td><StatusBadge status={r.status} /></td>
                                        <td className={styles.num}>{timeAgo(r.created_at)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </Panel>
        </div>
    );
}

export default Dashboard;
