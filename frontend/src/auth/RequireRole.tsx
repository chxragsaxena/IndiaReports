import { Link, Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

import { useAuth } from "./AuthContext";
import { isStaff } from "../services/session";
import type { Role } from "../services/session";

interface Props {
    /** Who may see this page. Omit to allow any signed-in person. */
    roles?: Role[];
    children: ReactNode;
}

/**
 * Keeps the wrong people off a page. This only shapes the interface: the server
 * checks the role again on every request, so a hand-edited browser cannot get data.
 */
function RequireRole({ roles, children }: Props) {
    const { user } = useAuth();
    const location = useLocation();

    if (!user) {
        const next = encodeURIComponent(location.pathname + location.search);
        return <Navigate to={`/login?next=${next}`} replace />;
    }

    if (roles && !roles.includes(user.role)) {
        return (
            <div style={{ padding: "64px 20px", textAlign: "center", display: "flex", flexDirection: "column", gap: 12, alignItems: "center" }}>
                <h1>This page is not for your account</h1>
                <p style={{ color: "var(--text-2)" }}>
                    You are signed in as {user.role === "admin" ? "an administrator" : user.role === "officer" ? "an area officer" : "a citizen"}.
                </p>
                <Link to={isStaff(user.role) ? "/admin" : "/report"}>Go to your home page</Link>
            </div>
        );
    }

    return <>{children}</>;
}

export default RequireRole;
