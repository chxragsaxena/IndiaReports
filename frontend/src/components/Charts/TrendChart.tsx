import type { TrendPoint } from "../../services/analyticsService";
import styles from "./Charts.module.css";

const W = 640;
const H = 220;
const PAD = { top: 12, right: 12, bottom: 28, left: 36 };

function niceMax(value: number): number {
    if (value <= 5) return 5;
    const magnitude = 10 ** Math.floor(Math.log10(value));
    return Math.ceil(value / magnitude) * magnitude;
}

function shortDate(iso: string): string {
    const d = new Date(`${iso}T00:00:00`);
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

/** Reports created vs resolved per day. Two series, told apart by color and dash. */
function TrendChart({ data }: { data: TrendPoint[] }) {
    if (data.length === 0) return null;

    const max = niceMax(Math.max(...data.map((p) => Math.max(p.created, p.resolved))));
    const x = (i: number) => PAD.left + (i / Math.max(1, data.length - 1)) * (W - PAD.left - PAD.right);
    const y = (v: number) => PAD.top + (1 - v / max) * (H - PAD.top - PAD.bottom);

    const line = (key: "created" | "resolved") =>
        data.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join(" ");

    const area = `${line("created")} L${x(data.length - 1).toFixed(1)},${y(0)} L${x(0).toFixed(1)},${y(0)} Z`;
    const ticks = [0, 0.5, 1].map((f) => Math.round(max * f));
    const labelIdx = [0, Math.floor((data.length - 1) / 2), data.length - 1];

    const totalCreated = data.reduce((s, p) => s + p.created, 0);
    const totalResolved = data.reduce((s, p) => s + p.resolved, 0);

    return (
        <figure className={styles.figure}>
            <svg viewBox={`0 0 ${W} ${H}`} className={styles.svg} role="img"
                aria-label={`Reports per day: ${totalCreated} created and ${totalResolved} resolved over ${data.length} days`}>
                {ticks.map((t) => (
                    <g key={t}>
                        <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className={styles.grid} />
                        <text x={PAD.left - 6} y={y(t) + 4} textAnchor="end" className={styles.axis}>{t}</text>
                    </g>
                ))}
                {labelIdx.map((i) => (
                    <text key={i} x={x(i)} y={H - 8}
                        textAnchor={i === 0 ? "start" : i === data.length - 1 ? "end" : "middle"} className={styles.axis}>
                        {shortDate(data[i].day)}
                    </text>
                ))}
                <path d={area} className={styles.area} />
                <path d={line("created")} className={styles.lineCreated} fill="none" />
                <path d={line("resolved")} className={styles.lineResolved} fill="none" />
            </svg>
            <figcaption className={styles.legend}>
                <span><i className={styles.keyCreated} />Reported</span>
                <span><i className={styles.keyResolved} />Resolved</span>
            </figcaption>
        </figure>
    );
}

export default TrendChart;
