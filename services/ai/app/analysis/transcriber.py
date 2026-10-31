"""Speech to text: what a resident said in a voice note, in whatever Indian language they spoke.
An open-weight Whisper model does this through an OpenAI-compatible /audio/transcriptions endpoint
(Groq hosts it for free; a local faster-whisper server speaks the same API). The transcript is
assistive: staff can play the original recording next to it.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from app.analysis.analyzer import (
    GROQ_BASE_URL,
    MAX_RATE_LIMIT_RETRIES,
    MAX_RATE_LIMIT_WAIT,
    AnalysisError,
    _api_error,
    resolve_provider,
    retry_delay,
)
from app.config import settings

logger = logging.getLogger(__name__)

GROQ_TRANSCRIBE_MODEL = "whisper-large-v3"  # the more accurate of Groq's two Whisper models (checked 2026-10)

# Whisper invents words ("Thank you.") for silence and noise. A segment it is this sure holds no speech is dropped.
NO_SPEECH_ABOVE = 0.6

# A hint about the kind of speech, which helps with local place and civic words. Kept in English and short.
HINT = "A resident of India describes a civic problem such as a pothole, garbage, drainage, a water leak or a broken street light."


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str


def _words(value: object) -> str:
    return " ".join(str(value or "").split())


def parse(body: dict) -> Transcript:
    """The text and language from a verbose_json answer, with segments that are silence removed."""
    segments = body.get("segments")
    if isinstance(segments, list) and segments:
        kept = [
            _words(s.get("text"))
            for s in segments
            if isinstance(s, dict) and float(s.get("no_speech_prob") or 0) <= NO_SPEECH_ABOVE
        ]
        text = " ".join(t for t in kept if t)
    else:
        text = _words(body.get("text"))
    language = _words(body.get("language")).title()  # "hindi" -> "Hindi"
    return Transcript(text=text[:5000], language=language[:40])


class WhisperTranscriber:
    """The /audio/transcriptions call, with the same rate-limit handling as the photo model."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        provider: str = "openai_compatible",
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.provider = provider
        self.model = model or settings.TRANSCRIBE_MODEL or GROQ_TRANSCRIBE_MODEL
        self._sleep = sleep
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.AsyncClient(
            base_url=(base_url or "").rstrip("/"), headers=headers,
            timeout=httpx.Timeout(settings.ANALYSIS_TIMEOUT_SECONDS, connect=10.0),
        )

    async def _post(self, audio: bytes, content_type: str, language: str | None = None) -> httpx.Response:
        extension = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/wav": "wav", "audio/mpeg": "mp3"}.get(content_type, "webm")
        form = {"model": self.model, "response_format": "verbose_json", "temperature": "0", "prompt": HINT}
        if language:
            form["language"] = language  # stops the model guessing the language
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            try:
                response = await self._client.post(
                    "/audio/transcriptions",
                    files={"file": (f"voice.{extension}", audio, content_type)},
                    data=form,
                )
            except (httpx.TimeoutException, httpx.TransportError):
                raise AnalysisError("The speech model server was unreachable or too slow; will retry.", retryable=True)
            if response.status_code != 429:
                return response
            _, message = _api_error(response)
            wait = retry_delay(response.headers, message)
            if attempt >= MAX_RATE_LIMIT_RETRIES or wait > MAX_RATE_LIMIT_WAIT:
                raise AnalysisError("The speech model is rate limited right now; will retry later.", retryable=True)
            await self._sleep(wait)
        raise AnalysisError("rate limited", retryable=True)  # pragma: no cover

    async def transcribe(self, audio: bytes, content_type: str, language: str | None = None) -> Transcript:
        result = await self._transcribe_once(audio, content_type, language)
        if language is None and result.language == "Urdu":
            # Hindi and Urdu sound almost the same, and the model often calls Hindi "Urdu" and writes it in
            # Arabic script, which most officers cannot read. Nobody named a language, so read it as Hindi.
            logger.info("detected Urdu with no language chosen; transcribing again as Hindi")
            return await self._transcribe_once(audio, content_type, "hi")
        return result

    async def _transcribe_once(self, audio: bytes, content_type: str, language: str | None) -> Transcript:
        response = await self._post(audio, content_type, language)
        error_type, error_message = _api_error(response)
        detail = f": {error_type} {error_message}".rstrip()[:240] if (error_type or error_message) else ""
        if response.status_code in (400, 401, 403, 404, 413, 422):
            # A bad key or model name, or audio the server cannot read: the same call will fail again.
            raise AnalysisError(f"The speech model server rejected the request ({response.status_code}{detail}).", retryable=False)
        if response.status_code >= 400:
            raise AnalysisError(f"The speech model server returned an error ({response.status_code}{detail}).", retryable=response.status_code >= 500)
        try:
            return parse(response.json())
        except (ValueError, TypeError, AttributeError):
            raise AnalysisError("The speech model server sent a response this service could not read.", retryable=True)


class MockTranscriber:
    """Deterministic stand-in for demos without a model. Clearly labelled; it hears nothing."""

    provider = "mock"
    model = "mock"

    async def transcribe(self, audio: bytes, content_type: str, language: str | None = None) -> Transcript:
        return Transcript(text="DEMO TRANSCRIPT (no speech model configured): a problem needs attention here.", language="English")


def build_transcriber():
    """None when no speech model is set up. A separate base URL because Ollama (which the text and
    photo models may use) has no audio endpoint."""
    if settings.TRANSCRIBE_BASE_URL:
        return WhisperTranscriber(
            provider="openai_compatible", base_url=settings.TRANSCRIBE_BASE_URL, api_key=settings.TRANSCRIBE_API_KEY,
        )
    provider = resolve_provider()
    if provider == "groq" and settings.GROQ_API_KEY and not settings.ANALYSIS_BASE_URL:
        return WhisperTranscriber(provider="groq", base_url=GROQ_BASE_URL, api_key=settings.GROQ_API_KEY)
    if provider == "mock":
        return MockTranscriber()
    return None
