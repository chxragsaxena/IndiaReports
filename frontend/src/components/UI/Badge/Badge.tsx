import styles from "./Badge.module.css";

interface BadgeProps {
    text: string;
    type?: "open" | "resolved";
}

function Badge({
    text,
    type = "open",
}: BadgeProps) {
    return (
        <span
            className={`${styles.badge} ${styles[type]}`}
        >
            {text}
        </span>
    );
}

export default Badge;