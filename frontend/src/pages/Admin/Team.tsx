import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";

import Button from "../../components/UI/Button/Button";
import { SelectField, TextArea, TextField } from "../../components/UI/Input/Input";
import Skeleton from "../../components/UI/Skeleton/Skeleton";
import { useToast } from "../../components/UI/Toast/Toast";
import Modal from "../../components/UI/Modal/Modal";
import {
    createArea,
    createOfficer,
    deactivateOfficer,
    listAreas,
    listOfficers,
    reactivateOfficer,
    sendOfficerReset,
    setOfficerAccount,
} from "../../services/adminService";
import type { Area, Officer } from "../../services/adminService";
import { apiErrorMessage } from "../../services/reportService";
import styles from "./Team.module.css";

/** Accepts a bare geometry, a Feature, or the FeatureCollection that drawing tools export. */
function extractGeometry(text: string): { geometry?: unknown; error?: string } {
    let value: unknown;
    try {
        value = JSON.parse(text);
    } catch {
        return { error: "That is not valid JSON. Paste the GeoJSON exactly as exported." };
    }
    const obj = value as { type?: string; features?: unknown[]; geometry?: unknown };
    let geometry: { type?: string } | undefined;
    if (obj?.type === "FeatureCollection") {
        if (!Array.isArray(obj.features) || obj.features.length !== 1) {
            return { error: "Paste exactly one shape. This has " + (Array.isArray(obj.features) ? obj.features.length : 0) + "." };
        }
        geometry = (obj.features[0] as { geometry?: { type?: string } }).geometry;
    } else if (obj?.type === "Feature") {
        geometry = obj.geometry as { type?: string };
    } else {
        geometry = obj as { type?: string };
    }
    if (geometry?.type !== "Polygon" && geometry?.type !== "MultiPolygon") {
        return { error: "The shape must be a Polygon or MultiPolygon." };
    }
    return { geometry };
}

