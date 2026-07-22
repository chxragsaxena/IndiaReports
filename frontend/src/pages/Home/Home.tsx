import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import IndiaMap from "../../components/Map/IndiaMap";
import Card from "../../components/UI/Card/Card";
import Input from "../../components/UI/Input/Input";
import Button from "../../components/UI/Button/Button";

import { getReports } from "../../services/reportService";
import type { Report } from "../../types/report";

import styles from "./Home.module.css";

function Home() {
    const navigate = useNavigate();

    const [reports, setReports] = useState<Report[]>([]);

    useEffect(() => {
        async function loadReports() {
            try {
                const data = await getReports();
                setReports(data);
            } catch (err) {
                console.error(err);
            }
        }

        loadReports();
    }, []);

    const totalReports = reports.length;

    const openReports = reports.filter(
        report => report.status === "OPEN"
    ).length;

    const resolvedReports = reports.filter(
        report => report.status === "RESOLVED"
    ).length;

    return (
        <div className={styles.container}>
            <Input placeholder="Search city, state or category..." />

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
                <IndiaMap />
            </div>

            <div className={styles.floatingButton}>
                <Button onClick={() => navigate("/report")}>
                    + Report Issue
                </Button>
            </div>
        </div>
    );
}

export default Home;