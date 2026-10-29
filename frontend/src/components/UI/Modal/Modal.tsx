import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";
import styles from "./Modal.module.css";

interface ModalProps {
    title: string;
    onClose: () => void;
    children: ReactNode;
}

function Modal({ title, onClose, children }: ModalProps) {
    const titleId = useId();
    const dialogRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
        const previouslyFocused = document.activeElement as HTMLElement | null;
        dialogRef.current?.focus();

        function onKey(e: KeyboardEvent) {
            if (e.key === "Escape") onClose();
        }
        document.addEventListener("keydown", onKey);
        return () => {
            document.removeEventListener("keydown", onKey);
            previouslyFocused?.focus();
        };
    }, [onClose]);

    return (
        <div className={styles.backdrop} onMouseDown={onClose}>
            <div
                ref={dialogRef}
                className={styles.dialog}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                tabIndex={-1}
                onMouseDown={(e) => e.stopPropagation()}
            >
                <div className={styles.header}>
                    <h2 id={titleId}>{title}</h2>
                    <button className={styles.close} onClick={onClose} aria-label="Close dialog">
                        &times;
                    </button>
                </div>
                {children}
            </div>
        </div>
    );
}

export default Modal;
