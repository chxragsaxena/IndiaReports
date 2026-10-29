import axios from "axios";
import { NOTIFIER_URL } from "../config/api";

export const notifierEnabled = NOTIFIER_URL !== "";

export type SubscriptionKind = "pincode" | "city" | "state";

export interface NewSubscription {
    chat_id: string;
    kind: SubscriptionKind;
    pincode?: string;
    city?: string;
    state?: string;
    category?: string;
}

export interface Subscription {
    id: string;
    kind: string;
    pincode?: string;
    city?: string;
    state?: string;
    category?: string;
}

const client = axios.create({ baseURL: `${NOTIFIER_URL}/v1`, timeout: 10000 });

export async function subscribe(sub: NewSubscription): Promise<Subscription> {
    const response = await client.post<Subscription>("/subscriptions", { channel: "telegram", ...sub });
    return response.data;
}
