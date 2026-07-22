import type { Dispatch, SetStateAction } from "react";
import { useNavigate } from "react-router-dom";

import Button from "../../components/UI/Button/Button";
import Input from "../../components/UI/Input/Input";

import { createReport } from "../../services/reportService";

import type { ReportFormData } from "./ReportPage";

import styles from "./ReportForm.module.css";

interface ReportFormProps {
    formData: ReportFormData;
    setFormData: Dispatch<SetStateAction<ReportFormData>>;
}

function ReportForm({
    formData,
    setFormData,
}: ReportFormProps) {
    const navigate = useNavigate();

    function handleChange(
        e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
    ) {
        const { name, value } = e.target;

        setFormData((prev) => ({
            ...prev,
            [name]: value,
        }));
    }

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();

        if (
            formData.latitude === null ||
            formData.longitude === null
        ) {
            alert("Please select a location on the map.");
            return;
        }

        try {
            await createReport({
                title: formData.title,
                description: formData.description,
                category: formData.category,
                latitude: formData.latitude,
                longitude: formData.longitude,
                address: formData.address,
                landmark: formData.landmark,
                city: formData.city,
                district: formData.district,
                state: formData.state,
                pincode: formData.pincode,
            });

            alert("Report submitted successfully!");

            navigate("/");
        } catch (error) {
            console.error(error);
            alert("Failed to submit report.");
        }
    }

    return (
        <form
            className={styles.form}
            onSubmit={handleSubmit}
        >
            <h2>Report Issue</h2>

            <p className={styles.subtitle}>
                Help improve your city by reporting civic issues.
            </p>

            <Input
                name="title"
                placeholder="Title"
                value={formData.title}
                onChange={handleChange}
            />

            <textarea
                className={styles.textarea}
                name="description"
                placeholder="Describe the issue..."
                value={formData.description}
                onChange={handleChange}
            />

            <select
                name="category"
                value={formData.category}
                onChange={(e) =>
                    setFormData((prev) => ({
                        ...prev,
                        category: e.target.value,
                    }))
                }
                className={styles.textarea}
            >
                <option value="">Select Category</option>
                <option value="Road">Road</option>
                <option value="Water Supply">Water Supply</option>
                <option value="Electricity">Electricity</option>
                <option value="Garbage">Garbage</option>
                <option value="Drainage">Drainage</option>
                <option value="Street Light">Street Light</option>
                <option value="Traffic">Traffic</option>
                <option value="Public Transport">Public Transport</option>
                <option value="Crime">Crime</option>
                <option value="Medical">Medical</option>
                <option value="Fire">Fire</option>
                <option value="Other">Other</option>
            </select>

            <Input
                name="address"
                placeholder="Address"
                value={formData.address}
                onChange={handleChange}
            />

            <Input
                name="landmark"
                placeholder="Landmark"
                value={formData.landmark}
                onChange={handleChange}
            />

            <div className={styles.row}>
                <Input
                    name="city"
                    placeholder="City"
                    value={formData.city}
                    onChange={handleChange}
                />

                <Input
                    name="district"
                    placeholder="District"
                    value={formData.district}
                    onChange={handleChange}
                />
            </div>

            <div className={styles.row}>
                <Input
                    name="state"
                    placeholder="State"
                    value={formData.state}
                    onChange={handleChange}
                />

                <Input
                    name="pincode"
                    placeholder="Pincode"
                    value={formData.pincode}
                    onChange={handleChange}
                />
            </div>

            <div className={styles.locationBox}>
                {formData.latitude && formData.longitude ? (
                    <p>📍 Location Selected Successfully</p>
                ) : (
                    <p>📍 Click anywhere on the map to select a location</p>
                )}
            </div>

            <div className={styles.submitButton}>
                <Button type="submit">
                    Submit Report
                </Button>
            </div>
        </form>
    );
}

export default ReportForm;