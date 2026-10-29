import { STATUS_LABEL } from "../../../types/report";
import type { ReportStatus } from "../../../types/report";
import styles from "./Badge.module.css";

export function StatusBadge({ status }: { status: ReportStatus }) {
    return (
        <span className={`${styles.badge} ${styles[status]}`}>
            <span className={styles.dot} aria-hidden="true" />
            {STATUS_LABEL[status] ?? status}
        </span>
    );
}

export function Tag({ children }: { children: string }) {
    return <span className={`${styles.badge} ${styles.neutral}`}>{children}</span>;
}
