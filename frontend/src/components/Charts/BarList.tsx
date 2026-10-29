import { formatNumber } from "../../utils/format";
import styles from "./Charts.module.css";

export interface BarItem {
    label: string;
    value: number;
}

/** Horizontal bars, sorted by value. Plain HTML so it is readable by screen readers. */
function BarList({ items, limit = 8 }: { items: BarItem[]; limit?: number }) {
    const shown = [...items].sort((a, b) => b.value - a.value).slice(0, limit);
    const max = Math.max(1, ...shown.map((i) => i.value));

    return (
        <ul className={styles.bars}>
            {shown.map((item) => (
                <li key={item.label} className={styles.barRow}>
                    <span className={styles.barLabel}>{item.label}</span>
                    <span className={styles.barTrack}>
                        <span className={styles.barFill} style={{ width: `${(item.value / max) * 100}%` }} />
                    </span>
                    <span className={styles.barValue}>{formatNumber(item.value)}</span>
                </li>
            ))}
        </ul>
    );
}

export default BarList;
