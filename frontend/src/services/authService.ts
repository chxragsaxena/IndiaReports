import axios from "axios";
import { API_URL } from "../config/api";
import type { AuthUser, Session } from "./session";

interface TokenResponse {
    access_token: string;
    expires_in: number;
    user: AuthUser;
}

const client = axios.create({ baseURL: `${API_URL}/api/v1/auth`, timeout: 60000 });

function toSession(data: TokenResponse): Session {
    return { token: data.access_token, user: data.user, expiresAt: Date.now() + data.expires_in * 1000 };
}

export async function login(email: string, password: string): Promise<Session> {
    return toSession((await client.post<TokenResponse>("/login", { email, password })).data);
}

export async function register(name: string, email: string, password: string): Promise<Session> {
    return toSession((await client.post<TokenResponse>("/register", { name, email, password })).data);
}
