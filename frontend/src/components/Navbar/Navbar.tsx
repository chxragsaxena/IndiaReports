import { Link, NavLink } from "react-router-dom";

import { useAuth } from "../../auth/AuthContext";
import InstallButton from "../InstallButton/InstallButton";
import { isStaff } from "../../services/session";
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
                <NavLink to="/scorecards" className={linkClass}>
                    Scorecards
                </NavLink>
                {isStaff(user?.role) && (
                    <>
                        <NavLink to="/admin" end className={linkClass}>
                            {user?.role === "admin" ? "Admin" : "My queue"}
                        </NavLink>
                        {user?.role === "admin" && (
                            <NavLink to="/admin/team" className={linkClass}>
                                Team
                            </NavLink>
                        )}
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

            <InstallButton />

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

            {!isStaff(user?.role) && (
                <Link to="/report" className={styles.cta}>
                    Report an issue
                </Link>
            )}
        </header>
    );
}

export default Navbar;
