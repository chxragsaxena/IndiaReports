import { useEffect, useState } from "react";

import styles from "./Dashboard.module.css";

import { getDashboard } from "../../services/dashboardService";
import type { DashboardData } from "../../services/dashboardService";

function Dashboard() {

    const [dashboard, setDashboard] =
        useState<DashboardData | null>(null);

    useEffect(() => {
        async function loadDashboard() {
            try {
                const data = await getDashboard();
                setDashboard(data);
            } catch (err) {
                console.error(err);
            }
        }

        loadDashboard();
    }, []);

    if (!dashboard) {
        return (
            <div className={styles.container}>
                Loading...
            </div>
        );
    }

    return (
        <div className={styles.container}>

            <h1 className={styles.title}>
                Dashboard
            </h1>

            <div className={styles.cards}>

                <div className={styles.card}>
                    <div className={styles.cardTitle}>
                        Total Reports
                    </div>

                    <div className={styles.cardValue}>
                        {dashboard.total_reports}
                    </div>
                </div>

                <div className={styles.card}>
                    <div className={styles.cardTitle}>
                        Open
                    </div>

                    <div className={styles.cardValue}>
                        {dashboard.open_reports}
                    </div>
                </div>

                <div className={styles.card}>
                    <div className={styles.cardTitle}>
                        In Progress
                    </div>

                    <div className={styles.cardValue}>
                        {dashboard.in_progress_reports}
                    </div>
                </div>

                <div className={styles.card}>
                    <div className={styles.cardTitle}>
                        Resolved
                    </div>

                    <div className={styles.cardValue}>
                        {dashboard.resolved_reports}
                    </div>
                </div>

            </div>

            <table className={styles.table}>

                <thead>

                    <tr>
                        <th>Title</th>
                        <th>City</th>
                        <th>Category</th>
                        <th>Status</th>
                    </tr>

                </thead>

                <tbody>

                    {dashboard.recent_reports.map((report) => (

                        <tr key={report.id}>
                            <td>{report.title}</td>
                            <td>{report.city}</td>
                            <td>{report.category}</td>
                            <td>{report.status}</td>
                        </tr>

                    ))}

                </tbody>

            </table>

        </div>
    );
}

export default Dashboard;