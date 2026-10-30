import { useState } from "react";
import { Link } from "react-router-dom";

import Button from "../UI/Button/Button";
import { useToast } from "../UI/Toast/Toast";
import { apiErrorMessage, supportReport } from "../../services/reportService";
import { loadSession } from "../../services/session";
import styles from "./MeToo.module.css";

interface Props {
    reportId: string;
    count: number;
    /** A resolved report no longer needs support. */
    open: boolean;
}

/** "N people affected" and a "Me too" button, counted once per signed-in person. */
function MeToo({ reportId, count, open }: Props) {
    const toast = useToast();
    const [people, setPeople] = useState(count);
    const [busy, setBusy] = useState(false);
    const [said, setSaid] = useState(false);
    const signedIn = loadSession() !== null;

    async function meToo() {
        setBusy(true);
        try {
            const result = await supportReport(reportId);
            setPeople(result.affected_count);
            setSaid(true);
            toast.show(
                result.added ? "Thanks, you are counted. We will email you when it is fixed." : "You are already counted.",
                "success",
            );
        } catch (e) {
            toast.show(apiErrorMessage(e), "error");
        } finally {
            setBusy(false);
        }
    }

    return (
        <div className={styles.row}>
            <span className={styles.count}>
                {people} {people === 1 ? "person" : "people"} affected
            </span>
            {open &&
                !said &&
                (signedIn ? (
                    <Button variant="secondary" size="sm" loading={busy} onClick={meToo}>
                        Me too
                    </Button>
                ) : (
                    <span className={styles.muted}>
                        <Link to="/login">Sign in</Link> to say you are affected too
                    </span>
                ))}
        </div>
    );
}

export default MeToo;
