import type { Feature, FeatureCollection, Point } from "geojson";
import type { Pin } from "../types/report";

/** The map layers colour by status and highlight by id; nothing else is needed. */
export interface PinProps {
    id: string;
    status: string;
}

export type PinFeature = Feature<Point, PinProps>;

export function reportToFeature(pin: Pin): PinFeature {
    return {
        type: "Feature",
        geometry: { type: "Point", coordinates: [pin.longitude, pin.latitude] },
        properties: { id: pin.id, status: pin.status },
    };
}

export function toCollection(features: PinFeature[]): FeatureCollection<Point, PinProps> {
    return { type: "FeatureCollection", features };
}

export const EMPTY_COLLECTION: FeatureCollection<Point, PinProps> = toCollection([]);
