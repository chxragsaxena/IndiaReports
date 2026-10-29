import { Link, NavLink } from "react-router-dom";

import { useAuth } from "../../auth/AuthContext";
import styles from "./Navbar.module.css";

function Navbar() {
    const { user, signOut } = useAuth();
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
                {user?.role === "admin" && (
                    <>
                        <NavLink to="/admin" className={linkClass}>
                            Admin
                        </NavLink>
                        <NavLink to="/dashboard" className={linkClass}>
                            Insights
                        </NavLink>
                    </>
                )}
                {user?.role === "citizen" && (
                    <NavLink to="/my-reports" className={linkClass}>
                        My reports
                    </NavLink>
                )}
            </nav>

            {user ? (
                <div className={styles.account}>
                    <span className={styles.who} title={user.email}>
                        {user.name}
                    </span>
                    <button className={styles.signOut} onClick={signOut}>
                        Sign out
                    </button>
                </div>
            ) : (
                <Link to="/login" className={styles.signIn}>
                    Sign in
                </Link>
            )}

            {user?.role !== "admin" && (
                <Link to="/report" className={styles.cta}>
                    Report an issue
                </Link>
            )}
        </header>
    );
}

export default Navbar;
