import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import { MAP_STYLE } from "../../config/api";
import type { QueueMapData } from "../../services/adminService";
import styles from "./QueueMap.module.css";

interface Props {
    data: QueueMapData;
    /** A report to fly to and highlight (from the list's "Show on map"). */
    focusId: string | null;
    onOpen: (reportId: string) => void;
}

const COLOURS = { OPEN: "#dc2626", IN_PROGRESS: "#d97706", RESOLVED: "#16a34a" } as const;

type Position = [number, number];

/** Every [lng, lat] inside a GeoJSON geometry, however deeply nested. */
function positions(coords: unknown, out: Position[] = []): Position[] {
    if (Array.isArray(coords)) {
        if (typeof coords[0] === "number" && typeof coords[1] === "number") out.push([coords[0], coords[1]]);
        else coords.forEach((c) => positions(c, out));
    }
    return out;
}

function toFeatures(data: QueueMapData, focusId: string | null) {
    return {
        areas: {
            type: "FeatureCollection" as const,
            features: data.areas.map((a) => ({
                type: "Feature" as const,
                properties: { name: a.name },
                geometry: a.geometry as unknown as GeoJSON.Geometry,
            })),
        },
        reports: {
            type: "FeatureCollection" as const,
            features: data.reports.map((r) => ({
                type: "Feature" as const,
                properties: { id: r.id, title: r.title, status: r.status, late: r.overdue || r.escalated, focus: r.id === focusId },
                geometry: { type: "Point" as const, coordinates: [r.longitude, r.latitude] },
            })),
        },
    };
}

/** The staff member's queue on a map: the boundary of the area they answer for, and every report in it. */
function QueueMap({ data, focusId, onOpen }: Props) {
    const containerRef = useRef<HTMLDivElement | null>(null);
    const mapRef = useRef<maplibregl.Map | null>(null);
    const [ready, setReady] = useState(false);
    const onOpenRef = useRef(onOpen);
    const fitted = useRef(false);

    useEffect(() => {
        onOpenRef.current = onOpen;
    });

    useEffect(() => {
        const container = containerRef.current;
        if (!container || mapRef.current) return;
        const map = new maplibregl.Map({
            container,
            style: MAP_STYLE,
            center: [78.9629, 22.5937],
            zoom: 4.4,
            attributionControl: { compact: true },
        });
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
        const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });

        map.on("load", () => {
            const empty = { type: "FeatureCollection" as const, features: [] };
            map.addSource("areas", { type: "geojson", data: empty });
            map.addSource("reports", { type: "geojson", data: empty });
            map.addLayer({ id: "areas-fill", type: "fill", source: "areas", paint: { "fill-color": "#1b3a8c", "fill-opacity": 0.07 } });
            map.addLayer({
                id: "areas-line",
                type: "line",
                source: "areas",
                paint: { "line-color": "#1b3a8c", "line-width": 2.2, "line-dasharray": [2, 1.5] },
            });
            map.addLayer({
                id: "reports-halo",
                type: "circle",
                source: "reports",
                filter: ["==", ["get", "focus"], true],
                paint: { "circle-radius": 18, "circle-color": "#1b3a8c", "circle-opacity": 0.22 },
            });
            map.addLayer({
                id: "reports-dots",
                type: "circle",
                source: "reports",
                paint: {
                    "circle-radius": ["case", ["get", "late"], 8, 6.5],
                    "circle-color": ["match", ["get", "status"], "OPEN", COLOURS.OPEN, "IN_PROGRESS", COLOURS.IN_PROGRESS, "RESOLVED", COLOURS.RESOLVED, "#3b82f6"],
                    "circle-stroke-color": ["case", ["get", "late"], "#111827", "#ffffff"],
                    "circle-stroke-width": ["case", ["get", "late"], 2.5, 1.5],
                },
            });

            map.on("mouseenter", "reports-dots", (e) => {
                map.getCanvas().style.cursor = "pointer";
                const f = e.features?.[0];
                if (!f || f.geometry.type !== "Point") return;
                popup.setLngLat(f.geometry.coordinates as Position).setText(String(f.properties?.title ?? "")).addTo(map);
            });
            map.on("mouseleave", "reports-dots", () => {
                map.getCanvas().style.cursor = "";
                popup.remove();
            });
            map.on("click", "reports-dots", (e) => {
                const id = e.features?.[0]?.properties?.id;
                if (typeof id === "string") onOpenRef.current(id);
            });
            setReady(true);
        });

        mapRef.current = map;
        const resizer = new ResizeObserver(() => map.resize());
        resizer.observe(container);
        return () => {
            resizer.disconnect();
            popup.remove();
            map.remove();
            mapRef.current = null;
            fitted.current = false;
        };
    }, []);

    // Push the data in, then frame it: the focused report if there is one, else the whole area and its pins.
    useEffect(() => {
        const map = mapRef.current;
        if (!map || !ready) return;
        const features = toFeatures(data, focusId);
        (map.getSource("areas") as maplibregl.GeoJSONSource).setData(features.areas);
        (map.getSource("reports") as maplibregl.GeoJSONSource).setData(features.reports);

        const focus = focusId ? data.reports.find((r) => r.id === focusId) : undefined;
        if (focus) {
            map.flyTo({ center: [focus.longitude, focus.latitude], zoom: 15 });
            fitted.current = true;
            return;
        }
        if (fitted.current) return; // do not yank the view while the person is looking around
        const points = [...data.areas.flatMap((a) => positions(a.geometry.coordinates)), ...data.reports.map((r): Position => [r.longitude, r.latitude])];
        if (points.length === 0) return;
        const bounds = points.reduce((b, p) => b.extend(p), new maplibregl.LngLatBounds(points[0], points[0]));
        map.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 0 });
        fitted.current = true;
    }, [data, focusId, ready]);

    const counts = { OPEN: 0, IN_PROGRESS: 0, RESOLVED: 0 };
    let late = 0;
    for (const r of data.reports) {
        if (r.status in counts) counts[r.status as keyof typeof counts] += 1;
        if (r.overdue || r.escalated) late += 1;
    }

    return (
        <div className={styles.wrapper}>
            <div ref={containerRef} className={styles.map} />
            <div className={styles.legend} aria-label="Map key">
                <span><i style={{ background: COLOURS.OPEN }} /> Open {counts.OPEN}</span>
                <span><i style={{ background: COLOURS.IN_PROGRESS }} /> In progress {counts.IN_PROGRESS}</span>
                <span><i style={{ background: COLOURS.RESOLVED }} /> Resolved {counts.RESOLVED}</span>
                <span><i className={styles.ring} /> Overdue or escalated {late}</span>
                <span className={styles.dash}>Dashed line: {data.areas.length === 1 ? data.areas[0].name : "area boundaries"}</span>
            </div>
            {data.truncated && <p className={styles.note}>Showing the newest {data.reports.length} reports.</p>}
            {data.areas.length === 0 && <p className={styles.note}>No area boundary is set for this account.</p>}
        </div>
    );
}

export default QueueMap;
