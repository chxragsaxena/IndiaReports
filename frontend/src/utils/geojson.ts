import type { Feature, FeatureCollection, Point } from "geojson";
import type { Report } from "../types/report";

/** Only what the map layers need. Anything else is fetched on demand by id. */
export interface PinProps {
    id: string;
    title: string;
    category: string;
    status: string;
    city: string;
}

export type PinFeature = Feature<Point, PinProps>;

export function reportToFeature(report: Pick<Report, "id" | "title" | "category" | "status" | "city" | "latitude" | "longitude">): PinFeature {
    return {
        type: "Feature",
        geometry: { type: "Point", coordinates: [report.longitude, report.latitude] },
        properties: {
            id: report.id,
            title: report.title,
            category: report.category,
            status: report.status,
            city: report.city,
        },
    };
}

export function toCollection(features: PinFeature[]): FeatureCollection<Point, PinProps> {
    return { type: "FeatureCollection", features };
}

export const EMPTY_COLLECTION: FeatureCollection<Point, PinProps> = toCollection([]);
