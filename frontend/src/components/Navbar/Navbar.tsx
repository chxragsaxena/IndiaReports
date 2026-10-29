import { Link, NavLink } from "react-router-dom";
import styles from "./Navbar.module.css";

function Navbar() {
    const linkClass = ({ isActive }: { isActive: boolean }) =>
        isActive ? `${styles.link} ${styles.active}` : styles.link;

    return (
        <header className={styles.navbar}>
            <Link to="/" className={styles.brand} aria-label="IndiaReports home">
                <span className={styles.mark} aria-hidden="true">
                    <span style={{ background: "#f59e0b" }} />
                    <span style={{ background: "#ffffff" }} />
                    <span style={{ background: "#138808" }} />
                </span>
                <span className={styles.name}>
                    India<strong>Reports</strong>
                </span>
            </Link>

            <nav className={styles.links} aria-label="Main">
                <NavLink to="/" end className={linkClass}>
                    Map
                </NavLink>
                <NavLink to="/dashboard" className={linkClass}>
                    Insights
                </NavLink>
            </nav>

            <Link to="/report" className={styles.cta}>
                Report an issue
            </Link>
        </header>
    );
}

export default Navbar;
