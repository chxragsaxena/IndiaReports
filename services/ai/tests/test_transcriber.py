import httpx
import pytest

from app.analysis.analyzer import AnalysisError
from app.analysis.transcriber import MockTranscriber, WhisperTranscriber, parse


def server(handler, **kwargs):
    client = httpx.AsyncClient(base_url="http://speech.test/v1", transport=httpx.MockTransport(handler))

    async def no_sleep(_seconds):
        return None

    return WhisperTranscriber(client=client, model="whisper-test", sleep=no_sleep, **kwargs)


def answer(**body):
    return httpx.Response(200, json=body)


async def test_the_recording_is_sent_as_a_file_with_the_model_and_the_text_comes_back():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = request.content
        return answer(text=" Sadak par bada gaddha hai. ", language="hindi")

    result = await server(handler).transcribe(b"\x1a\x45\xdf\xa3audio", "audio/webm")
    assert result.text == "Sadak par bada gaddha hai." and result.language == "Hindi"
    assert seen["path"] == "/v1/audio/transcriptions"
    assert b'name="model"' in seen["body"] and b"whisper-test" in seen["body"]
    assert b'filename="voice.webm"' in seen["body"] and b"audio/webm" in seen["body"]
    assert b"verbose_json" in seen["body"]


async def test_segments_the_model_thinks_are_silence_are_dropped():
    body = {
        "text": "There is a pothole. Thank you.", "language": "english",
        "segments": [
            {"text": " There is a pothole.", "no_speech_prob": 0.02},
            {"text": " Thank you.", "no_speech_prob": 0.93},  # Whisper invents these for silence
        ],
    }
    assert parse(body).text == "There is a pothole."


def test_a_recording_of_only_silence_gives_no_text():
    assert parse({"text": "Thank you.", "language": "english", "segments": [{"text": "Thank you.", "no_speech_prob": 0.97}]}).text == ""


def test_a_missing_language_and_oversized_text_are_handled():
    result = parse({"text": "word " * 4000})
    assert result.language == "" and len(result.text) <= 5000


async def test_rate_limits_are_waited_out_then_retried():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={"error": {"message": "slow down"}})
        return answer(text="hello", language="english")

    assert (await server(handler).transcribe(b"a", "audio/webm")).text == "hello"
    assert len(calls) == 2


async def test_staying_rate_limited_is_retryable_later():
    handler = lambda request: httpx.Response(429, headers={"Retry-After": "1"}, json={"error": {"message": "slow down"}})
    with pytest.raises(AnalysisError) as caught:
        await server(handler).transcribe(b"a", "audio/webm")
    assert caught.value.retryable is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413])
async def test_a_refusal_that_will_not_change_is_not_retried(status):
    handler = lambda request: httpx.Response(status, json={"error": {"type": "invalid_request_error", "message": "bad"}})
    with pytest.raises(AnalysisError) as caught:
        await server(handler).transcribe(b"a", "audio/webm")
    assert caught.value.retryable is False


async def test_server_errors_and_unreadable_answers_are_retried():
    for response in (httpx.Response(503, json={}), httpx.Response(200, content=b"not json")):
        with pytest.raises(AnalysisError) as caught:
            await server(lambda request, r=response: r).transcribe(b"a", "audio/webm")
        assert caught.value.retryable is True


async def test_the_mock_is_labelled_as_a_demo():
    result = await MockTranscriber().transcribe(b"a", "audio/webm")
    assert "DEMO" in result.text


async def test_a_chosen_language_is_sent_so_the_model_does_not_guess():
    bodies = []

    def handler(request):
        bodies.append(request.content)
        return answer(text="sadak par gaddha hai", language="hindi")

    await server(handler).transcribe(b"a", "audio/webm", "hi")
    assert len(bodies) == 1 and b'name="language"' in bodies[0]


async def test_no_language_is_sent_when_none_was_chosen():
    bodies = []

    def handler(request):
        bodies.append(request.content)
        return answer(text="hello", language="english")

    await server(handler).transcribe(b"a", "audio/webm")
    assert b'name="language"' not in bodies[0]


async def test_urdu_with_no_language_chosen_is_read_again_as_hindi():
    bodies = []

    def handler(request):
        bodies.append(request.content)
        if len(bodies) == 1:
            return answer(text="سڑک پر گٹھا ہے", language="urdu")
        return answer(text="सड़क पर गड्ढा है", language="hindi")

    result = await server(handler).transcribe(b"a", "audio/webm")
    assert len(bodies) == 2 and b'name="language"' not in bodies[0] and b"hi" in bodies[1].split(b'name="language"')[1][:20]
    assert result.language == "Hindi" and result.text.startswith("सड़")


async def test_urdu_that_the_speaker_chose_is_left_alone():
    calls = []

    def handler(request):
        calls.append(1)
        return answer(text="گٹھا", language="urdu")

    result = await server(handler).transcribe(b"a", "audio/webm", "ur")
    assert len(calls) == 1 and result.language == "Urdu"
