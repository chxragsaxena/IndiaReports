import { Outlet } from "react-router-dom";

import Navbar from "../Navbar/Navbar";
import { ToastProvider } from "../UI/Toast/Toast";
import styles from "./MainLayout.module.css";

function MainLayout() {
    return (
        <ToastProvider>
            <div className={styles.shell}>
                <Navbar />
                <main className={styles.main}>
                    <Outlet />
                </main>
            </div>
        </ToastProvider>
    );
}

export default MainLayout;
