import {
    BrowserRouter,
    Routes,
    Route,
} from "react-router-dom";

import MainLayout from "../components/Layout/MainLayout";

import Home from "../pages/Home/Home";
import ReportPage from "../pages/Report/ReportPage";
import Dashboard from "../pages/Dashboard/Dashboard";

function AppRouter() {
    return (
        <BrowserRouter>
            <Routes>
                <Route element={<MainLayout />}>
                    <Route
                        path="/"
                        element={<Home />}
                    />

                    <Route
                        path="/report"
                        element={<ReportPage />}
                    />

                    <Route
                        path="/dashboard"
                        element={<Dashboard />}
                    />
                </Route>
            </Routes>
        </BrowserRouter>
    );
}

export default AppRouter;