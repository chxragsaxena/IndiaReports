import { useCallback, useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature, FeatureCollection, Point } from "geojson";

import styles from "./IndiaMap.module.css";
import { MAP_STYLE } from "../../config/api";
import { getClusters, getPins } from "../../services/reportService";
import { EMPTY_COLLECTION, reportToFeature, toCollection } from "../../utils/geojson";
import type { PinFeature } from "../../utils/geojson";
import { useLiveSocket } from "../../hooks/useLiveSocket";
import type { LiveReport, LiveStatus } from "../../hooks/useLiveSocket";
import type { ReportStatus } from "../../types/report";

/** At or above this zoom the map shows individual reports, below it clusters (matches the server and notifier). */
const PIN_ZOOM = 11;
const PULSE_MS = 2500;
const INDIA_CENTER: [number, number] = [78.9629, 22.5937];

export interface MapView {
    lat: number;
    lng: number;
    zoom: number;
}

interface IndiaMapProps {
    statusFilter: string;
    categoryFilter: string;
    selectedId: string | null;
    onSelect: (id: string | null) => void;
    onLiveStatus: (status: LiveStatus) => void;
    /** Whether the reports for this view are loading, loaded, or could not be fetched. */
    onDataState?: (state: "loading" | "ready" | "error") => void;
    initialView?: MapView;
}

interface Pulse {
    lng: number;
    lat: number;
    start: number;
}

function source(map: maplibregl.Map, id: string): maplibregl.GeoJSONSource | null {
    return (map.getSource(id) as maplibregl.GeoJSONSource | undefined) ?? null;
}

