/** The description a report carries when the person only spoke. The server swaps in the transcript;
 *  it must match VOICE_PLACEHOLDER in backend/app/core/audio.py. */
export const VOICE_PLACEHOLDER = "Voice report. The spoken description is being transcribed.";

export const MAX_VOICE_SECONDS = 60;
export const MAX_VOICE_BYTES = 3 * 1024 * 1024;

/** Languages a speaker can name. "" lets the model guess, which can write Hindi in Urdu script. */
export const VOICE_LANGUAGES: { code: string; label: string }[] = [
    { code: "", label: "Detect automatically" },
    { code: "hi", label: "Hindi" },
    { code: "en", label: "English" },
    { code: "bn", label: "Bengali" },
    { code: "ta", label: "Tamil" },
    { code: "te", label: "Telugu" },
    { code: "mr", label: "Marathi" },
    { code: "gu", label: "Gujarati" },
    { code: "kn", label: "Kannada" },
    { code: "ml", label: "Malayalam" },
    { code: "pa", label: "Punjabi" },
    { code: "ur", label: "Urdu" },
    { code: "ne", label: "Nepali" },
    { code: "as", label: "Assamese" },
];

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
