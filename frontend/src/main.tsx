import { StrictMode } from "react";
import ReactDOM from "react-dom/client";

import AppRouter from "./router/AppRouter";

import "./styles.css";

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