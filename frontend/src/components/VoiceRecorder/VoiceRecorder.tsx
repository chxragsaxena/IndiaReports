import { useEffect, useMemo, useRef, useState } from "react";

import Button from "../UI/Button/Button";
import { MAX_VOICE_BYTES, MAX_VOICE_SECONDS, clock, pickMimeType, voiceSupported } from "../../utils/voice";
import styles from "./VoiceRecorder.module.css";

export interface Recording {
    blob: Blob;
    seconds: number;
}

interface Props {
    value: Recording | null;
    onChange: (recording: Recording | null) => void;
    onProblem: (message: string) => void;
}

/** Record a spoken description in the browser. Nothing is uploaded here: the form sends it after the report is filed. */
function VoiceRecorder({ value, onChange, onProblem }: Props) {
    const [recording, setRecording] = useState(false);
    const [elapsed, setElapsed] = useState(0);
    const recorder = useRef<MediaRecorder | null>(null);
    const stream = useRef<MediaStream | null>(null);
    const timer = useRef<number | undefined>(undefined);
    const startedAt = useRef(0);

    const playback = useMemo(() => (value ? URL.createObjectURL(value.blob) : null), [value]);
    useEffect(() => () => void (playback && URL.revokeObjectURL(playback)), [playback]);

    function release() {
        window.clearInterval(timer.current);
        stream.current?.getTracks().forEach((t) => t.stop());
        stream.current = null;
    }
    useEffect(() => release, []); // closing the page must not leave the microphone on

    async function start() {
        let media: MediaStream;
        try {
            media = await navigator.mediaDevices.getUserMedia({ audio: true });
        } catch {
            onProblem("The microphone is blocked. Allow it in your browser, or type the details instead.");
            return;
        }
        stream.current = media;
        const mimeType = pickMimeType();
        const rec = new MediaRecorder(media, mimeType ? { mimeType } : undefined);
        const chunks: Blob[] = [];
        rec.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);
        rec.onstop = () => {
            const seconds = Math.round((Date.now() - startedAt.current) / 1000);
            const blob = new Blob(chunks, { type: rec.mimeType || mimeType || "audio/webm" });
            release();
            setRecording(false);
            if (blob.size > MAX_VOICE_BYTES) {
                onProblem("That recording is too large. Please keep it shorter.");
            } else if (blob.size === 0 || seconds < 1) {
                onProblem("Nothing was recorded. Please try again.");
            } else {
                onChange({ blob, seconds });
            }
        };
        recorder.current = rec;
        startedAt.current = Date.now();
        setElapsed(0);
        setRecording(true);
        rec.start();
        timer.current = window.setInterval(() => {
            const seconds = (Date.now() - startedAt.current) / 1000;
            setElapsed(seconds);
            if (seconds >= MAX_VOICE_SECONDS) stop();
        }, 250);
    }

    function stop() {
        if (recorder.current?.state === "recording") recorder.current.stop();
    }

    if (!voiceSupported()) return <p className={styles.note}>Voice recording is not supported in this browser. Please type the details.</p>;

    if (value && playback) {
        return (
            <div className={styles.box}>
                <audio controls src={playback} className={styles.player} />
                <span className={styles.note}>{clock(value.seconds)}</span>
                <Button variant="ghost" size="sm" onClick={() => onChange(null)}>
                    Remove
                </Button>
            </div>
        );
    }

    return (
        <div className={styles.box}>
            {recording ? (
                <>
                    <span className={styles.dot} aria-hidden="true" />
                    <span role="status">
                        Recording {clock(elapsed)} / {clock(MAX_VOICE_SECONDS)}
                    </span>
                    <Button variant="secondary" size="sm" onClick={stop}>
                        Stop
                    </Button>
                </>
            ) : (
                <Button variant="secondary" size="sm" onClick={() => void start()}>
                    Record a voice note
                </Button>
            )}
        </div>
    );
}

export default VoiceRecorder;
