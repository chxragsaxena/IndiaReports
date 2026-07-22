import { NavLink } from "react-router-dom";
import styles from "./Navbar.module.css";

function Navbar() {
    return (
        <nav className={styles.navbar}>
            <div className={styles.logo}>
                🇮🇳 IndiaReports
            </div>

            <div className={styles.links}>
                <NavLink
                    to="/"
                    className={({ isActive }) =>
                        isActive ? styles.active : styles.link
                    }
                >
                    Home
                </NavLink>

                <NavLink
                    to="/report"
                    className={({ isActive }) =>
                        isActive ? styles.active : styles.link
                    }
                >
                    Report Issue
                </NavLink>

                <NavLink
                    to="/dashboard"
                    className={({ isActive }) =>
                        isActive ? styles.active : styles.link
                    }
                >
                    Dashboard
                </NavLink>
            </div>
        </nav>
    );
}

export default Navbar;