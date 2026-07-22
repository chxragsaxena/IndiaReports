import { useState } from "react";
import styles from "./ReportPage.module.css";
import ReportForm from "./ReportForm";
import LocationPicker from "./LocationPicker";

export interface ReportFormData {
    title: string;
    description: string;
    category: string;
    address: string;
    landmark: string;
    city: string;
    district: string;
    state: string;
    pincode: string;
    latitude: number | null;
    longitude: number | null;
}

function ReportPage() {
    const [formData, setFormData] = useState<ReportFormData>({
        title: "",
        description: "",
        category: "",
        address: "",
        landmark: "",
        city: "",
        district: "",
        state: "",
        pincode: "",
        latitude: null,
        longitude: null,
    });

    return (
        <div className={styles.container}>
            <div className={styles.left}>
                <ReportForm
                    formData={formData}
                    setFormData={setFormData}
                />
            </div>

            <div className={styles.right}>
                <LocationPicker
                    formData={formData}
                    setFormData={setFormData}
                />
            </div>
        </div>
    );
}

export default ReportPage;