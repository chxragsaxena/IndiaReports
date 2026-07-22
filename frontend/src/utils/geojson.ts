import type { Feature, FeatureCollection, Point } from "geojson";
import type { Report } from "../types/report";

export function reportsToGeoJSON(
    reports: Report[]
): FeatureCollection<Point> {
    return {
        type: "FeatureCollection",
        features: reports.map((report): Feature<Point> => ({
            type: "Feature",
            geometry: {
                type: "Point",
                coordinates: [
                    report.longitude,
                    report.latitude,
                ],
            },
            properties: {
                id: report.id,
                title: report.title,
                description: report.description,
                city: report.city,
                category: report.category,
                status: report.status,
                landmark: report.landmark,
            },
        })),
    };
}