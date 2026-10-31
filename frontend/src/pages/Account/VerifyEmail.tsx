import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { verifyEmail } from "../../services/authService";
import { apiErrorMessage } from "../../services/reportService";
import styles from "./Account.module.css";

type State = "working" | "done" | "failed";

function VerifyEmail() {
    const [params] = useSearchParams();
    const token = params.get("token") ?? "";
    const [state, setState] = useState<State>(token ? "working" : "failed");
    const [message, setMessage] = useState(token ? "" : "This link is incomplete.");
    const started = useRef(false);

    useEffect(() => {
        if (!token || started.current) return; // React runs effects twice in development; the link works once
        started.current = true;
        verifyEmail(token)
            .then(() => setState("done"))
            .catch((err) => {
                setState("failed");
                setMessage(apiErrorMessage(err, "This link is invalid or has expired."));
            });
    }, [token]);

    return (
        <div className={styles.page}>
            <div className={styles.card}>
                {state === "working" && <p role="status">Confirming your email...</p>}
                {state === "done" && (
                    <>
                        <h1>Email confirmed</h1>
                        <p className={styles.sub}>Thank you. We will email you when the problems you report are resolved.</p>
                        <Link to="/report">Report an issue</Link>
                    </>
                )}
                {state === "failed" && (
                    <>
                        <h1>We could not confirm that</h1>
                        <p className={styles.error} role="alert">
                            {message}
                        </p>
                        <p className={styles.sub}>Sign in and use &ldquo;Send the link again&rdquo; at the top of the page.</p>
                        <Link to="/login">Sign in</Link>
                    </>
                )}
            </div>
        </div>
    );
}

export default VerifyEmail;
