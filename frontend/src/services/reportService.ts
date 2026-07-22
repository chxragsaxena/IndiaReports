import axios from "axios";
import type { Report } from "../types/report";
import { API_URL } from "../config/api";

const api = axios.create({
    baseURL: `${API_URL}/api/v1`,
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
    const response = await api.post("/reports/", report);
    return response.data;
}