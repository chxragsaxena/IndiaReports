import { useEffect, useState } from "react";

import MeToo from "./MeToo";
import { Tag } from "../UI/Badge/Badge";
import { findSimilar } from "../../services/reportService";
import type { SimilarReport } from "../../services/reportService";
import styles from "./MeToo.module.css";

interface Props {
    latitude: number | null;
    longitude: number | null;
    category: string;
    title: string;
    description: string;
}

/** While filing: is this problem already reported here? Offers "me too" instead of a copy. */
function SimilarNearby({ latitude, longitude, category, title, description }: Props) {
    const [found, setFound] = useState<SimilarReport[]>([]);
    const ready = latitude !== null && longitude !== null && category !== "" && title.trim().length >= 3;

    useEffect(() => {
        if (!ready || latitude === null || longitude === null) {
            setFound([]);
            return;
        }
        const controller = new AbortController();
        const timer = window.setTimeout(() => {
            findSimilar({ latitude, longitude, category, title: title.trim(), description: description.trim() }, controller.signal)
                .then(setFound)
                .catch(() => setFound([])); // a failed suggestion must never get in the way of filing
        }, 700);
        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [ready, latitude, longitude, category, title, description]);

    if (found.length === 0) return null;

    return (
        <section className={styles.notice} aria-live="polite">
            <h3>This may already be reported nearby</h3>
            <p className={styles.muted}>
                If it is the same problem, add yourself instead of filing a copy. It counts towards how many people are affected.
            </p>
            {found.map((r) => (
                <div key={r.id} className={styles.card}>
                    <span className={styles.cardTitle}>{r.title}</span>
                    <span className={styles.muted}>
                        <Tag>{r.category}</Tag> about {r.distance_m} m away
                    </span>
                    <MeToo reportId={r.id} count={r.affected_count} open />
                </div>
            ))}
        </section>
    );
}

export default SimilarNearby;
