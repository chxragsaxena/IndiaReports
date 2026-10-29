import { isAxiosError } from "axios";
import type { AxiosInstance } from "axios";

export type Role = "citizen" | "admin";

export interface AuthUser {
    id: string;
    name: string;
    email: string;
    role: Role;
}

export interface Session {
    token: string;
    user: AuthUser;
    /** Epoch milliseconds. */
    expiresAt: number;
}

// Kept for this browser tab only: closing the tab signs you out. The token is also
// short-lived (the server sets the lifetime), so a stolen one stops working soon.
const KEY = "indiareports.session";

export function loadSession(): Session | null {
    try {
        const raw = sessionStorage.getItem(KEY);
        if (!raw) return null;
        const session = JSON.parse(raw) as Session;
        if (!session.token || session.expiresAt <= Date.now()) {
            sessionStorage.removeItem(KEY);
            return null;
        }
        return session;
    } catch {
        return null;
    }
}

export function saveSession(session: Session): void {
    sessionStorage.setItem(KEY, JSON.stringify(session));
}

export function clearSession(): void {
    sessionStorage.removeItem(KEY);
}

export const SESSION_EXPIRED_EVENT = "indiareports:session-expired";

/** Sends the signed-in token with every request, and signs out cleanly if the server
 *  says the session is no longer valid. */
export function attachAuth(client: AxiosInstance): void {
    client.interceptors.request.use((config) => {
        const session = loadSession();
        if (session) config.headers.set("Authorization", `Bearer ${session.token}`);
        return config;
    });
    client.interceptors.response.use(
        (response) => response,
        (error) => {
            if (isAxiosError(error) && error.response?.status === 401 && loadSession()) {
                clearSession();
                window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
            }
            return Promise.reject(error);
        },
    );
}
