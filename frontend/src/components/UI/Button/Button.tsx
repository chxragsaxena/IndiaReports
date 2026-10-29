import type { ButtonHTMLAttributes, ReactNode } from "react";
import styles from "./Button.module.css";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    variant?: "primary" | "secondary" | "ghost";
    size?: "md" | "sm";
    loading?: boolean;
    children: ReactNode;
}

function Button({
    variant = "primary",
    size = "md",
    loading = false,
    disabled,
    className,
    children,
    type = "button",
    ...rest
}: ButtonProps) {
    const classes = [styles.button, styles[variant], styles[size], className].filter(Boolean).join(" ");

    return (
        <button
            type={type}
            className={classes}
            disabled={disabled || loading}
            aria-busy={loading || undefined}
            {...rest}
        >
            {loading && <span className={styles.spinner} aria-hidden="true" />}
            {children}
        </button>
    );
}

export default Button;