function Team() {
    const toast = useToast();
    const [officers, setOfficers] = useState<Officer[]>([]);
    const [areas, setAreas] = useState<Area[]>([]);
    const [loading, setLoading] = useState(true);

    const fail = useCallback((err: unknown) => toast.show(apiErrorMessage(err), "error"), [toast]);

    const load = useCallback(async () => {
        try {
            const [o, a] = await Promise.all([listOfficers(), listAreas()]);
            setOfficers(o);
            setAreas(a);
        } catch (err) {
            fail(err);
        } finally {
            setLoading(false);
        }
    }, [fail]);

    useEffect(() => {
        void load();
    }, [load]);

    // ---- add officer
    const [name, setName] = useState("");
    const [areaId, setAreaId] = useState("");
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [chat, setChat] = useState("");
    const [savingOfficer, setSavingOfficer] = useState(false);

    async function addOfficer(e: FormEvent) {
        e.preventDefault();
        setSavingOfficer(true);
        try {
            await createOfficer({ name: name.trim(), area_id: areaId, email: email.trim(), password, telegram_chat_id: chat.trim() });
            toast.show(`${name.trim()} can now sign in and will receive reports for their area`, "success");
            setName("");
            setEmail("");
            setPassword("");
            setChat("");
            await load();
        } catch (err) {
            fail(err);
        } finally {
            setSavingOfficer(false);
        }
    }

    // ---- add area
    const [areaName, setAreaName] = useState("");
    const [shape, setShape] = useState("");
    const [shapeError, setShapeError] = useState("");
    const [savingArea, setSavingArea] = useState(false);

    async function addArea(e: FormEvent) {
        e.preventDefault();
        const parsed = extractGeometry(shape);
        if (parsed.error) {
            setShapeError(parsed.error);
            return;
        }
        setShapeError("");
        setSavingArea(true);
        try {
            await createArea(areaName.trim(), parsed.geometry);
            toast.show(`${areaName.trim()} added`, "success");
            setAreaName("");
            setShape("");
            await load();
        } catch (err) {
            fail(err);
        } finally {
            setSavingArea(false);
        }
    }

    // ---- give an existing officer a sign-in
    const [giving, setGiving] = useState<Officer | null>(null);
    const [giveEmail, setGiveEmail] = useState("");
    const [givePassword, setGivePassword] = useState("");
    const [savingAccount, setSavingAccount] = useState(false);

    async function saveAccount(e: FormEvent) {
        e.preventDefault();
        if (!giving) return;
        setSavingAccount(true);
        try {
            await setOfficerAccount(giving.id, giveEmail.trim(), givePassword);
            toast.show(`${giving.name} can now sign in`, "success");
            setGiving(null);
            setGiveEmail("");
            setGivePassword("");
            await load();
        } catch (err) {
            fail(err);
        } finally {
            setSavingAccount(false);
        }
    }

    // ---- deactivate, reactivate, send a password reset link
    const [working, setWorking] = useState<string | null>(null);

    async function act(officer: Officer, what: "deactivate" | "reactivate" | "reset") {
        if (
            what === "deactivate" &&
            !window.confirm(
                `Deactivate ${officer.name}? They can no longer sign in, and their open reports move to you. You can reactivate them later.`,
            )
        ) {
            return;
        }
        setWorking(officer.id);
        try {
            if (what === "deactivate") {
                const done = await deactivateOfficer(officer.id);
                toast.show(`${officer.name} is deactivated. ${done.reassigned} open report${done.reassigned === 1 ? "" : "s"} moved to you.`, "success");
            } else if (what === "reactivate") {
                await reactivateOfficer(officer.id);
                toast.show(`${officer.name} can sign in again and will get new reports for their area.`, "success");
            } else {
                const sent = await sendOfficerReset(officer.id);
                toast.show(`A password reset link was emailed to ${sent.sent_to}.`, "success");
            }
            await load();
        } catch (err) {
            fail(err);
        } finally {
            setWorking(null);
        }
    }

    const staff = officers.filter((o) => o.role === "officer");

    return (
        <div className={styles.page}>
            <header className={styles.header}>
                <div>
                    <h1>Team and areas</h1>
                    <p className={styles.sub}>
                        Each area has one officer. A report goes to the officer of the smallest area it falls in, and to you if
                        it falls in none.
                    </p>
                </div>
                <Link to="/admin">Back to reports</Link>
            </header>

            <section className={styles.card}>
                <h2>Area officers</h2>
                {loading ? (
                    <Skeleton height={80} />
                ) : staff.length === 0 ? (
                    <p className={styles.muted}>No officers yet. Add an area below, then an officer for it.</p>
                ) : (
                    <div className={styles.tableWrap}>
                        <table className={styles.table}>
                            <thead>
                                <tr>
                                    <th scope="col">Officer</th>
                                    <th scope="col">Area</th>
                                    <th scope="col">Signs in with</th>
                                    <th scope="col">Access</th>
                                </tr>
                            </thead>
                            <tbody>
                                {staff.map((o) => (
                                    <tr key={o.id} className={o.active ? undefined : styles.inactive}>
                                        <th scope="row">{o.name}</th>
                                        <td>{o.area_name ?? <span className={styles.muted}>No area</span>}</td>
                                        <td>
                                            {o.email ?? (
                                                <>
                                                    <span className={styles.muted}>No sign-in </span>
                                                    <button className={styles.linkBtn} onClick={() => setGiving(o)}>
                                                        Add one
                                                    </button>
                                                </>
                                            )}
                                        </td>
                                        <td>
                                            <span className={styles.actions}>
                                                {o.active ? (
                                                    <>
                                                        {o.email && (
                                                            <button className={styles.linkBtn} disabled={working === o.id} onClick={() => void act(o, "reset")}>
                                                                Send reset link
                                                            </button>
                                                        )}
                                                        <button className={styles.linkBtn} disabled={working === o.id} onClick={() => void act(o, "deactivate")}>
                                                            Deactivate
                                                        </button>
                                                    </>
                                                ) : (
                                                    <>
                                                        <span className={styles.muted}>Deactivated</span>
                                                        <button className={styles.linkBtn} disabled={working === o.id} onClick={() => void act(o, "reactivate")}>
                                                            Reactivate
                                                        </button>
                                                    </>
                                                )}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>

            <div className={styles.grid}>
                <form className={styles.card} onSubmit={addOfficer}>
                    <h2>Add an officer</h2>
                    <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} minLength={2} required />
                    <SelectField label="Area" value={areaId} onChange={(e) => setAreaId(e.target.value)} required>
                        <option value="">{areas.length ? "Choose an area" : "Add an area first"}</option>
                        {areas.map((a) => (
                            <option key={a.id} value={a.id}>
                                {a.name}
                            </option>
                        ))}
                    </SelectField>
                    <TextField
                        label="Email"
                        type="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        autoComplete="off"
                        required
                        hint="They sign in with this and get an email for each new report in their area."
                    />
                    <TextField
                        label="Password for a new account"
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        autoComplete="new-password"
                        minLength={8}
                        hint="Leave empty if this email already has an account; it is upgraded to an officer."
                    />
                    <TextField
                        label="Telegram chat id (optional)"
                        value={chat}
                        onChange={(e) => setChat(e.target.value)}
                        hint="For instant Telegram alerts, if the alert service is running."
                    />
                    <Button type="submit" loading={savingOfficer} disabled={!areas.length}>
                        Add officer
                    </Button>
                </form>

                <form className={styles.card} onSubmit={addArea}>
                    <h2>Add an area</h2>
                    <TextField
                        label="Name"
                        value={areaName}
                        onChange={(e) => setAreaName(e.target.value)}
                        minLength={2}
                        required
                        placeholder="For example: Andheri West ward"
                    />
                    <TextArea
                        label="Boundary (GeoJSON)"
                        value={shape}
                        onChange={(e) => setShape(e.target.value)}
                        rows={7}
                        required
                        error={shapeError || undefined}
                        hint="Draw the boundary at geojson.io, then paste what it shows on the right."
                        spellCheck={false}
                    />
                    <Button type="submit" loading={savingArea}>
                        Add area
                    </Button>
                    {areas.length > 0 && (
                        <p className={styles.muted}>
                            {areas.length} area{areas.length === 1 ? "" : "s"}: {areas.map((a) => a.name).join(", ")}
                        </p>
                    )}
                </form>
            </div>

            {giving && (
                <Modal title={`Sign-in for ${giving.name}`} onClose={() => setGiving(null)}>
                    <form className={styles.modalForm} onSubmit={saveAccount}>
                        <TextField
                            label="Email"
                            type="email"
                            value={giveEmail}
                            onChange={(e) => setGiveEmail(e.target.value)}
                            autoComplete="off"
                            required
                        />
                        <TextField
                            label="Password for a new account"
                            type="password"
                            value={givePassword}
                            onChange={(e) => setGivePassword(e.target.value)}
                            autoComplete="new-password"
                            minLength={8}
                            hint="Leave empty if this email already has an account."
                        />
                        <div className={styles.modalActions}>
                            <Button type="button" variant="secondary" onClick={() => setGiving(null)}>
                                Cancel
                            </Button>
                            <Button type="submit" loading={savingAccount}>
                                Save
                            </Button>
                        </div>
                    </form>
                </Modal>
            )}

            <section className={styles.card}>
                <h2>Escalation</h2>
                <p className={styles.muted}>
                    An officer has 7 days to resolve a report. After that it is escalated to you. Escalation to higher agencies
                    (city, district, state) is described in the architecture notes but not built.
                </p>
            </section>
        </div>
    );
}

export default Team;
