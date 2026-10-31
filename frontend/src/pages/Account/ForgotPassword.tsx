import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";

import Button from "../../components/UI/Button/Button";
import { TextField } from "../../components/UI/Input/Input";
import { forgotPassword } from "../../services/authService";
import { apiErrorMessage } from "../../services/reportService";
import styles from "./Account.module.css";

function ForgotPassword() {
    const [email, setEmail] = useState("");
    const [busy, setBusy] = useState(false);
    const [sent, setSent] = useState(false);
    const [error, setError] = useState("");

    async function submit(e: FormEvent) {
        e.preventDefault();
        setError("");
        setBusy(true);
        try {
            await forgotPassword(email.trim());
            setSent(true);
        } catch (err) {
            setError(apiErrorMessage(err, "We could not send that. Please try again."));
        } finally {
            setBusy(false);
        }
    }

    return (
        <div className={styles.page}>
            <div className={styles.card}>
                <h1>Forgot your password?</h1>
                {sent ? (
                    <>
                        <p className={styles.ok} role="status">
                            If an account exists for {email.trim()}, we have emailed a link to choose a new password. It works for one hour.
                            Check your spam folder too.
                        </p>
                        <Link className={styles.back} to="/login">
                            Back to sign in
                        </Link>
                    </>
                ) : (
                    <form onSubmit={submit} className={styles.card} style={{ padding: 0, border: "none", boxShadow: "none" }}>
                        <p className={styles.sub}>Enter the email you signed up with and we will send you a link.</p>
                        <TextField
                            label="Email"
                            type="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            autoComplete="email"
                            required
                        />
                        {error && (
                            <p className={styles.error} role="alert">
                                {error}
                            </p>
                        )}
                        <Button type="submit" loading={busy}>
                            Send reset link
                        </Button>
                        <Link className={styles.back} to="/login">
                            Back to sign in
                        </Link>
                    </form>
                )}
            </div>
        </div>
    );
}

export default ForgotPassword;
