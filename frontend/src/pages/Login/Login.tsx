import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { useAuth } from "../../auth/AuthContext";
import Button from "../../components/UI/Button/Button";
import { TextField } from "../../components/UI/Input/Input";
import { apiErrorMessage } from "../../services/reportService";
import type { Role } from "../../services/session";
import BackdropMap from "./BackdropMap";
import styles from "./Login.module.css";

type Portal = "citizen" | "admin";
type Mode = "signin" | "signup";

const HOME: Record<Role, string> = { citizen: "/report", admin: "/admin" };

/** Only follow same-site paths, so a crafted link cannot send someone elsewhere after sign-in. */
function safeNext(next: string | null): string | null {
    return next && next.startsWith("/") && !next.startsWith("//") ? next : null;
}

function Login() {
    const { user, signIn, signUp, signOut } = useAuth();
    const navigate = useNavigate();
    const [params] = useSearchParams();
    const next = safeNext(params.get("next"));

    const [portal, setPortal] = useState<Portal>("citizen");
    const [mode, setMode] = useState<Mode>("signin");
    const [name, setName] = useState("");
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);

    if (user) return <Navigate to={next ?? HOME[user.role]} replace />;

    function choosePortal(p: Portal) {
        setPortal(p);
        setMode("signin"); // administrators cannot sign themselves up
        setError("");
    }

    async function submit(e: FormEvent) {
        e.preventDefault();
        setError("");
        setBusy(true);
        try {
            const signedIn =
                mode === "signup" && portal === "citizen"
                    ? await signUp(name.trim(), email.trim(), password)
                    : await signIn(email.trim(), password);

            // The tab is only a hint about which form to show; the server decides the role.
            if (portal === "admin" && signedIn.role !== "admin") {
                signOut();
                setError("This account does not have administrator access.");
                return;
            }
            navigate(next ?? HOME[signedIn.role], { replace: true });
        } catch (err) {
            setError(apiErrorMessage(err, "We could not sign you in. Please try again."));
        } finally {
            setBusy(false);
        }
    }

    const signingUp = mode === "signup" && portal === "citizen";

    return (
        <div className={styles.wrap}>
            <BackdropMap />
            <div className={styles.veil} aria-hidden="true" />

            <div className={styles.content}>
                <section className={styles.pitch}>
                    <span className={styles.flag} aria-hidden="true" />
                    <h2>See what needs fixing, anywhere in India.</h2>
                    <p>Report a pothole, a broken light or a blocked drain on the map, and follow it until it is resolved.</p>
                    <ul>
                        <li>Pin issues to the exact spot</li>
                        <li>Reports go to the officer for that area</li>
                        <li>Unanswered for 7 days? It goes to the administrator</li>
                    </ul>
                </section>

            <div className={styles.card}>
                <h1>{signingUp ? "Create your account" : "Sign in"}</h1>

                <div className={styles.portals} role="tablist" aria-label="Who are you?">
                    {(["citizen", "admin"] as Portal[]).map((p) => (
                        <button
                            key={p}
                            role="tab"
                            aria-selected={portal === p}
                            className={portal === p ? styles.portalActive : styles.portal}
                            onClick={() => choosePortal(p)}
                            type="button"
                        >
                            <strong>{p === "citizen" ? "Citizen" : "Administrator"}</strong>
                            <span>{p === "citizen" ? "Report issues in your area" : "Manage and track reports"}</span>
                        </button>
                    ))}
                </div>

                <form className={styles.form} onSubmit={submit}>
                    {signingUp && (
                        <TextField
                            label="Your name"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            autoComplete="name"
                            minLength={2}
                            required
                        />
                    )}
                    <TextField
                        label="Email"
                        type="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        autoComplete="email"
                        required
                    />
                    <TextField
                        label="Password"
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        autoComplete={signingUp ? "new-password" : "current-password"}
                        hint={signingUp ? "At least 8 characters." : undefined}
                        minLength={signingUp ? 8 : undefined}
                        required
                    />

                    {error && (
                        <div className={styles.error} role="alert">
                            <p>{error}</p>
                        </div>
                    )}

                    <Button type="submit" loading={busy}>
                        {signingUp ? "Create account" : "Sign in"}
                    </Button>
                </form>

                {portal === "citizen" ? (
                    <p className={styles.switch}>
                        {signingUp ? "Already have an account?" : "New here?"}{" "}
                        <button type="button" className={styles.link} onClick={() => { setMode(signingUp ? "signin" : "signup"); setError(""); }}>
                            {signingUp ? "Sign in" : "Create an account"}
                        </button>
                    </p>
                ) : (
                    <p className={styles.switch}>Administrator accounts are created by an existing administrator.</p>
                )}
            </div>
            </div>
        </div>
    );
}

export default Login;
