import { useCallback, useEffect, useRef, useState } from "react";
import { NOTIFIER_URL, toWebSocketUrl } from "../config/api";
import type { ReportStatus } from "../types/report";

export type LiveStatus = "off" | "connecting" | "live" | "reconnecting";

/** The public part of a stream event (the server never sends private fields). */
export interface LiveReport {
    report_id: string;
    title: string;
    category: string;
    status?: ReportStatus;
    new_status?: ReportStatus;
    city: string;
    state: string;
    latitude: number;
    longitude: number;
}

export interface LiveHandlers {
    onReport: (event: string, report: LiveReport) => void;
    /** The viewport is zoomed out: the server asks us to re-fetch clusters. */
    onRefresh: () => void;
}

interface Viewport {
    bbox: [number, number, number, number]; // west, south, east, north
    zoom: number;
}

const MAX_BACKOFF_MS = 30_000;
const HIDDEN_GRACE_MS = 30_000;

/**
 * Keeps one WebSocket to the notifier. Reconnects with jittered exponential backoff
 * and re-sends the last viewport. When the tab stays hidden it disconnects, so idle
 * tabs do not hold server connections.
 */
export function useLiveSocket(handlers: LiveHandlers) {
    const enabled = NOTIFIER_URL !== "";
    const [status, setStatus] = useState<LiveStatus>(enabled ? "connecting" : "off");

    const handlersRef = useRef(handlers);
    const socketRef = useRef<WebSocket | null>(null);
    const viewportRef = useRef<Viewport | null>(null);

    useEffect(() => {
        handlersRef.current = handlers;
    });

    useEffect(() => {
        if (!enabled) return;

        let disposed = false;
        let attempt = 0;
        let retryTimer: number | undefined;
        let hiddenTimer: number | undefined;

        function sendViewport() {
            const ws = socketRef.current;
            const vp = viewportRef.current;
            if (ws && ws.readyState === WebSocket.OPEN && vp) {
                ws.send(JSON.stringify({ type: "viewport", bbox: vp.bbox, zoom: vp.zoom }));
            }
        }

        function connect() {
            if (disposed || socketRef.current) return;
            setStatus(attempt === 0 ? "connecting" : "reconnecting");

            const ws = new WebSocket(`${toWebSocketUrl(NOTIFIER_URL)}/ws`);
            socketRef.current = ws;

            ws.onopen = () => {
                attempt = 0;
                setStatus("live");
                sendViewport();
            };

            ws.onmessage = (msg) => {
                try {
                    const data = JSON.parse(String(msg.data));
                    if (data.type === "report" && data.report) {
                        handlersRef.current.onReport(String(data.event), data.report as LiveReport);
                    } else if (data.type === "refresh") {
                        handlersRef.current.onRefresh();
                    }
                } catch {
                    // Ignore malformed frames.
                }
            };

            ws.onclose = () => {
                // A late close from an older socket must not clear a newer one.
                if (socketRef.current === ws) socketRef.current = null;
                if (disposed || document.hidden) return;
                setStatus("reconnecting");
                const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt) * (0.5 + Math.random() / 2);
                attempt += 1;
                retryTimer = window.setTimeout(connect, delay);
            };

            ws.onerror = () => ws.close();
        }

        function onVisibility() {
            if (document.hidden) {
                hiddenTimer = window.setTimeout(() => {
                    window.clearTimeout(retryTimer);
                    socketRef.current?.close();
                }, HIDDEN_GRACE_MS);
            } else {
                window.clearTimeout(hiddenTimer);
                if (!socketRef.current) {
                    attempt = 0;
                    connect();
                }
            }
        }

        connect();
        document.addEventListener("visibilitychange", onVisibility);

        return () => {
            disposed = true;
            window.clearTimeout(retryTimer);
            window.clearTimeout(hiddenTimer);
            document.removeEventListener("visibilitychange", onVisibility);
            socketRef.current?.close();
            socketRef.current = null;
        };
    }, [enabled]);

    /** Tell the server which part of the map this client is looking at. */
    const setViewport = useCallback((bbox: [number, number, number, number], zoom: number) => {
        viewportRef.current = { bbox, zoom };
        const ws = socketRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "viewport", bbox, zoom }));
        }
    }, []);

    return { status, setViewport };
}
