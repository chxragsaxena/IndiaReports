import styles from "./Skeleton.module.css";

function Skeleton({ width = "100%", height = 16 }: { width?: string | number; height?: string | number }) {
    return <span className={styles.skeleton} style={{ width, height }} aria-hidden="true" />;
}

export default Skeleton;
