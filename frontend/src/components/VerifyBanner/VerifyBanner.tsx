import { useEffect, useState } from "react";

import { useAuth } from "../../auth/AuthContext";
import { currentUser, resendVerification } from "../../services/authService";
import { useToast } from "../UI/Toast/Toast";
import styles from "./VerifyBanner.module.css";

/** Asks a signed-in citizen to confirm their email address. Emails about their reports are sent either way. */
function VerifyBanner() {
    const { user } = useAuth();
    const toast = useToast();
    const [verified, setVerified] = useState<boolean | null>(null);
    const [sending, setSending] = useState(false);

    // The sign-in answer can be stale (they may have clicked the link in another tab), so ask again.
    useEffect(() => {
        if (!user || user.role !== "citizen") {
            setVerified(null);
            return;
        }
        let cancelled = false;
        currentUser()
            .then((u) => !cancelled && setVerified(u.email_verified !== false))
            .catch(() => !cancelled && setVerified(user.email_verified !== false));
        return () => {
            cancelled = true;
        };
    }, [user]);

    if (!user || verified !== false) return null;

    async function resend() {
        setSending(true);
        try {
            await resendVerification();
            toast.show("We sent a new link. Check your inbox and spam folder.", "success");
        } catch {
            toast.show("We could not send that right now. Please try again later.", "error");
        } finally {
            setSending(false);
        }
    }

    return (
        <div className={styles.banner} role="status">
            <span>
                Please confirm your email address ({user.email}).
            </span>
            <button type="button" className={styles.link} onClick={() => void resend()} disabled={sending}>
                {sending ? "Sending..." : "Send the link again"}
            </button>
        </div>
    );
}

export default VerifyBanner;
