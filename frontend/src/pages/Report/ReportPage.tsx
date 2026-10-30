import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";

import Button from "../../components/UI/Button/Button";
import { SelectField, TextArea, TextField } from "../../components/UI/Input/Input";
import { useToast } from "../../components/UI/Toast/Toast";
import { PhotosUnavailableError, apiErrorMessage, createReport, uploadReportPhoto } from "../../services/reportService";
import { MAX_PHOTOS, compressPhoto, photoProblem } from "../../utils/image";
import { CATEGORIES } from "../../types/report";
import type { Report } from "../../types/report";
import { reverseGeocode } from "../../utils/geocode";
import LocationPicker from "./LocationPicker";
import SimilarNearby from "../../components/MeToo/SimilarNearby";
import styles from "./ReportPage.module.css";

interface FormState {
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

type Errors = Partial<Record<keyof FormState, string>>;

const EMPTY: FormState = {
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
};

// Address fields that reverse geocoding may fill in (unless the person typed them).
const PLACE_FIELDS = ["address", "city", "district", "state", "pincode"] as const;

function validate(f: FormState): Errors {
    const e: Errors = {};
    if (f.title.trim().length < 3) e.title = "Give the issue a short title (at least 3 characters).";
    if (f.description.trim().length < 10) e.description = "Describe the problem in a sentence or two (at least 10 characters).";
    if (!f.category) e.category = "Choose the category that fits best.";
    if (f.latitude === null || f.longitude === null) e.latitude = "Tap the map to mark where the problem is.";
    if (!f.city.trim()) e.city = "Enter the city or town.";
    if (!f.state.trim()) e.state = "Enter the state.";
    if (f.pincode && !/^\d{6}$/.test(f.pincode.trim())) e.pincode = "A pincode has 6 digits.";
    return e;
}

function ReportPage() {
    const toast = useToast();
    const [form, setForm] = useState<FormState>(EMPTY);
    const [errors, setErrors] = useState<Errors>({});
    const [submitting, setSubmitting] = useState(false);
    const [submitted, setSubmitted] = useState<Report | null>(null);
    const [lookingUp, setLookingUp] = useState(false);
    const [photos, setPhotos] = useState<File[]>([]);
    const [uploadNote, setUploadNote] = useState("");
    const [photoCount, setPhotoCount] = useState(0);
    const [matchKey, setMatchKey] = useState("");
    const [confirmedNew, setConfirmedNew] = useState(false);
    const onMatches = useCallback((key: string) => {
        setMatchKey(key);
        setConfirmedNew(false); // a different set of matches needs a fresh look
    }, []);

    // Fields the person edited by hand: geocoding must not overwrite them.
    const touched = useRef(new Set<string>());
    const geocodeRequest = useRef<AbortController | null>(null);

    useEffect(() => () => geocodeRequest.current?.abort(), []);

    // Object URLs for the thumbnails; released when the photos change or the page closes.
    const previews = useMemo(() => photos.map((p) => URL.createObjectURL(p)), [photos]);
    useEffect(() => () => previews.forEach((u) => URL.revokeObjectURL(u)), [previews]);

    function addPhotos(list: FileList | null) {
        if (!list) return;
        const next = [...photos];
        for (const file of Array.from(list)) {
            const problem = photoProblem(file);
            if (problem) {
                toast.show(problem, "error");
                continue;
            }
            if (next.length >= MAX_PHOTOS) {
                toast.show(`You can attach up to ${MAX_PHOTOS} photos.`, "info");
                break;
            }
            next.push(file);
        }
        setPhotos(next);
    }

    function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
        touched.current.add(key);
        setForm((prev) => ({ ...prev, [key]: value }));
        setErrors((prev) => ({ ...prev, [key]: undefined }));
    }

    const onPick = useCallback(async (lat: number, lng: number) => {
        setForm((prev) => ({ ...prev, latitude: lat, longitude: lng }));
        setErrors((prev) => ({ ...prev, latitude: undefined }));

        geocodeRequest.current?.abort();
        const controller = new AbortController();
        geocodeRequest.current = controller;
        setLookingUp(true);
        const place = await reverseGeocode(lat, lng, controller.signal);
        if (controller.signal.aborted) return;
        setLookingUp(false);
        if (!place) return;

        setForm((prev) => {
            const next = { ...prev };
            for (const field of PLACE_FIELDS) {
                if (!touched.current.has(field) && place[field]) next[field] = place[field];
            }
            return next;
        });
    }, []);

