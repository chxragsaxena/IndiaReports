import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";

import RequireRole from "../auth/RequireRole";
import MainLayout from "../components/Layout/MainLayout";
import Skeleton from "../components/UI/Skeleton/Skeleton";

// Pages load on demand. The map library is large, so pages that do not draw a map
// never download it.
const Home = lazy(() => import("../pages/Home/Home"));
const ReportPage = lazy(() => import("../pages/Report/ReportPage"));
const Dashboard = lazy(() => import("../pages/Dashboard/Dashboard"));
const Acknowledge = lazy(() => import("../pages/Acknowledge/Acknowledge"));
const Admin = lazy(() => import("../pages/Admin/Admin"));
const Login = lazy(() => import("../pages/Login/Login"));
const MyReports = lazy(() => import("../pages/MyReports/MyReports"));
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
                        {/* Anyone: the public map, the sign-in page and the officer acknowledge link */}
                        <Route path="/" element={<Home />} />
                        <Route path="/login" element={<Login />} />
                        <Route path="/ack" element={<Acknowledge />} />

                        {/* Signed-in people */}
                        <Route path="/report" element={<RequireRole><ReportPage /></RequireRole>} />
                        <Route path="/my-reports" element={<RequireRole roles={["citizen"]}><MyReports /></RequireRole>} />

                        {/* Administrators only */}
                        <Route path="/admin" element={<RequireRole roles={["admin"]}><Admin /></RequireRole>} />
                        <Route path="/dashboard" element={<RequireRole roles={["admin"]}><Dashboard /></RequireRole>} />

                        <Route path="*" element={<NotFound />} />
                    </Route>
                </Routes>
            </Suspense>
        </BrowserRouter>
    );
}

export default AppRouter;
