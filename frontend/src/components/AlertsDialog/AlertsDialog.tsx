import { useState } from "react";
import type { FormEvent } from "react";

import Modal from "../UI/Modal/Modal";
import Button from "../UI/Button/Button";
import { SelectField, TextField } from "../UI/Input/Input";
import { useToast } from "../UI/Toast/Toast";
import { subscribe } from "../../services/notifierService";
import type { SubscriptionKind } from "../../services/notifierService";
import { apiErrorMessage } from "../../services/reportService";
import { CATEGORIES } from "../../types/report";
import styles from "./AlertsDialog.module.css";

const BOT_NAME = import.meta.env.VITE_TELEGRAM_BOT as string | undefined;

function AlertsDialog({ onClose }: { onClose: () => void }) {
    const toast = useToast();
    const [chatId, setChatId] = useState("");
    const [kind, setKind] = useState<SubscriptionKind>("pincode");
    const [pincode, setPincode] = useState("");
    const [city, setCity] = useState("");
    const [state, setState] = useState("");
    const [category, setCategory] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");

    async function submit(e: FormEvent) {
        e.preventDefault();
        setError("");
        setBusy(true);
        try {
            await subscribe({
                chat_id: chatId.trim(),
                kind,
                pincode: kind === "pincode" ? pincode.trim() : undefined,
                city: kind === "city" ? city.trim() : undefined,
                state: kind === "city" || kind === "state" ? state.trim() : undefined,
                category: category || undefined,
            });
            toast.show("Alerts are on. You will get a Telegram message for new reports.", "success");
            onClose();
        } catch (err) {
            setError(apiErrorMessage(err));
        } finally {
            setBusy(false);
        }
    }

    return (
        <Modal title="Get alerts for your area" onClose={onClose}>
            <form className={styles.form} onSubmit={submit}>
                <p className={styles.intro}>
                    We message you on Telegram when a new report appears in the area you choose.
                    {BOT_NAME ? (
                        <>
                            {" "}
                            Start a chat with{" "}
                            <a href={`https://t.me/${BOT_NAME}`} target="_blank" rel="noopener noreferrer">
                                @{BOT_NAME}
                            </a>{" "}
                            first, otherwise Telegram will not let us message you.
                        </>
                    ) : (
                        " Start a chat with the IndiaReports bot first, otherwise Telegram will not let us message you."
                    )}
                </p>

                <TextField
                    label="Telegram chat ID"
                    inputMode="numeric"
                    value={chatId}
                    onChange={(e) => setChatId(e.target.value)}
                    hint="Send /start to @userinfobot on Telegram to see your numeric ID."
                    required
                />

                <SelectField label="Area type" value={kind} onChange={(e) => setKind(e.target.value as SubscriptionKind)}>
                    <option value="pincode">Pincode</option>
                    <option value="city">City</option>
                    <option value="state">State</option>
                </SelectField>

                {kind === "pincode" && (
                    <TextField
                        label="Pincode"
                        inputMode="numeric"
                        maxLength={6}
                        value={pincode}
                        onChange={(e) => setPincode(e.target.value)}
                        required
                    />
                )}
                {kind === "city" && (
                    <TextField label="City" value={city} onChange={(e) => setCity(e.target.value)} required />
                )}
                {(kind === "city" || kind === "state") && (
                    <TextField label="State" value={state} onChange={(e) => setState(e.target.value)} required />
                )}

                <SelectField label="Category (optional)" value={category} onChange={(e) => setCategory(e.target.value)}>
                    <option value="">All categories</option>
                    {CATEGORIES.map((c) => (
                        <option key={c} value={c}>
                            {c}
                        </option>
                    ))}
                </SelectField>

                {error && (
                    <p className={styles.error} role="alert">
                        {error}
                    </p>
                )}

                <div className={styles.actions}>
                    <Button variant="ghost" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button type="submit" loading={busy}>
                        Turn on alerts
                    </Button>
                </div>
            </form>
        </Modal>
    );
}

export default AlertsDialog;
