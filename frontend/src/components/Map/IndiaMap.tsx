import { useEffect, useRef } from "react";
import maplibregl, { GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import styles from "./IndiaMap.module.css";
import type { FeatureCollection, Point } from "geojson";
import {
    getReports,
    getClusters,
} from "../../services/reportService";
import { reportsToGeoJSON } from "../../utils/geojson";

interface IndiaMapProps {
    statusFilter: string;
    categoryFilter: string;
}

function IndiaMap({
    statusFilter,
    categoryFilter,
}: IndiaMapProps) {
    const mapContainer = useRef<HTMLDivElement | null>(null);
    const mapRef = useRef<maplibregl.Map | null>(null);
    const lastViewportRef = useRef("");
    const timeoutRef = useRef<number | null>(null);
    const statusFilterRef = useRef(statusFilter);
    const categoryFilterRef = useRef(categoryFilter);
    useEffect(() => {
        statusFilterRef.current = statusFilter;
        categoryFilterRef.current = categoryFilter;
    }, [statusFilter, categoryFilter]);

    async function loadViewport(
    map: maplibregl.Map
) {
    try {

        const bounds = map.getBounds();

        const south = bounds.getSouth();
        const north = bounds.getNorth();
        const west = bounds.getWest();
        const east = bounds.getEast();

        const latPadding = (north - south) * 0.25;
        const lngPadding = (east - west) * 0.25;

        const minLat = south - latPadding;
        const maxLat = north + latPadding;
        const minLng = west - lngPadding;
        const maxLng = east + lngPadding;

        const viewportKey = [
            minLat.toFixed(2),
            maxLat.toFixed(2),
            minLng.toFixed(2),
            maxLng.toFixed(2),
            statusFilterRef.current,
            categoryFilterRef.current,
        ].join(",");

        if (viewportKey === lastViewportRef.current) {
            return;
        }

        lastViewportRef.current = viewportKey;

        const zoom = map.getZoom();

        const reportsSource = map.getSource("reports");
        const clustersSource = map.getSource("clusters");

        if (!reportsSource || !clustersSource) {
            return;
        }

        if (zoom < 8) {

            const clusters = await getClusters({
                minLat,
                maxLat,
                minLng,
                maxLng,
                zoom: Math.floor(zoom),
                status:
                    statusFilterRef.current === "ALL"
                        ? undefined
                        : statusFilterRef.current,
                category:
                    categoryFilterRef.current === "ALL"
                        ? undefined
                        : categoryFilterRef.current,
            });

            const clusterGeoJson: FeatureCollection<Point, {count: number}> = {
                type: "FeatureCollection",
                features: clusters.map(cluster => ({
                    type: "Feature",
                    geometry: {
                        type: "Point",
                        coordinates: [
                            cluster.longitude,
                            cluster.latitude,
                        ],
                    },
                    properties: {
                        count: cluster.count,
                    },
                })),
            };

            clustersSource.setData(clusterGeoJson);

            reportsSource.setData({
                type: "FeatureCollection",
                features: [],
            });

        } else {

            const reports = await getReports({
                minLat,
                maxLat,
                minLng,
                maxLng,
                status:
                    statusFilterRef.current === "ALL"
                        ? undefined
                        : statusFilterRef.current,
                category:
                    categoryFilterRef.current=== "ALL"
                        ? undefined
                        : categoryFilterRef.current,
            });

            reportsSource.setData(
                reportsToGeoJSON(reports)
            );

            clustersSource.setData({
                type: "FeatureCollection",
                features: [],
            });

        }

    } catch (err) {
        console.error(err);
    }
}

    useEffect(() => {

        if (
            !mapContainer.current ||
            mapRef.current
        ) {
            return;
        }

        const map =
            new maplibregl.Map({

                container:
                    mapContainer.current,

                style:
                    "https://demotiles.maplibre.org/style.json",

                center: [
                    78.9629,
                    22.5937,
                ],

                zoom: 4.5,
            });

        map.addControl(
            new maplibregl.NavigationControl(),
            "top-right"
        );

        mapRef.current = map;

            map.on("load", () => {

            map.addSource("reports", {
                type: "geojson",
                data: {
                    type: "FeatureCollection",
                    features: [],
                },
            });

            map.addSource("clusters", {
                type: "geojson",
                data: {
                    type: "FeatureCollection",
                    features: [],
                },
            });

            map.addLayer({
                id: "cluster-layer",
                type: "circle",
                source: "clusters",
                maxzoom: 8,
                paint: {
                    "circle-radius": [
                        "interpolate",
                        ["linear"],
                        ["get", "count"],

                        1,
                        14,

                        10,
                        18,

                        25,
                        24,

                        50,
                        30,

                        100,
                        36,
                    ],

                    "circle-color": [
                        "interpolate",
                        ["linear"],
                        ["get", "count"],

                        1,
                        "#facc15",

                        20,
                        "#f97316",

                        50,
                        "#ef4444",

                        100,
                        "#991b1b",
                    ],

                    "circle-stroke-width": 2,
                    "circle-stroke-color": "#ffffff",
                },
            });

            map.addLayer({
                id: "cluster-count",
                type: "symbol",
                source: "clusters",
                maxzoom: 8,

                layout: {
                    "text-field": [
                        "to-string",
                        ["get", "count"],
                    ],

                    "text-size": 14,

                    "text-font": [
                        "Open Sans Regular",
                    ],
                },

                paint: {
                    "text-color": "#ffffff",
                },
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

                        "#3b82f6",
                    ],

                    "circle-stroke-width": 2,

                    "circle-stroke-color":
                        "#ffffff",
                },
            });
            map.on("click", "cluster-layer", (e) => {

                const feature = e.features?.[0];

                if (!feature) return;

                const coordinates =
                    (feature.geometry as Point)
                        .coordinates as [number, number];

                map.easeTo({
                    center: coordinates,
                    zoom: map.getZoom() + 2,
                });

            });

            void loadViewport(map);
            map.on("click", "reports-layer", (e) => {

                const feature = e.features?.[0];

            if (!feature) return;

            const properties = feature.properties;

        const coordinates =
            (feature.geometry as Point)
                .coordinates as [number, number];

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

                    <hr/>

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

    map.on("mouseenter", "cluster-layer", () => {
        map.getCanvas().style.cursor = "pointer";
    });

    map.on("mouseleave", "cluster-layer", () => {
        map.getCanvas().style.cursor = "";
    });

    });

        map.on("moveend", () => {
            if (timeoutRef.current) {
                clearTimeout(timeoutRef.current);
            }

            timeoutRef.current = window.setTimeout(() => {
                void loadViewport(map);
            }, 200);
        });

        return () => {
            map.remove();
            mapRef.current = null;
        };
    }, []);

    useEffect(() => {
        if (!mapRef.current) {
            return;
        }

        lastViewportRef.current = "";

        void loadViewport(mapRef.current);
    }, [statusFilter, categoryFilter]);
 
    return (
        <div
            ref={mapContainer}
            className={styles.map}
        />
    );
}

export default IndiaMap;