    const onOutsideIndia = useCallback(() => {
        toast.show("Reports can only be filed for locations in India.", "error");
    }, [toast]);

    async function submit(e: FormEvent) {
        e.preventDefault();
        const found = validate(form);
        setErrors(found);
        if (Object.keys(found).length > 0) {
            toast.show("Please fix the highlighted fields.", "error");
            return;
        }

        if (matchKey !== "" && !confirmedNew) {
            toast.show("Please check the report(s) that may already exist, then press Me too or confirm yours is different.", "error");
            return;
        }

        setSubmitting(true);
        try {
            const report = await createReport({
                title: form.title.trim(),
                description: form.description.trim(),
                category: form.category,
                latitude: form.latitude!,
                longitude: form.longitude!,
                address: form.address.trim(),
                landmark: form.landmark.trim(),
                city: form.city.trim(),
                district: form.district.trim(),
                state: form.state.trim(),
                pincode: form.pincode.trim(),
            });
            // The report is filed. Attach photos one at a time; a failure here must not undo it.
            let attached = 0;
            let failed = 0;
            for (let i = 0; i < photos.length; i++) {
                setUploadNote(`Uploading photo ${i + 1} of ${photos.length}...`);
                try {
                    await uploadReportPhoto(report.id, await compressPhoto(photos[i]));
                    attached += 1;
                } catch (err) {
                    if (err instanceof PhotosUnavailableError) {
                        toast.show("Photos cannot be uploaded right now, but your report was submitted.", "info");
                        failed += photos.length - i;
                        break;
                    }
                    failed += 1;
                }
            }
            if (failed > 0 && attached > 0) toast.show(`${failed} photo${failed === 1 ? "" : "s"} could not be uploaded.`, "error");
            setPhotoCount(attached);
            setSubmitted(report);
        } catch (err) {
            toast.show(apiErrorMessage(err, "We could not submit your report. Please try again."), "error");
        } finally {
            setSubmitting(false);
        }
    }