function IndiaMap({
    statusFilter,
    categoryFilter,
    selectedId,
    onSelect,
    onLiveStatus,
    onDataState,
    initialView,
}: IndiaMapProps) {
    const containerRef = useRef<HTMLDivElement | null>(null);
    const mapRef = useRef<maplibregl.Map | null>(null);

    // Latest props/state for callbacks that outlive a render (map events, sockets).
    const filtersRef = useRef({ status: statusFilter, category: categoryFilter });
    const onSelectRef = useRef(onSelect);
    const onDataStateRef = useRef<(s: "loading" | "ready" | "error") => void>(() => undefined);
    const retryRef = useRef<number | null>(null);
    const lastKeyRef = useRef("");
    const requestRef = useRef<AbortController | null>(null);
    const debounceRef = useRef<number | null>(null);
    const pinsRef = useRef<Map<string, PinFeature>>(new Map());
    const pulsesRef = useRef<Pulse[]>([]);
    const frameRef = useRef<number | null>(null);

    useEffect(() => {
        filtersRef.current = { status: statusFilter, category: categoryFilter };
        onSelectRef.current = onSelect;
        onDataStateRef.current = onDataState ?? (() => undefined);
    });

    const matchesFilters = useCallback((status: string | undefined, category: string) => {
        const { status: s, category: c } = filtersRef.current;
        return (s === "ALL" || s === status) && (c === "ALL" || c === category);
    }, []);

    const loadViewport = useCallback(async (map: maplibregl.Map) => {
        const pins = source(map, "reports");
        const clusters = source(map, "clusters");
        if (!pins || !clusters) return;

        const b = map.getBounds();
        const latPad = (b.getNorth() - b.getSouth()) * 0.25;
        const lngPad = (b.getEast() - b.getWest()) * 0.25;
        const view = {
            minLat: b.getSouth() - latPad,
            maxLat: b.getNorth() + latPad,
            minLng: b.getWest() - lngPad,
            maxLng: b.getEast() + lngPad,
        };
        const { status, category } = filtersRef.current;
        const zoom = map.getZoom();

        const key = [
            view.minLat.toFixed(2), view.maxLat.toFixed(2), view.minLng.toFixed(2), view.maxLng.toFixed(2),
            Math.floor(zoom), status, category,
        ].join(",");
        if (key === lastKeyRef.current) return;
        lastKeyRef.current = key;

        // A newer pan/zoom supersedes any request still in flight.
        requestRef.current?.abort();
        const controller = new AbortController();
        requestRef.current = controller;
        onDataStateRef.current("loading");
        if (retryRef.current) window.clearTimeout(retryRef.current);

        const filters = {
            status: status === "ALL" ? undefined : status,
            category: category === "ALL" ? undefined : category,
        };

        try {
            if (zoom < PIN_ZOOM) {
                const data = await getClusters({ ...view, ...filters, zoom: Math.floor(zoom) }, controller.signal);
                const features: Feature<Point, { count: number }>[] = data.map((c) => ({
                    type: "Feature",
                    geometry: { type: "Point", coordinates: [c.longitude, c.latitude] },
                    properties: { count: c.count },
                }));
                clusters.setData({ type: "FeatureCollection", features });
                pinsRef.current.clear();
                pins.setData(EMPTY_COLLECTION);
            } else {
                const data = await getPins({ ...view, ...filters }, controller.signal);
                pinsRef.current = new Map(data.pins.map((r) => [r.id, reportToFeature(r)]));
                pins.setData(toCollection([...pinsRef.current.values()]));
                clusters.setData({ type: "FeatureCollection", features: [] });
            }
            onDataStateRef.current("ready");
        } catch (err) {
            if ((err as { code?: string }).code !== "ERR_CANCELED") {
                lastKeyRef.current = ""; // allow a retry on the next move
                console.error(err);
                // Say so, and keep trying: a sleeping server usually answers on the next attempt.
                onDataStateRef.current("error");
                if (retryRef.current) window.clearTimeout(retryRef.current);
                retryRef.current = window.setTimeout(() => void loadViewport(map), 6000);
            }
        }
    }, []);

    const addPulse = useCallback((lng: number, lat: number) => {
        const map = mapRef.current;
        if (!map) return;
        pulsesRef.current.push({ lng, lat, start: performance.now() });
        if (frameRef.current !== null) return;

        const tick = (now: number) => {
            pulsesRef.current = pulsesRef.current.filter((p) => now - p.start < PULSE_MS);
            const features: Feature<Point, { t: number }>[] = pulsesRef.current.map((p) => ({
                type: "Feature",
                geometry: { type: "Point", coordinates: [p.lng, p.lat] },
                properties: { t: (now - p.start) / PULSE_MS },
            }));
            source(map, "pulses")?.setData({ type: "FeatureCollection", features });
            frameRef.current = pulsesRef.current.length > 0 ? requestAnimationFrame(tick) : null;
        };
        frameRef.current = requestAnimationFrame(tick);
    }, []);

    const { status: liveStatus, setViewport } = useLiveSocket({
        onReport: (event, r: LiveReport) => {
            const map = mapRef.current;
            if (!map) return;
            const status: ReportStatus | undefined = r.new_status ?? r.status;
            const visible = matchesFilters(status, r.category);

            if (event === "ReportCreated" && visible) {
                addPulse(r.longitude, r.latitude);
                if (map.getZoom() >= PIN_ZOOM) {
                    pinsRef.current.set(r.report_id, reportToFeature({
                        id: r.report_id, status: status ?? "OPEN", latitude: r.latitude, longitude: r.longitude,
                    }));
                    source(map, "reports")?.setData(toCollection([...pinsRef.current.values()]));
                }
            } else if (event === "ReportStatusChanged" && pinsRef.current.has(r.report_id)) {
                if (visible && status) {
                    const pin = pinsRef.current.get(r.report_id)!;
                    pinsRef.current.set(r.report_id, { ...pin, properties: { ...pin.properties, status } });
                } else {
                    pinsRef.current.delete(r.report_id);
                }
                source(map, "reports")?.setData(toCollection([...pinsRef.current.values()]));
            }
        },
        onRefresh: () => {
            const map = mapRef.current;
            if (!map) return;
            lastKeyRef.current = "";
            void loadViewport(map);
        },
    });

    useEffect(() => {
        onLiveStatus(liveStatus);
    }, [liveStatus, onLiveStatus]);

    // Create the map once.
    useEffect(() => {
        const container = containerRef.current;
        if (!container || mapRef.current) return;

        const map = new maplibregl.Map({
            container,
            style: MAP_STYLE,
            center: initialView ? [initialView.lng, initialView.lat] : INDIA_CENTER,
            zoom: initialView?.zoom ?? 4.4,
            minZoom: 3.5,
            maxBounds: [[58, 0], [108, 44]],
            attributionControl: { compact: true },
        });
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
        mapRef.current = map;

        const syncViewport = () => {
            const b = map.getBounds();
            setViewport([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()], map.getZoom());
        };

        map.on("load", () => {
            const empty = { type: "geojson", data: EMPTY_COLLECTION } as const;
            map.addSource("reports", empty);
            map.addSource("clusters", { type: "geojson", data: { type: "FeatureCollection", features: [] } as FeatureCollection });
            map.addSource("pulses", { type: "geojson", data: { type: "FeatureCollection", features: [] } as FeatureCollection });

            map.addLayer({
                id: "cluster-layer",
                type: "circle",
                source: "clusters",
                paint: {
                    "circle-radius": ["interpolate", ["linear"], ["get", "count"], 1, 16, 10, 20, 50, 28, 200, 38, 1000, 48],
                    "circle-color": ["interpolate", ["linear"], ["get", "count"], 1, "#4f7be0", 25, "#2f56b8", 100, "#1b3a8c", 500, "#0e1f57"],
                    "circle-opacity": 0.92,
                    "circle-stroke-width": 3,
                    "circle-stroke-color": "rgba(255,255,255,0.9)",
                },
            });

            map.addLayer({
                id: "cluster-count",
                type: "symbol",
                source: "clusters",
                layout: {
                    "text-field": ["to-string", ["get", "count"]],
                    "text-font": ["Noto Sans Bold"],
                    "text-size": 13,
                    "text-allow-overlap": true,
                },
                paint: { "text-color": "#ffffff" },
            });

            map.addLayer({
                id: "pulse-layer",
                type: "circle",
                source: "pulses",
                paint: {
                    "circle-radius": ["interpolate", ["linear"], ["get", "t"], 0, 6, 1, 46],
                    "circle-color": "rgba(27,58,140,0.18)",
                    "circle-stroke-width": 2,
                    "circle-stroke-color": "#1b3a8c",
                    "circle-stroke-opacity": ["-", 1, ["get", "t"]],
                    "circle-opacity": ["-", 1, ["get", "t"]],
                },
            });

            map.addLayer({
                id: "selected-ring",
                type: "circle",
                source: "reports",
                filter: ["==", ["get", "id"], ""],
                paint: {
                    "circle-radius": 16,
                    "circle-color": "rgba(27,58,140,0.12)",
                    "circle-stroke-width": 3,
                    "circle-stroke-color": "#1b3a8c",
                },
            });

            map.addLayer({
                id: "reports-layer",
                type: "circle",
                source: "reports",
                paint: {
                    "circle-radius": 8,
                    "circle-color": [
                        "match", ["get", "status"],
                        "OPEN", "#dc2626",
                        "IN_PROGRESS", "#d97706",
                        "RESOLVED", "#16a34a",
                        "#3b82f6",
                    ],
                    "circle-stroke-width": 2.5,
                    "circle-stroke-color": "#ffffff",
                },
            });

            map.on("click", "cluster-layer", (e) => {
                const f = e.features?.[0];
                if (!f) return;
                map.easeTo({ center: (f.geometry as Point).coordinates as [number, number], zoom: map.getZoom() + 2 });
            });

            map.on("click", "reports-layer", (e) => {
                const id = e.features?.[0]?.properties?.id;
                if (typeof id === "string") onSelectRef.current(id);
            });

            map.on("click", (e) => {
                const hit = map.queryRenderedFeatures(e.point, { layers: ["reports-layer", "cluster-layer"] });
                if (hit.length === 0) onSelectRef.current(null);
            });

            for (const layer of ["reports-layer", "cluster-layer"]) {
                map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
                map.on("mouseleave", layer, () => (map.getCanvas().style.cursor = ""));
            }

            syncViewport();
            void loadViewport(map);
        });

        map.on("moveend", () => {
            if (debounceRef.current) window.clearTimeout(debounceRef.current);
            debounceRef.current = window.setTimeout(() => {
                syncViewport();
                void loadViewport(map);
            }, 250);
        });

        const resizer = new ResizeObserver(() => map.resize());
        resizer.observe(container);

        return () => {
            resizer.disconnect();
            if (debounceRef.current) window.clearTimeout(debounceRef.current);
            if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
            frameRef.current = null;
            requestRef.current?.abort();
            if (retryRef.current) window.clearTimeout(retryRef.current);
            map.remove();
            mapRef.current = null;
        };
        // The map is created once; later prop changes are handled by the effects below.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Filters changed: drop the cache key and reload.
    useEffect(() => {
        const map = mapRef.current;
        if (!map || !map.getSource("reports")) return;
        lastKeyRef.current = "";
        void loadViewport(map);
    }, [statusFilter, categoryFilter, loadViewport]);

    // Highlight the selected report.
    useEffect(() => {
        const map = mapRef.current;
        if (!map || !map.getLayer("selected-ring")) return;
        map.setFilter("selected-ring", ["==", ["get", "id"], selectedId ?? ""]);
    }, [selectedId]);

    return <div ref={containerRef} className={styles.map} />;
}

export default IndiaMap;
