import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import Button from "../../components/UI/Button/Button";
import { TextField } from "../../components/UI/Input/Input";
import { resetPassword } from "../../services/authService";
import { apiErrorMessage } from "../../services/reportService";
import styles from "./Account.module.css";

function ResetPassword() {
    const [params] = useSearchParams();
    const token = params.get("token") ?? "";
    const [password, setPassword] = useState("");
    const [again, setAgain] = useState("");
    const [busy, setBusy] = useState(false);
    const [done, setDone] = useState(false);
    const [error, setError] = useState("");

    async function submit(e: FormEvent) {
        e.preventDefault();
        if (password !== again) {
            setError("The two passwords do not match.");
            return;
        }
        setError("");
        setBusy(true);
        try {
            await resetPassword(token, password);
            setDone(true);
        } catch (err) {
            setError(apiErrorMessage(err, "We could not change your password. Please try again."));
        } finally {
            setBusy(false);
        }
    }

    if (!token) {
        return (
            <div className={styles.page}>
                <div className={styles.card}>
                    <h1>This link is incomplete</h1>
                    <p className={styles.sub}>Open the link from the email exactly as it was sent, or ask for a new one.</p>
                    <Link to="/forgot-password">Ask for a new link</Link>
                </div>
            </div>
        );
    }

    return (
        <div className={styles.page}>
            <div className={styles.card}>
                <h1>Choose a new password</h1>
                {done ? (
                    <>
                        <p className={styles.ok} role="status">
                            Your password has been changed. You were signed out everywhere, so sign in again with the new one.
                        </p>
                        <Link to="/login">Go to sign in</Link>
                    </>
                ) : (
                    <form onSubmit={submit} className={styles.card} style={{ padding: 0, border: "none", boxShadow: "none" }}>
                        <TextField
                            label="New password"
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            autoComplete="new-password"
                            minLength={8}
                            hint="At least 8 characters."
                            required
                        />
                        <TextField
                            label="Type it again"
                            type="password"
                            value={again}
                            onChange={(e) => setAgain(e.target.value)}
                            autoComplete="new-password"
                            minLength={8}
                            required
                        />
                        {error && (
                            <p className={styles.error} role="alert">
                                {error}{" "}
                                {error.includes("expired") && <Link to="/forgot-password">Ask for a new link</Link>}
                            </p>
                        )}
                        <Button type="submit" loading={busy}>
                            Change password
                        </Button>
                    </form>
                )}
            </div>
        </div>
    );
}

export default ResetPassword;
