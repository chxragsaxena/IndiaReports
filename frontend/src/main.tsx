import { StrictMode } from "react";
import ReactDOM from "react-dom/client";

import AppRouter from "./router/AppRouter";

import "./styles.css";
import { API_URL } from "./config/api";

// A free-tier server sleeps when idle. Start waking it the moment the page opens, in parallel with everything else loading.
if (API_URL) void fetch(`${API_URL}/health`, { mode: "no-cors", cache: "no-store" }).catch(() => undefined);

// Installable app: the service worker only runs in the built site, so development is never served stale files.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
    window.addEventListener("load", () => {
        navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    });
}

ReactDOM.createRoot(document.getElementById("root")!).render(
    <StrictMode>
        <AppRouter />
    </StrictMode>
);