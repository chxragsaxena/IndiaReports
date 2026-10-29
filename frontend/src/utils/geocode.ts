import { isInIndia } from "../types/report";

export interface PlaceDetails {
    address: string;
    city: string;
    district: string;
    state: string;
    pincode: string;
}

interface NominatimAddress {
    road?: string;
    neighbourhood?: string;
    suburb?: string;
    city?: string;
    town?: string;
    village?: string;
    county?: string;
    state_district?: string;
    state?: string;
    postcode?: string;
}

/**
 * Best-effort reverse geocoding so people do not have to type their address.
 * Uses OpenStreetMap's public Nominatim, which is rate limited and meant for light
 * use; for production traffic point this at a self-hosted or paid geocoder.
 * Any failure returns null and the form simply stays manual.
 */
export async function reverseGeocode(lat: number, lng: number, signal?: AbortSignal): Promise<PlaceDetails | null> {
    if (!isInIndia(lat, lng)) return null;
    try {
        const url =
            `https://nominatim.openstreetmap.org/reverse?format=jsonv2&addressdetails=1` +
            `&accept-language=en&zoom=18&lat=${lat}&lon=${lng}`;
        const res = await fetch(url, { signal });
        if (!res.ok) return null;
        const data = (await res.json()) as { address?: NominatimAddress };
        const a = data.address;
        if (!a) return null;
        return {
            address: [a.road, a.neighbourhood ?? a.suburb].filter(Boolean).join(", "),
            city: a.city ?? a.town ?? a.village ?? a.county ?? "",
            district: a.state_district ?? a.county ?? "",
            state: a.state ?? "",
            pincode: (a.postcode ?? "").replace(/\s+/g, ""),
        };
    } catch {
        return null;
    }
}
