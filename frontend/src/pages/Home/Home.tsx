import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import IndiaMap from "../../components/Map/IndiaMap";
import Card from "../../components/UI/Card/Card";
import Button from "../../components/UI/Button/Button";

import { getReports } from "../../services/reportService";
import type { Report } from "../../types/report";

import styles from "./Home.module.css";

function Home() {
    const navigate = useNavigate();

    const [reports, setReports] = useState<Report[]>([]);

    const [statusFilter, setStatusFilter] =
        useState("OPEN");

    const [categoryFilter, setCategoryFilter] =
        useState("ALL");

    useEffect(() => {
        async function loadReports() {
            try {
                const data = await getReports({
                    status:
                        statusFilter === "ALL"
                            ? undefined
                            : statusFilter,

                    category:
                        categoryFilter === "ALL"
                            ? undefined
                            : categoryFilter,
                });

                setReports(data);
            } catch (err) {
                console.error(err);
            }
        }

        void loadReports();
    }, [statusFilter, categoryFilter]);

    const totalReports = reports.length;

    const openReports = reports.filter(
        report => report.status === "OPEN"
    ).length;

    const resolvedReports = reports.filter(
        report => report.status === "RESOLVED"
    ).length;

    return (
        <div className={styles.container}>

            <div className={styles.filters}>

                <div className={styles.filterGroup}>
                    <label>Status</label>

                    <select
                        value={statusFilter}
                        onChange={(e) =>
                            setStatusFilter(e.target.value)
                        }
                    >
                        <option value="OPEN">
                            🔴 Open
                        </option>

                        <option value="IN_PROGRESS">
                            🟡 In Progress
                        </option>

                        <option value="RESOLVED">
                            🟢 Resolved
                        </option>

                        <option value="ALL">
                            📋 All
                        </option>
                    </select>
                </div>

                <div className={styles.filterGroup}>
                    <label>Category</label>

                    <select
                        value={categoryFilter}
                        onChange={(e) =>
                            setCategoryFilter(e.target.value)
                        }
                    >
                        <option value="ALL">
                            📂 All Categories
                        </option>

                        <option value="POTHOLE">
                            🛣️ Pothole
                        </option>

                        <option value="GARBAGE">
                            🗑️ Garbage
                        </option>

                        <option value="WATER_LOGGING">
                            💧 Water Logging
                        </option>

                        <option value="STREETLIGHT">
                            💡 Street Light
                        </option>

                        <option value="OTHER">
                            📌 Other
                        </option>
                    </select>
                </div>

            </div>

            <div className={styles.stats}>
                <Card>
                    <h3>Total Reports</h3>
                    <h1>{totalReports}</h1>
                    <p>Reports submitted</p>
                </Card>

                <Card>
                    <h3>Open Issues</h3>
                    <h1>{openReports}</h1>
                    <p>Needs attention</p>
                </Card>

                <Card>
                    <h3>Resolved</h3>
                    <h1>{resolvedReports}</h1>
                    <p>Successfully resolved</p>
                </Card>
            </div>

            <div className={styles.mapSection}>
                <IndiaMap
                    statusFilter={statusFilter}
                    categoryFilter={categoryFilter}
                />
            </div>

            <div className={styles.floatingButton}>
                <Button
                    onClick={() =>
                        navigate("/report")
                    }
                >
                    + Report Issue
                </Button>
            </div>

        </div>
    );
}

export default Home;