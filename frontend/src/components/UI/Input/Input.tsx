import { useId } from "react";
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import styles from "./Input.module.css";

interface FieldShellProps {
    id: string;
    label: string;
    error?: string;
    hint?: string;
    children: ReactNode;
}

function FieldShell({ id, label, error, hint, children }: FieldShellProps) {
    return (
        <div className={styles.field}>
            <label htmlFor={id} className={styles.label}>
                {label}
            </label>
            {children}
            {error ? (
                <p id={`${id}-error`} className={styles.error} role="alert">
                    {error}
                </p>
            ) : hint ? (
                <p id={`${id}-hint`} className={styles.hint}>
                    {hint}
                </p>
            ) : null}
        </div>
    );
}

function describedBy(id: string, error?: string, hint?: string) {
    return error ? `${id}-error` : hint ? `${id}-hint` : undefined;
}

interface CommonProps {
    label: string;
    error?: string;
    hint?: string;
}

export function TextField({
    label,
    error,
    hint,
    ...rest
}: CommonProps & InputHTMLAttributes<HTMLInputElement>) {
    const id = useId();
    return (
        <FieldShell id={id} label={label} error={error} hint={hint}>
            <input
                id={id}
                className={`${styles.control} ${error ? styles.invalid : ""}`}
                aria-invalid={error ? true : undefined}
                aria-describedby={describedBy(id, error, hint)}
                {...rest}
            />
        </FieldShell>
    );
}

export function TextArea({
    label,
    error,
    hint,
    ...rest
}: CommonProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
    const id = useId();
    return (
        <FieldShell id={id} label={label} error={error} hint={hint}>
            <textarea
                id={id}
                className={`${styles.control} ${styles.textarea} ${error ? styles.invalid : ""}`}
                aria-invalid={error ? true : undefined}
                aria-describedby={describedBy(id, error, hint)}
                {...rest}
            />
        </FieldShell>
    );
}

export function SelectField({
    label,
    error,
    hint,
    children,
    ...rest
}: CommonProps & SelectHTMLAttributes<HTMLSelectElement>) {
    const id = useId();
    return (
        <FieldShell id={id} label={label} error={error} hint={hint}>
            <select
                id={id}
                className={`${styles.control} ${error ? styles.invalid : ""}`}
                aria-invalid={error ? true : undefined}
                aria-describedby={describedBy(id, error, hint)}
                {...rest}
            >
                {children}
            </select>
        </FieldShell>
    );
}
