import { Link } from "react-router-dom";

function NotFound() {
    return (
        <div style={{ padding: "64px 20px", textAlign: "center", display: "flex", flexDirection: "column", gap: 12, alignItems: "center" }}>
            <h1>Page not found</h1>
            <p style={{ color: "var(--text-2)" }}>The page you are looking for does not exist.</p>
            <Link to="/">Back to the map</Link>
        </div>
    );
}

export default NotFound;
