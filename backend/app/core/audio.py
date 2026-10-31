"""Checking an uploaded voice note.

Photos are re-encoded so only a clean JPEG is ever stored. Audio is not re-encoded (that would need
ffmpeg in the image), so the next best thing: only formats browsers record, recognised by their
real first bytes rather than the claimed content type, and a hard size cap. The file is never
executed or parsed here; it is stored and later handed to the transcription model.
"""

from dataclasses import dataclass

# The description a report carries when the person only spoke. If it still equals this when the
# transcript arrives, the transcript replaces it. The frontend sends the same text.
VOICE_PLACEHOLDER = "Voice report. The spoken description is being transcribed."


class AudioRejected(Exception):
    """The file is not a voice note we accept."""


@dataclass(frozen=True)
class AudioKind:
    content_type: str
    extension: str


def sniff(data: bytes) -> AudioKind:
    head = data[:16]
    if head[:4] == b"\x1a\x45\xdf\xa3":  # EBML: webm (Chrome, Firefox, Edge)
        return AudioKind("audio/webm", "webm")
    if head[:4] == b"OggS":  # Firefox
        return AudioKind("audio/ogg", "ogg")
    if head[4:8] == b"ftyp":  # mp4 / m4a (Safari)
        return AudioKind("audio/mp4", "m4a")
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return AudioKind("audio/wav", "wav")
    if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return AudioKind("audio/mpeg", "mp3")
    raise AudioRejected("That does not look like a voice recording. Please record it again.")


def clamp_duration(value: int | None, limit: int) -> int | None:
    """The browser reports the length; it is only a hint for the officer, never trusted."""
    if value is None:
        return None
    return max(0, min(int(value), limit))
