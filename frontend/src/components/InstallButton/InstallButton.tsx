import { useEffect, useState } from "react";

import styles from "./InstallButton.module.css";

// Chrome and Edge announce that the app can be installed; Safari has no such event (use Share > Add to Home Screen).
interface InstallPrompt extends Event {
    prompt: () => Promise<void>;
    userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

function InstallButton() {
    const [prompt, setPrompt] = useState<InstallPrompt | null>(null);

    useEffect(() => {
        const onPrompt = (e: Event) => {
            e.preventDefault(); // keep it for our own button instead of the browser's mini-bar
            setPrompt(e as InstallPrompt);
        };
        const onInstalled = () => setPrompt(null);
        window.addEventListener("beforeinstallprompt", onPrompt);
        window.addEventListener("appinstalled", onInstalled);
        return () => {
            window.removeEventListener("beforeinstallprompt", onPrompt);
            window.removeEventListener("appinstalled", onInstalled);
        };
    }, []);

    if (!prompt) return null;

    return (
        <button
            type="button"
            className={styles.install}
            onClick={async () => {
                await prompt.prompt();
                await prompt.userChoice;
                setPrompt(null);
            }}
        >
            Install app
        </button>
    );
}

export default InstallButton;
