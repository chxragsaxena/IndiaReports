import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import IndiaMap from "../../components/Map/IndiaMap";
import type { MapView } from "../../components/Map/IndiaMap";
import ReportDetailsDrawer from "../../components/ReportDetailsDrawer/ReportDetailsDrawer";
import AlertsDialog from "../../components/AlertsDialog/AlertsDialog";
import Skeleton from "../../components/UI/Skeleton/Skeleton";
import Button from "../../components/UI/Button/Button";
import { getDashboard } from "../../services/dashboardService";
import type { DashboardData } from "../../services/dashboardService";
import { notifierEnabled } from "../../services/notifierService";
import type { LiveStatus } from "../../hooks/useLiveSocket";
import { CATEGORIES, STATUS_LABEL } from "../../types/report";
import type { ReportStatus } from "../../types/report";
import { formatNumber } from "../../utils/format";

import styles from "./Home.module.css";

const STATUS_OPTIONS: { value: string; label: string }[] = [
    { value: "ALL", label: "All" },
    { value: "OPEN", label: STATUS_LABEL.OPEN },
    { value: "IN_PROGRESS", label: STATUS_LABEL.IN_PROGRESS },
    { value: "RESOLVED", label: STATUS_LABEL.RESOLVED },
];

const LIVE_LABEL: Record<LiveStatus, string> = {
    off: "Live updates off",
    connecting: "Connecting",
    live: "Live",
    reconnecting: "Reconnecting",
};

const STATS: { key: keyof Pick<DashboardData, "total_reports" | "open_reports" | "in_progress_reports" | "resolved_reports">; label: string; status?: ReportStatus }[] = [
    { key: "total_reports", label: "Total" },
    { key: "open_reports", label: "Open", status: "OPEN" },
    { key: "in_progress_reports", label: "In progress", status: "IN_PROGRESS" },
    { key: "resolved_reports", label: "Resolved", status: "RESOLVED" },
];

function parseView(params: URLSearchParams): MapView | undefined {
    const lat = Number(params.get("lat"));
    const lng = Number(params.get("lng"));
    if (!params.get("lat") || !params.get("lng") || Number.isNaN(lat) || Number.isNaN(lng)) return undefined;
    const zoom = Number(params.get("z"));
    return { lat, lng, zoom: Number.isNaN(zoom) || zoom <= 0 ? 10 : zoom };
}

function Home() {
    const [params, setParams] = useSearchParams();

    const [statusFilter, setStatusFilter] = useState("ALL");
    const [categoryFilter, setCategoryFilter] = useState("ALL");
    const [panelOpen, setPanelOpen] = useState(false);
    const [alertsOpen, setAlertsOpen] = useState(false);
    const [liveStatus, setLiveStatus] = useState<LiveStatus>("off");
    const [stats, setStats] = useState<DashboardData | null>(null);

    const selectedId = params.get("report");
    // Read once: later URL changes (selecting a report) must not recentre the map.
    const [initialView] = useState(() => parseView(params));

    useEffect(() => {
        const controller = new AbortController();
        const load = () =>
            getDashboard(controller.signal)
                .then(setStats)
                .catch(() => undefined);
        void load();
        const timer = window.setInterval(load, 30_000);
        return () => {
            controller.abort();
            window.clearInterval(timer);
        };
    }, []);

    const select = useCallback(
        (id: string | null) => {
            setParams(
                (prev) => {
                    const next = new URLSearchParams(prev);
                    if (id) next.set("report", id);
                    else next.delete("report");
                    return next;
                },
                { replace: true },
            );
        },
        [setParams],
    );

    return (
        <div className={styles.page}>
            <IndiaMap
                statusFilter={statusFilter}
                categoryFilter={categoryFilter}
                selectedId={selectedId}
                onSelect={select}
                onLiveStatus={setLiveStatus}
                initialView={initialView}
            />

            <section className={`${styles.panel} ${panelOpen ? styles.panelOpen : ""}`} aria-label="Filters and statistics">
                <button
                    className={styles.panelToggle}
                    onClick={() => setPanelOpen((o) => !o)}
                    aria-expanded={panelOpen}
                >
                    <span>Filters and statistics</span>
                    <span aria-hidden="true">{panelOpen ? "−" : "+"}</span>
                </button>

                <div className={styles.panelBody}>
                    <div className={styles.liveRow}>
                        <span className={`${styles.liveDot} ${styles[liveStatus]}`} aria-hidden="true" />
                        <span role="status">{LIVE_LABEL[liveStatus]}</span>
                    </div>

                    <div className={styles.stats}>
                        {STATS.map((s) => (
                            <button
                                key={s.key}
                                className={`${styles.stat} ${
                                    (s.status ?? "ALL") === statusFilter ? styles.statActive : ""
                                }`}
                                onClick={() => setStatusFilter(s.status ?? "ALL")}
                                aria-pressed={(s.status ?? "ALL") === statusFilter}
                            >
                                <span className={styles.statValue}>
                                    {stats ? formatNumber(stats[s.key]) : <Skeleton width={36} height={22} />}
                                </span>
                                <span className={styles.statLabel}>{s.label}</span>
                            </button>
                        ))}
                    </div>

                    <fieldset className={styles.group}>
                        <legend>Status</legend>
                        <div className={styles.segmented}>
                            {STATUS_OPTIONS.map((o) => (
                                <button
                                    key={o.value}
                                    className={o.value === statusFilter ? styles.segActive : styles.seg}
                                    onClick={() => setStatusFilter(o.value)}
                                    aria-pressed={o.value === statusFilter}
                                >
                                    {o.label}
                                </button>
                            ))}
                        </div>
                    </fieldset>

                    <div className={styles.group}>
                        <label htmlFor="category-filter">Category</label>
                        <select
                            id="category-filter"
                            className={styles.select}
                            value={categoryFilter}
                            onChange={(e) => setCategoryFilter(e.target.value)}
                        >
                            <option value="ALL">All categories</option>
                            {CATEGORIES.map((c) => (
                                <option key={c} value={c}>
                                    {c}
                                </option>
                            ))}
                        </select>
                    </div>

                    <ul className={styles.legend} aria-label="Map legend">
                        <li><span style={{ background: "var(--open)" }} />Open</li>
                        <li><span style={{ background: "var(--progress)" }} />In progress</li>
                        <li><span style={{ background: "var(--resolved)" }} />Resolved</li>
                    </ul>

                    <div className={styles.cta}>
                        <Link to="/report" className={styles.primaryLink}>
                            Report an issue
                        </Link>
                        {notifierEnabled && (
                            <Button variant="secondary" onClick={() => setAlertsOpen(true)}>
                                Get alerts for my area
                            </Button>
                        )}
                    </div>
                </div>
            </section>

            <ReportDetailsDrawer reportId={selectedId} onClose={() => select(null)} />

            {alertsOpen && <AlertsDialog onClose={() => setAlertsOpen(false)} />}
        </div>
    );
}

export default Home;
