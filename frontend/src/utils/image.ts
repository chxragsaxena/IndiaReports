export const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"];
export const MAX_PHOTOS = 3;
/** Phones produce large files; we shrink them before upload, so allow generous originals. */
export const MAX_ORIGINAL_BYTES = 25 * 1024 * 1024;

/** A readable reason a file cannot be used, or null if it is fine. */
export function photoProblem(file: File): string | null {
    if (!ACCEPTED_TYPES.includes(file.type)) return "Only JPEG, PNG or WebP photos can be attached.";
    if (file.size > MAX_ORIGINAL_BYTES) return "That photo is too large. Please choose a smaller one.";
    return null;
}

/**
 * Shrinks a photo before it is uploaded: far less data on a slow mobile connection, and
 * the re-draw drops embedded metadata such as the GPS position. The server re-encodes
 * every upload again, so this is a courtesy, not the security boundary. If the browser
 * cannot do it, the original file is sent instead.
 */
export async function compressPhoto(file: File, maxEdge = 1600, quality = 0.82): Promise<Blob> {
    try {
        const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
        const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(bitmap.width * scale));
        canvas.height = Math.max(1, Math.round(bitmap.height * scale));
        const context = canvas.getContext("2d");
        if (!context) return file;
        context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        bitmap.close();
        const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
        return blob && blob.size < file.size ? blob : file;
    } catch {
        return file;
    }
}
