import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import Button from "../../components/UI/Button/Button";
import { MAP_STYLE } from "../../config/api";
import { isInIndia } from "../../types/report";
import styles from "./LocationPicker.module.css";

interface LocationPickerProps {
    latitude: number | null;
    longitude: number | null;
    onPick: (lat: number, lng: number) => void;
    onOutsideIndia: () => void;
}

function LocationPicker({ latitude, longitude, onPick, onOutsideIndia }: LocationPickerProps) {
    const containerRef = useRef<HTMLDivElement | null>(null);
    const mapRef = useRef<maplibregl.Map | null>(null);
    const markerRef = useRef<maplibregl.Marker | null>(null);
    const handlersRef = useRef({ onPick, onOutsideIndia });
    const [locating, setLocating] = useState(false);
    const [geoError, setGeoError] = useState("");

    useEffect(() => {
        handlersRef.current = { onPick, onOutsideIndia };
    });

    useEffect(() => {
        const container = containerRef.current;
        if (!container || mapRef.current) return;

        const map = new maplibregl.Map({
            container,
            style: MAP_STYLE,
            center: [78.9629, 22.5937],
            zoom: 4.4,
            minZoom: 3.5,
            maxBounds: [[58, 0], [108, 44]],
            attributionControl: { compact: true },
        });
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

        map.on("click", (e) => {
            const { lng, lat } = e.lngLat;
            if (!isInIndia(lat, lng)) {
                handlersRef.current.onOutsideIndia();
                return;
            }
            handlersRef.current.onPick(lat, lng);
        });

        mapRef.current = map;
        const resizer = new ResizeObserver(() => map.resize());
        resizer.observe(container);

        return () => {
            resizer.disconnect();
            map.remove();
            mapRef.current = null;
            markerRef.current = null;
        };
    }, []);

    // Keep the marker in sync with the chosen location (click, geolocation or typed).
    useEffect(() => {
        const map = mapRef.current;
        if (!map) return;
        if (latitude === null || longitude === null) {
            markerRef.current?.remove();
            markerRef.current = null;
            return;
        }
        if (!markerRef.current) {
            markerRef.current = new maplibregl.Marker({ color: "#1b3a8c" }).setLngLat([longitude, latitude]).addTo(map);
        } else {
            markerRef.current.setLngLat([longitude, latitude]);
        }
    }, [latitude, longitude]);

    function useMyLocation() {
        setGeoError("");
        if (!navigator.geolocation) {
            setGeoError("Your browser does not support location.");
            return;
        }
        setLocating(true);
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                setLocating(false);
                const { latitude: lat, longitude: lng } = pos.coords;
                if (!isInIndia(lat, lng)) {
                    handlersRef.current.onOutsideIndia();
                    return;
                }
                mapRef.current?.flyTo({ center: [lng, lat], zoom: 15 });
                handlersRef.current.onPick(lat, lng);
            },
            () => {
                setLocating(false);
                setGeoError("We could not get your location. Allow location access or tap the map instead.");
            },
            { enableHighAccuracy: true, timeout: 10000 },
        );
    }

    return (
        <div className={styles.wrapper}>
            <div ref={containerRef} className={styles.map} />
            <div className={styles.overlay}>
                <Button variant="secondary" size="sm" onClick={useMyLocation} loading={locating}>
                    Use my location
                </Button>
                {geoError && (
                    <p className={styles.geoError} role="alert">
                        {geoError}
                    </p>
                )}
            </div>
        </div>
    );
}

export default LocationPicker;
