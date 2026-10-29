export type ReportStatus = "OPEN" | "IN_PROGRESS" | "RESOLVED";

export const CATEGORIES = [
    "Road",
    "Water Supply",
    "Electricity",
    "Garbage",
    "Drainage",
    "Street Light",
    "Traffic",
    "Public Transport",
    "Crime",
    "Medical",
    "Fire",
    "Other",
] as const;

export const STATUS_LABEL: Record<ReportStatus, string> = {
    OPEN: "Open",
    IN_PROGRESS: "In progress",
    RESOLVED: "Resolved",
};

export interface Report {
    id: string;

    title: string;
    description: string;

    category: string;

    latitude: number;
    longitude: number;

    address: string;
    landmark: string;

    city: string;
    district: string;
    state: string;

    pincode: string;

    status: ReportStatus;

    created_at?: string | null;
    updated_at?: string | null;
    assigned_at?: string | null;
    acknowledged_at?: string | null;
    escalated_at?: string | null;
}

export interface NewReport {
    title: string;
    description: string;
    category: string;
    latitude: number;
    longitude: number;
    address: string;
    landmark: string;
    city: string;
    district: string;
    state: string;
    pincode: string;
}

/** India's bounding box; the API rejects coordinates outside it. */
export const INDIA_BOUNDS = { minLat: 6, maxLat: 38, minLng: 68, maxLng: 98 } as const;

export function isInIndia(lat: number, lng: number): boolean {
    return (
        lat >= INDIA_BOUNDS.minLat &&
        lat <= INDIA_BOUNDS.maxLat &&
        lng >= INDIA_BOUNDS.minLng &&
        lng <= INDIA_BOUNDS.maxLng
    );
}
