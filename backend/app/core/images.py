"""Turns an uploaded file into a safe, small JPEG, or refuses it.

Re-encoding is the main defence: whatever the upload claims to be, only pixels survive.
That removes embedded scripts and malformed trailers, strips EXIF (including the GPS
position and the camera owner), and bounds the size that later work has to handle.
"""

import asyncio
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_PIXELS = 40_000_000  # refuses decompression bombs before the image is decoded
MAX_EDGE = 2048
MIN_EDGE = 64
MAX_STORED_BYTES = 2_500_000  # keeps the base64 form well under a 4 MB hosted-model limit


class ImageRejected(Exception):
    """The upload cannot be used. The message is safe to show to the person."""


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    content_type: str
    width: int
    height: int


def _process(raw: bytes) -> ProcessedImage:
    try:
        image = Image.open(io.BytesIO(raw))
        if image.format not in ALLOWED_FORMATS:
            raise ImageRejected("Only JPEG, PNG or WebP photos are accepted.")
        if image.width * image.height > MAX_PIXELS:
            raise ImageRejected("That image is too large. Please use a smaller photo.")
        if getattr(image, "is_animated", False) and getattr(image, "n_frames", 1) > 1:
            raise ImageRejected("Animated images are not accepted.")
        image.load()
    except ImageRejected:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ImageRejected("That file is not a readable photo.")

    image = ImageOps.exif_transpose(image)  # honour the phone's rotation before dropping metadata
    if min(image.size) < MIN_EDGE:
        raise ImageRejected("That image is too small to be useful.")

    image = image.convert("RGB")  # drops alpha and palettes
    image.thumbnail((MAX_EDGE, MAX_EDGE))

    # A fresh file: no metadata carried over. Noisy photos can stay large even at 2048 px, and
    # hosted vision APIs cap base64 images at about 4 MB, so lower the quality until it fits.
    quality = 85
    while True:
        out = io.BytesIO()
        image.save(out, "JPEG", quality=quality, optimize=True)
        if out.tell() <= MAX_STORED_BYTES or quality <= 40:
            return ProcessedImage(out.getvalue(), "image/jpeg", image.width, image.height)
        quality -= 15


async def process_image(raw: bytes) -> ProcessedImage:
    """Decoding and encoding are CPU-bound, so they run off the event loop."""
    return await asyncio.to_thread(_process, raw)


class TooLarge(ImageRejected):
    """The upload exceeds the size limit."""


async def read_limited(file, limit: int, what: str = "photo") -> bytes:
    """Read an upload without ever holding more than `limit` bytes in memory."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise TooLarge(f"That {what} is larger than {limit // (1024 * 1024)} MB. Please use a smaller one.")
        chunks.append(chunk)
