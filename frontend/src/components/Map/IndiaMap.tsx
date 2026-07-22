import { useEffect, useRef, useState } from "react";
import maplibregl, { GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import styles from "./IndiaMap.module.css";

import { getReports } from "../../services/reportService";
import { reportsToGeoJSON } from "../../utils/geojson";

import type { Report } from "../../types/report";

function IndiaMap() {
    const mapContainer = useRef<HTMLDivElement | null>(null);
    const mapRef = useRef<maplibregl.Map | null>(null);

    const [reports, setReports] = useState<Report[]>([]);
    const [mapLoaded, setMapLoaded] = useState(false);

    useEffect(() => {
        if (!mapContainer.current || mapRef.current) return;

        const map = new maplibregl.Map({
            container: mapContainer.current,
            style: "https://demotiles.maplibre.org/style.json",
            center: [78.9629, 22.5937],
            zoom: 4.5,
        });

        map.addControl(
            new maplibregl.NavigationControl(),
            "top-right"
        );

        map.on("load", () => {
            setMapLoaded(true);
        });

        mapRef.current = map;

        return () => {
            map.remove();
            mapRef.current = null;
        };
    }, []);

    useEffect(() => {
        async function loadReports() {
            try {
                const data = await getReports();
                setReports(data);
            } catch (err) {
                console.error(err);
            }
        }

        loadReports();
    }, []);

    useEffect(() => {
        if (!mapLoaded || !mapRef.current) return;

        const map = mapRef.current;

        const geojson = reportsToGeoJSON(reports);

        const existingSource = map.getSource("reports") as GeoJSONSource | undefined;

        if (existingSource) {
            existingSource.setData(geojson);
            return;
        }

        map.addSource("reports", {
            type: "geojson",
            data: geojson
        });

        map.addLayer({
            id: "heatmap",
            type: "heatmap",
            source: "reports",
            maxzoom: 8,
            paint: {
                "heatmap-weight": 1,

                "heatmap-intensity": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    0,
                    1,
                    8,
                    3
                ],

                "heatmap-radius": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    0,
                    6,
                    8,
                    30
                ],

                "heatmap-opacity": [
                    "interpolate",
                    ["linear"],
                    ["zoom"],
                    7,
                    1,
                    8,
                    0
                ],

                "heatmap-color": [
                    "interpolate",
                    ["linear"],
                    ["heatmap-density"],

                    0,
                    "rgba(33,102,172,0)",

                    0.2,
                    "#3b82f6",

                    0.4,
                    "#22c55e",

                    0.6,
                    "#facc15",

                    0.8,
                    "#f97316",

                    1,
                    "#ef4444"
                ]
            }
        });

        map.addLayer({
            id: "reports-layer",
            type: "circle",
            source: "reports",
            minzoom: 8,
            maxzoom: 24,
            paint: {
                "circle-radius": 8,

                "circle-color": [
                    "match",
                    ["get", "status"],

                    "OPEN",
                    "#ef4444",

                    "IN_PROGRESS",
                    "#f59e0b",

                    "RESOLVED",
                    "#22c55e",

                    "#3b82f6"
                ],

                "circle-stroke-width": 2,

                "circle-stroke-color": "#ffffff"
            }
        });        
        map.on("click", "reports-layer", (e) => {
            const feature = e.features?.[0];

            if (!feature) return;

            const properties = feature.properties;

            const coordinates = (
                feature.geometry as GeoJSON.Point
            ).coordinates as [number, number];

            new maplibregl.Popup({
                closeButton: true,
                closeOnClick: true,
            })
                .setLngLat(coordinates)
                .setHTML(`
                    <div style="min-width:220px">
                        <h3 style="margin-bottom:8px">
                            ${properties?.title}
                        </h3>

                        <p style="margin-bottom:12px">
                            ${properties?.description}
                        </p>

                        <hr />

                        <strong>City:</strong> ${properties?.city}<br/>
                        <strong>Category:</strong> ${properties?.category}<br/>
                        <strong>Status:</strong> ${properties?.status}
                    </div>
                `)
                .addTo(map);
        });

        map.on("mouseenter", "reports-layer", () => {
            map.getCanvas().style.cursor = "pointer";
        });

        map.on("mouseleave", "reports-layer", () => {
            map.getCanvas().style.cursor = "";
        });

    }, [reports, mapLoaded]);

    return (
        <div
            ref={mapContainer}
            className={styles.map}
        />
    );
}

export default IndiaMap;