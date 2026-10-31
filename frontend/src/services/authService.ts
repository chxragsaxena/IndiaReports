import axios from "axios";
import { API_URL } from "../config/api";
import { attachAuth } from "./session";
import type { AuthUser, Session } from "./session";

interface TokenResponse {
    access_token: string;
    expires_in: number;
    user: AuthUser;
}

const client = axios.create({ baseURL: `${API_URL}/api/v1/auth`, timeout: 60000 });
attachAuth(client);

function toSession(data: TokenResponse): Session {
    return { token: data.access_token, user: data.user, expiresAt: Date.now() + data.expires_in * 1000 };
}

export async function login(email: string, password: string): Promise<Session> {
    return toSession((await client.post<TokenResponse>("/login", { email, password })).data);
}

export async function register(name: string, email: string, password: string): Promise<Session> {
    return toSession((await client.post<TokenResponse>("/register", { name, email, password })).data);
}

/** Email a reset link. The answer is the same whether or not the address has an account. */
export async function forgotPassword(email: string): Promise<void> {
    await client.post("/forgot-password", { email });
}

export async function resetPassword(token: string, password: string): Promise<void> {
    await client.post("/reset-password", { token, password });
}

export async function verifyEmail(token: string): Promise<void> {
    await client.post("/verify-email", { token });
}

export async function resendVerification(): Promise<void> {
    await client.post("/resend-verification");
}

/** The signed-in person as the server sees them now (for example, after they confirmed their email). */
export async function currentUser(): Promise<AuthUser> {
    return (await client.get<AuthUser>("/me")).data;
}
