import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";

import MainLayout from "../components/Layout/MainLayout";
import Skeleton from "../components/UI/Skeleton/Skeleton";

// Pages load on demand. The map library is large, so the dashboard and the
// acknowledge page (which do not draw a map) never download it.
const Home = lazy(() => import("../pages/Home/Home"));
const ReportPage = lazy(() => import("../pages/Report/ReportPage"));
const Dashboard = lazy(() => import("../pages/Dashboard/Dashboard"));
const Acknowledge = lazy(() => import("../pages/Acknowledge/Acknowledge"));
const NotFound = lazy(() => import("../pages/NotFound/NotFound"));

function PageFallback() {
    return (
        <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 12 }} role="status" aria-label="Loading">
            <Skeleton width="30%" height={28} />
            <Skeleton height={120} />
        </div>
    );
}

function AppRouter() {
    return (
        <BrowserRouter>
            <Suspense fallback={<PageFallback />}>
                <Routes>
                    <Route element={<MainLayout />}>
                        <Route path="/" element={<Home />} />
                        <Route path="/report" element={<ReportPage />} />
                        <Route path="/dashboard" element={<Dashboard />} />
                        <Route path="/ack" element={<Acknowledge />} />
                        <Route path="*" element={<NotFound />} />
                    </Route>
                </Routes>
            </Suspense>
        </BrowserRouter>
    );
}

export default AppRouter;
