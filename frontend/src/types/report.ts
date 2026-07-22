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

    status: string;
}