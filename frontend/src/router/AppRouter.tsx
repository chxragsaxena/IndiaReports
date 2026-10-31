import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";

import RequireRole from "../auth/RequireRole";
import MainLayout from "../components/Layout/MainLayout";
import Skeleton from "../components/UI/Skeleton/Skeleton";

// Pages load on demand. The map library is large, so pages that do not draw a map
// never download it.
const Home = lazy(() => import("../pages/Home/Home"));
const ReportPage = lazy(() => import("../pages/Report/ReportPage"));
const Scorecards = lazy(() => import("../pages/Scorecards/Scorecards"));
const Dashboard = lazy(() => import("../pages/Dashboard/Dashboard"));
const Acknowledge = lazy(() => import("../pages/Acknowledge/Acknowledge"));
const Admin = lazy(() => import("../pages/Admin/Admin"));
const Team = lazy(() => import("../pages/Admin/Team"));
const Login = lazy(() => import("../pages/Login/Login"));
const ForgotPassword = lazy(() => import("../pages/Account/ForgotPassword"));
const ResetPassword = lazy(() => import("../pages/Account/ResetPassword"));
const VerifyEmail = lazy(() => import("../pages/Account/VerifyEmail"));
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
                        <Route path="/forgot-password" element={<ForgotPassword />} />
                        <Route path="/reset-password" element={<ResetPassword />} />
                        <Route path="/verify-email" element={<VerifyEmail />} />
                        <Route path="/ack" element={<Acknowledge />} />
                        <Route path="/scorecards" element={<Scorecards />} />

                        {/* Signed-in people */}
                        <Route path="/report" element={<RequireRole><ReportPage /></RequireRole>} />
                        <Route path="/my-reports" element={<RequireRole roles={["citizen"]}><MyReports /></RequireRole>} />

                        {/* Staff: area officers see their own queue, the main administrator sees everything */}
                        <Route path="/admin" element={<RequireRole roles={["admin", "officer"]}><Admin /></RequireRole>} />
                        <Route path="/admin/team" element={<RequireRole roles={["admin"]}><Team /></RequireRole>} />
                        <Route path="/dashboard" element={<RequireRole roles={["admin", "officer"]}><Dashboard /></RequireRole>} />

                        <Route path="*" element={<NotFound />} />
                    </Route>
                </Routes>
            </Suspense>
        </BrowserRouter>
    );
}

export default AppRouter;
