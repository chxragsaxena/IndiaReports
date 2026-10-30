import { useEffect, useState } from "react";

import Skeleton from "../../components/UI/Skeleton/Skeleton";
import { getScorecards } from "../../services/scorecardService";
import type { Scorecards as Data } from "../../services/scorecardService";
import { formatDuration, formatPercent } from "../../utils/format";
import styles from "./Scorecards.module.css";

/** Public: is each area actually fixing what residents report? */
function Scorecards() {
    const [data, setData] = useState<Data | null>(null);
    const [failed, setFailed] = useState(false);

    useEffect(() => {
        const controller = new AbortController();
        getScorecards(controller.signal)
            .then(setData)
            .catch((err) => {
                if ((err as { code?: string }).code !== "ERR_CANCELED") setFailed(true);
            });
        return () => controller.abort();
    }, []);

    return (
        <div className={styles.page}>
            <header>
                <h1>Area scorecards</h1>
                <p className={styles.sub}>
                    How each area is doing at fixing what residents report.
                    {data ? ` An officer has ${data.resolve_within_days} days to resolve a report; after that it is escalated.` : ""}
                </p>
            </header>

            {failed && <p className={styles.problem}>Scorecards could not be loaded. Please try again.</p>}
            {!data && !failed && <Skeleton height={260} />}

            {data && data.areas.length === 0 && <p className={styles.muted}>No reports have been routed to an area yet.</p>}

            {data && data.areas.length > 0 && (
                <div className={styles.tableWrap}>
                    <table className={styles.table}>
                        <thead>
                            <tr>
                                <th scope="col">#</th>
                                <th scope="col">Area</th>
                                <th scope="col">Resolved in time</th>
                                <th scope="col">Typical time to fix</th>
                                <th scope="col">Fix disputed</th>
                                <th scope="col">Open now</th>
                                <th scope="col">Escalated</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.areas.map((a, i) => (
                                <tr key={a.area_id}>
                                    <td className={styles.rank}>{a.ranked ? i + 1 : ""}</td>
                                    <th scope="row">
                                        <span className={styles.area}>{a.area}</span>
                                        <span className={styles.muted}>
                                            {a.officers.length > 0 ? a.officers.join(", ") : "No officer assigned"} &middot; {a.received} report
                                            {a.received === 1 ? "" : "s"}
                                        </span>
                                    </th>
                                    <td>
                                        {a.in_time_rate === null ? (
                                            <span className={styles.muted}>Nothing judged yet</span>
                                        ) : (
                                            <div className={styles.meter} title={`${a.resolved} resolved, ${a.late_open} still open past the deadline`}>
                                                <div className={styles.track}>
                                                    <div
                                                        className={a.in_time_rate >= 0.7 ? styles.good : a.in_time_rate >= 0.4 ? styles.fair : styles.poor}
                                                        style={{ width: `${Math.round(a.in_time_rate * 100)}%` }}
                                                    />
                                                </div>
                                                <strong>{formatPercent(a.in_time_rate)}</strong>
                                                {!a.ranked && <span className={styles.muted}>too few to rank</span>}
                                            </div>
                                        )}
                                    </td>
                                    <td>
                                        {a.median_resolution_hours === null ? <span className={styles.muted}>-</span> : formatDuration(a.median_resolution_hours)}
                                    </td>
                                    <td>{a.reopen_rate === null ? <span className={styles.muted}>-</span> : formatPercent(a.reopen_rate)}</td>
                                    <td>
                                        {a.open_now}
                                        {a.late_open > 0 && <span className={styles.late}> ({a.late_open} late)</span>}
                                    </td>
                                    <td>{a.escalated}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            <section className={styles.how}>
                <h2>How this is worked out</h2>
                <ul>
                    <li>
                        <strong>Resolved in time</strong>: of the reports whose deadline has passed or that are already resolved, the share fixed within{" "}
                        {data?.resolve_within_days ?? 7} days and not escalated. Reports still inside their deadline are not counted against anyone.
                    </li>
                    <li>
                        <strong>Typical time to fix</strong>: the median time from a report reaching the officer to it being marked resolved.
                    </li>
                    <li>
                        <strong>Fix disputed</strong>: how often the person who reported it said it was not actually fixed.
                    </li>
                    <li>Spam is left out. Areas with fewer than {data?.min_ranked ?? 5} judged reports are shown but not ranked.</li>
                </ul>
            </section>
        </div>
    );
}

export default Scorecards;
