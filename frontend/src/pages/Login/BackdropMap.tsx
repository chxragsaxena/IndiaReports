import { useEffect, useRef } from "react";

import { MAP_STYLE } from "../../config/api";
import styles from "./Login.module.css";

/** A still, non-interactive map of India behind the sign-in card. Purely decorative. */
function BackdropMap() {
    const containerRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;
        let cancelled = false;
        let map: { remove: () => void } | null = null;

        // The map library is large; load it only for this page, after the form is already usable.
        (async () => {
            try {
                const [{ default: maplibregl }] = await Promise.all([
                    import("maplibre-gl"),
                    import("maplibre-gl/dist/maplibre-gl.css"),
                ]);
                if (cancelled) return;
                map = new maplibregl.Map({
                    container,
                    style: MAP_STYLE,
                    center: [79.5, 22],
                    zoom: window.innerWidth < 700 ? 3.1 : 3.9,
                    interactive: false,
                    attributionControl: { compact: true },
                    fadeDuration: 0,
                });
            } catch {
                // No WebGL or the tiles are unreachable: the gradient behind it is the fallback.
            }
        })();

        return () => {
            cancelled = true;
            map?.remove();
        };
    }, []);

    // The wrapper is the positioned layer; MapLibre restyles its own container, so keep them separate.
    return (
        <div className={styles.map} aria-hidden="true">
            <div ref={containerRef} className={styles.mapInner} />
        </div>
    );
}

export default BackdropMap;
