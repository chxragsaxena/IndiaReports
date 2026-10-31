/** The description a report carries when the person only spoke. The server swaps in the transcript;
 *  it must match VOICE_PLACEHOLDER in backend/app/core/audio.py. */
export const VOICE_PLACEHOLDER = "Voice report. The spoken description is being transcribed.";

export const MAX_VOICE_SECONDS = 60;
export const MAX_VOICE_BYTES = 3 * 1024 * 1024;

// Browsers record different containers: Chrome and Edge webm, Firefox webm or ogg, Safari mp4.
const CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];

export function voiceSupported(): boolean {
    return (
        typeof window !== "undefined" &&
        typeof window.MediaRecorder !== "undefined" &&
        typeof navigator !== "undefined" &&
        !!navigator.mediaDevices?.getUserMedia
    );
}

/** The first format this browser can record, or "" to let it choose. */
export function pickMimeType(): string {
    return CANDIDATES.find((t) => window.MediaRecorder.isTypeSupported(t)) ?? "";
}

export function clock(seconds: number): string {
    const s = Math.max(0, Math.floor(seconds));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
