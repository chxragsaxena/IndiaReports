import styles from "./ReportDetailsDrawer.module.css";
import Badge from "../UI/Badge/Badge";
import type { Report } from "../../types/report";

interface Props {
    report: Report | null;
    open: boolean;
    onClose: () => void;
}

function ReportDetailsDrawer({
    report,
    open,
    onClose,
}: Props) {
    if (!report) return null;

    return (
        <div
            className={`${styles.drawer} ${
                open ? styles.open : ""
            }`}
        >
            <div className={styles.header}>
                <h2>{report.title}</h2>

                <button
                    className={styles.closeButton}
                    onClick={onClose}
                >
                    ✕
                </button>
            </div>

            <Badge
                text={report.status}
                type={
                    report.status === "RESOLVED"
                        ? "resolved"
                        : "open"
                }
            />

            <div className={styles.section}>
                <h4>Category</h4>
                <p>{report.category}</p>
            </div>

            <div className={styles.section}>
                <h4>Description</h4>
                <p>{report.description}</p>
            </div>

            <div className={styles.section}>
                <h4>Address</h4>
                <p>{report.address}</p>
            </div>

            <div className={styles.section}>
                <h4>Landmark</h4>
                <p>{report.landmark}</p>
            </div>

            <div className={styles.section}>
                <h4>Location</h4>

                <p>{report.city}</p>

                <p>{report.district}</p>

                <p>{report.state}</p>

                <p>{report.pincode}</p>
            </div>

            <div className={styles.section}>
                <h4>Coordinates</h4>

                <p>
                    {report.latitude},
                    {report.longitude}
                </p>
            </div>
        </div>
    );
}

export default ReportDetailsDrawer;