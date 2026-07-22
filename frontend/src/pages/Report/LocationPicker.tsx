import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import type { Dispatch, SetStateAction } from "react";
import type { ReportFormData } from "./ReportPage";

import styles from "./LocationPicker.module.css";

interface LocationPickerProps {
    formData: ReportFormData;
    setFormData: Dispatch<SetStateAction<ReportFormData>>;
}

function LocationPicker({
    setFormData,
}: LocationPickerProps) {

    const mapContainer = useRef<HTMLDivElement | null>(null);
    const mapRef = useRef<maplibregl.Map | null>(null);
    const markerRef = useRef<maplibregl.Marker | null>(null);

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

        map.on("click", (e) => {

            const { lng, lat } = e.lngLat;

            if (markerRef.current) {
                markerRef.current.remove();
            }

            markerRef.current = new maplibregl.Marker({
                color: "#ef4444",
            })
                .setLngLat([lng, lat])
                .addTo(map);

            setFormData((prev) => ({
                ...prev,
                latitude: lat,
                longitude: lng,
            }));

        });

        mapRef.current = map;

        return () => {
            map.remove();
            mapRef.current = null;
        };

    }, [setFormData]);

    return (
        <div
            ref={mapContainer}
            className={styles.map}
        />
    );
}

export default LocationPicker;