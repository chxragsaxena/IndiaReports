import type { HTMLAttributes } from "react";
import styles from "./Card.module.css";

function Card({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
    return (
        <div className={[styles.card, className].filter(Boolean).join(" ")} {...rest}>
            {children}
        </div>
    );
}

export default Card;
