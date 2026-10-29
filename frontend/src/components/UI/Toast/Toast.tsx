import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import styles from "./Toast.module.css";

type ToastKind = "success" | "error" | "info";

interface ToastItem {
    id: number;
    kind: ToastKind;
    message: string;
}

interface ToastApi {
    show: (message: string, kind?: ToastKind) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
    const [items, setItems] = useState<ToastItem[]>([]);
    const nextId = useRef(1);

    const show = useCallback((message: string, kind: ToastKind = "info") => {
        const id = nextId.current++;
        setItems((current) => [...current.slice(-3), { id, kind, message }]);
        window.setTimeout(() => setItems((current) => current.filter((t) => t.id !== id)), 5000);
    }, []);

    const api = useMemo(() => ({ show }), [show]);

    return (
        <ToastContext.Provider value={api}>
            {children}
            <div className={styles.region} role="status" aria-live="polite">
                {items.map((t) => (
                    <div key={t.id} className={`${styles.toast} ${styles[t.kind]}`}>
                        {t.message}
                    </div>
                ))}
            </div>
        </ToastContext.Provider>
    );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastApi {
    const ctx = useContext(ToastContext);
    if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
    return ctx;
}