    if (submitted) {
        return (
            <div className={styles.doneWrap}>
                <div className={styles.done}>
                    <div className={styles.check} aria-hidden="true">
                        &#10003;
                    </div>
                    <h1>Thank you, your report is in</h1>
                    <p>
                        {submitted.assigned_at
                            ? `It has been sent to the officer responsible for this area${photoCount > 0 ? `, with ${photoCount} photo${photoCount === 1 ? "" : "s"}` : ""}. If nobody acknowledges it, it is escalated to the administrator automatically.`
                            : "It is now on the map for everyone to see."}
                    </p>
                    <div className={styles.doneActions}>
                        <Link
                            className={styles.primaryLink}
                            to={`/?report=${submitted.id}&lat=${submitted.latitude}&lng=${submitted.longitude}&z=14`}
                        >
                            See it on the map
                        </Link>
                        <Button
                            variant="secondary"
                            onClick={() => {
                                touched.current.clear();
                                setPhotos([]);
                                setUploadNote("");
                                setForm(EMPTY);
                                setSubmitted(null);
                            }}
                        >
                            Report another issue
                        </Button>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className={styles.page}>
            <form className={styles.form} onSubmit={submit} noValidate>
                <header>
                    <h1>Report an issue</h1>
                    <p className={styles.subtitle}>
                        Tell us what is wrong and where. The report goes to the officer responsible for that area.
                    </p>
                </header>

                <fieldset className={styles.section}>
                    <legend>What is the problem?</legend>
                    <TextField
                        label="Title"
                        value={form.title}
                        onChange={(e) => setField("title", e.target.value)}
                        error={errors.title}
                        maxLength={255}
                        placeholder="For example: Large pothole near the bus stop"
                    />
                    <SelectField
                        label="Category"
                        value={form.category}
                        onChange={(e) => setField("category", e.target.value)}
                        error={errors.category}
                    >
                        <option value="">Select a category</option>
                        {CATEGORIES.map((c) => (
                            <option key={c} value={c}>
                                {c}
                            </option>
                        ))}
                    </SelectField>
                    <TextArea
                        label="Details"
                        value={form.description}
                        onChange={(e) => setField("description", e.target.value)}
                        error={errors.description}
                        maxLength={5000}
                        placeholder="What happened, how long it has been like this, and who it affects."
                    />
                </fieldset>

                <SimilarNearby
                    latitude={form.latitude}
                    longitude={form.longitude}
                    category={form.category}
                    title={form.title}
                    description={form.description}
                    onMatches={onMatches}
                    confirmed={confirmedNew}
                    onConfirm={setConfirmedNew}
                />

                <fieldset className={styles.section}>
                    <legend>Where is it?</legend>
                    <div
                        className={`${styles.locationStatus} ${errors.latitude ? styles.locationError : ""}`}
                        role={errors.latitude ? "alert" : "status"}
                    >
                        {errors.latitude
                            ? errors.latitude
                            : form.latitude !== null && form.longitude !== null
                              ? lookingUp
                                  ? "Location marked. Looking up the address..."
                                  : `Location marked (${form.latitude.toFixed(4)}, ${form.longitude.toFixed(4)})`
                              : "Tap the map to mark the exact spot, or use your current location."}
                    </div>
                    <TextField
                        label="Street or area"
                        value={form.address}
                        onChange={(e) => setField("address", e.target.value)}
                        maxLength={500}
                    />
                    <TextField
                        label="Landmark (optional)"
                        value={form.landmark}
                        onChange={(e) => setField("landmark", e.target.value)}
                        maxLength={255}
                        placeholder="Near the temple, opposite the school..."
                    />
                    <div className={styles.row}>
                        <TextField
                            label="City or town"
                            value={form.city}
                            onChange={(e) => setField("city", e.target.value)}
                            error={errors.city}
                            maxLength={100}
                        />
                        <TextField
                            label="District"
                            value={form.district}
                            onChange={(e) => setField("district", e.target.value)}
                            maxLength={100}
                        />
                    </div>
                    <div className={styles.row}>
                        <TextField
                            label="State"
                            value={form.state}
                            onChange={(e) => setField("state", e.target.value)}
                            error={errors.state}
                            maxLength={100}
                        />
                        <TextField
                            label="Pincode"
                            inputMode="numeric"
                            value={form.pincode}
                            onChange={(e) => setField("pincode", e.target.value)}
                            error={errors.pincode}
                            maxLength={10}
                        />
                    </div>
                </fieldset>

                <fieldset className={styles.section}>
                    <legend>Photos (optional)</legend>
                    <p className={styles.photoHelp}>
                        A clear photo helps the right person act faster. Up to {MAX_PHOTOS} photos. They are shown to administrators only, and the
                        location stored in the photo is removed.
                    </p>
                    <div className={styles.photoGrid}>
                        {previews.map((src, i) => (
                            <div key={src} className={styles.thumb}>
                                <img src={src} alt={`Attached photo ${i + 1}`} />
                                <button
                                    type="button"
                                    className={styles.removePhoto}
                                    aria-label={`Remove photo ${i + 1}`}
                                    onClick={() => setPhotos(photos.filter((_, n) => n !== i))}
                                >
                                    &times;
                                </button>
                            </div>
                        ))}
                        {photos.length < MAX_PHOTOS && (
                            <label className={styles.addPhoto}>
                                <input
                                    type="file"
                                    accept="image/jpeg,image/png,image/webp"
                                    multiple
                                    onChange={(e) => {
                                        addPhotos(e.target.files);
                                        e.target.value = ""; // allow picking the same file again
                                    }}
                                />
                                <span aria-hidden="true">+</span>
                                <span>Add photo</span>
                            </label>
                        )}
                    </div>
                </fieldset>

                <div className={styles.submitRow}>
                    <Button type="submit" loading={submitting}>
                        {submitting && uploadNote ? uploadNote : "Submit report"}
                    </Button>
                    <Link to="/" className={styles.cancel}>
                        Cancel
                    </Link>
                </div>
            </form>

            <div className={styles.mapColumn}>
                <LocationPicker
                    latitude={form.latitude}
                    longitude={form.longitude}
                    onPick={onPick}
                    onOutsideIndia={onOutsideIndia}
                />
            </div>
        </div>
    );
}

export default ReportPage;
