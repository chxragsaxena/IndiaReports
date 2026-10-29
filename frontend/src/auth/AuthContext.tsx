import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { useToast } from "../components/UI/Toast/Toast";
import * as authService from "../services/authService";
import { SESSION_EXPIRED_EVENT, clearSession, loadSession, saveSession } from "../services/session";
import type { AuthUser, Session } from "../services/session";

interface AuthValue {
    user: AuthUser | null;
    signIn: (email: string, password: string) => Promise<AuthUser>;
    signUp: (name: string, email: string, password: string) => Promise<AuthUser>;
    signOut: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
    const toast = useToast();
    const [session, setSession] = useState<Session | null>(loadSession);

    const adopt = useCallback((next: Session) => {
        saveSession(next);
        setSession(next);
        return next.user;
    }, []);

    const signIn = useCallback(
        async (email: string, password: string) => adopt(await authService.login(email, password)),
        [adopt],
    );
    const signUp = useCallback(
        async (name: string, email: string, password: string) => adopt(await authService.register(name, email, password)),
        [adopt],
    );
    const signOut = useCallback(() => {
        clearSession();
        setSession(null);
    }, []);

    // The server rejected our token (expired, or the account was disabled).
    useEffect(() => {
        const onExpired = () => {
            setSession(null);
            toast.show("Your session ended. Please sign in again.", "info");
        };
        window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
        return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
    }, [toast]);

    // Sign out on the client the moment the token expires, without waiting for a 401.
    useEffect(() => {
        if (!session) return;
        const timer = window.setTimeout(() => window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT)), Math.max(0, session.expiresAt - Date.now()));
        return () => window.clearTimeout(timer);
    }, [session]);

    const value = useMemo<AuthValue>(
        () => ({ user: session?.user ?? null, signIn, signUp, signOut }),
        [session, signIn, signUp, signOut],
    );

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthValue {
    const ctx = useContext(AuthContext);
    if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
    return ctx;
}
