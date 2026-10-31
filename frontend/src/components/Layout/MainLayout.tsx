import { Outlet } from "react-router-dom";

import Navbar from "../Navbar/Navbar";
import VerifyBanner from "../VerifyBanner/VerifyBanner";
import { AuthProvider } from "../../auth/AuthContext";
import { ToastProvider } from "../UI/Toast/Toast";
import styles from "./MainLayout.module.css";

function MainLayout() {
    return (
        <ToastProvider>
            <AuthProvider>
                <div className={styles.shell}>
                    <Navbar />
                    <VerifyBanner />
                    <main className={styles.main}>
                        <Outlet />
                    </main>
                </div>
            </AuthProvider>
        </ToastProvider>
    );
}

export default MainLayout;
