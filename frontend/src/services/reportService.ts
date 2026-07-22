import axios from "axios";
import type { Report } from "../types/report";

const api = axios.create({
    baseURL: "http://127.0.0.1:8000/api/v1",
});

export async function getReports(): Promise<Report[]> {
    const response = await api.get("/reports/");
    return response.data;
}

export async function createReport(report: {
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
}) {
    const response = await fetch("http://127.0.0.1:8000/api/v1/reports/", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(report),
    });

    if (!response.ok) {
        throw new Error("Failed to create report");
    }

    return response.json();
}