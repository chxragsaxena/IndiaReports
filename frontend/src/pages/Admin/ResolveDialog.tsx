import { useState } from "react";
import type { FormEvent } from "react";

import Button from "../../components/UI/Button/Button";
import { TextArea } from "../../components/UI/Input/Input";
import Modal from "../../components/UI/Modal/Modal";
import styles from "./Admin.module.css";

interface Props {
    title: string;
    /** Days the citizen has to check the fix before the report leaves the map. */
    visibleDays: number;
    onSubmit: (note: string) => Promise<void>;
    onClose: () => void;
}

/** Marking a report resolved: say what was done, because the citizen reads it. */
function ResolveDialog({ title, visibleDays, onSubmit, onClose }: Props) {
    const [note, setNote] = useState("");
    const [busy, setBusy] = useState(false);

    async function submit(e: FormEvent) {
        e.preventDefault();
        setBusy(true);
        try {
            await onSubmit(note);
        } finally {
            setBusy(false);
        }
    }

    return (
        <Modal title="Mark as resolved" onClose={onClose}>
            <form className={styles.dialogForm} onSubmit={submit}>
                <p className={styles.dialogLead}>{title}</p>
                <TextArea
                    label="What was done?"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    maxLength={1000}
                    rows={4}
                    placeholder="For example: Pothole filled and levelled on Tuesday."
                    hint={`The citizen reads this and gets an email. The report stays on the map for ${visibleDays} day${visibleDays === 1 ? "" : "s"} so they can check it, and they can reopen it if it is not fixed.`}
                />
                <div className={styles.dialogActions}>
                    <Button type="button" variant="secondary" onClick={onClose}>
                        Cancel
                    </Button>
                    <Button type="submit" loading={busy}>
                        Mark resolved
                    </Button>
                </div>
            </form>
        </Modal>
    );
}

export default ResolveDialog;
