"""Vision clients over httpx.MockTransport: no network, no real sleeping (pauses recorded)."""

import json
import logging

import httpx
import pytest

from app.config import Settings
from app.images import PreparedImage
from app.vision import base
from app.vision.base import VisionError, get_vision_client, parse_answer
from app.vision.fake import FakeVision
from app.vision.fallback import FallbackVisionClient
from app.vision.gemini import GeminiVision
from app.vision.groq import GroqVision

KEY = "AIza-secret-test-key"
ANSWER = {"photos": [{"index": 0, "side": "back", "quality": "ok"}], "other_text": []}


def images(n: int) -> list[PreparedImage]:
    return [PreparedImage(b"\xff\xd8jpeg%d" % i, "image/jpeg", 10, 10, f"h{i}") for i in range(n)]


def gemini_ok(text: str | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"parts": [{"text": text or json.dumps(ANSWER)}]}}],
            "usageMetadata": {
                "promptTokenCount": 1900,
                "candidatesTokenCount": 600,
                "totalTokenCount": 2500,
            },
        },
    )


def groq_ok(text: str | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": text or json.dumps(ANSWER)}}],
            "usage": {"prompt_tokens": 5000, "completion_tokens": 700, "total_tokens": 5700},
        },
    )


class Script:
    """A MockTransport answering from a queue, recording requests."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


@pytest.fixture(autouse=True)
def pauses(monkeypatch):
    recorded: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(base, "_sleep", fake_sleep)
    return recorded


def gemini(script: Script, key: str = KEY) -> GeminiVision:
    return GeminiVision(key, "gemini-3.5-flash-lite", 60, http=script.http())


def groq(script: Script, key: str = "gsk-secret") -> GroqVision:
    return GroqVision(key, "qwen/qwen3.8-27b", 60, http=script.http())


async def extract_error(client, n: int = 1) -> VisionError:
    with pytest.raises(VisionError) as err:
        await client.extract(images(n), "prompt")
    return err.value


# --- Gemini ----------------------------------------------------------------------------------


async def test_gemini_success_sends_all_photos_in_one_call():
    script = Script(gemini_ok())
    result = await gemini(script).extract(images(3), "PROMPT", schema={"type": "OBJECT"})

    assert result.data == ANSWER
    assert result.model == "gemini/gemini-3.5-flash-lite"
    assert result.usage == {
        "input_tokens": 1900,
        "output_tokens": 600,
        "reasoning_tokens": 0,
        "total_tokens": 2500,
    }
    (request,) = script.requests
    assert request.url.path.endswith("/gemini-3.5-flash-lite:generateContent")
    assert request.headers["x-goog-api-key"] == KEY
    assert KEY not in str(request.url)
    body = json.loads(request.content)
    parts = body["contents"][0]["parts"]
    assert parts[0] == {"text": "PROMPT"}
    assert [p["text"] for p in parts[1::2]] == ["Photo 0:", "Photo 1:", "Photo 2:"]
    assert all(p["inline_data"]["mime_type"] == "image/jpeg" for p in parts[2::2])
    config = body["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["temperature"] == 0
    assert config["responseSchema"] == {"type": "OBJECT"}


async def test_gemini_503_twice_then_ok_retries_with_growing_pauses(pauses):
    script = Script(httpx.Response(503, text="high demand"), httpx.Response(503), gemini_ok())
    result = await gemini(script).extract(images(1), "p")
    assert result.data == ANSWER
    assert len(script.requests) == 3
    assert len(pauses) == 2
    assert 2 <= pauses[0] < 3 and 4 <= pauses[1] < 5


async def test_gemini_503_until_retries_run_out(pauses):
    script = Script(*[httpx.Response(503)] * 4)
    err = await extract_error(gemini(script))
    assert err.code == "vision_unavailable"
    assert len(script.requests) == 4  # 1 + 3 retries (2, 4, 8 s)
    assert sum(pauses) <= base.RETRY_BUDGET_SECONDS


async def test_retries_stop_at_the_time_budget(monkeypatch, pauses):
    now = [0.0]
    monkeypatch.setattr(base, "_clock", lambda: now[0])

    async def sleep(seconds: float) -> None:
        pauses.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(base, "_sleep", sleep)

    def slow_503(request):
        now[0] += 30  # each attempt hangs 30 s before 503
        return httpx.Response(503)

    http = httpx.AsyncClient(transport=httpx.MockTransport(slow_503))
    client = GeminiVision(KEY, "m", 60, http=http)
    err = await extract_error(client)
    assert err.code == "vision_unavailable"
    # 30 + ~2.5 + 30 = ~62.5 s: no second pause. The budget bounds when a retry may start;
    # the attempt itself is bounded by VISION_TIMEOUT_SECONDS.
    assert len(pauses) == 1


async def test_gemini_timeout_is_retried_then_vision_timeout(pauses):
    script = Script(*[httpx.ReadTimeout("slow")] * 4)
    err = await extract_error(gemini(script))
    assert (err.code, err.status_code) == ("vision_timeout", 504)
    assert len(script.requests) == 4


async def test_gemini_invalid_key_is_not_retried_and_not_echoed(pauses):
    body = {
        "error": {
            "message": f"API key not valid: {KEY}",
            "details": [{"reason": "API_KEY_INVALID"}],
        }
    }
    script = Script(httpx.Response(400, json=body))
    err = await extract_error(gemini(script))
    assert (err.code, err.status_code) == ("vision_invalid_key", 503)
    assert "GEMINI_API_KEY" in err.message and KEY not in err.message
    assert len(script.requests) == 1 and pauses == []


async def test_gemini_429_is_not_retried(pauses):
    script = Script(httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}}))
    err = await extract_error(gemini(script))
    assert err.code == "vision_rate_limited"
    assert len(script.requests) == 1 and pauses == []


async def test_other_4xx_is_not_retried_and_hides_the_key(pauses):
    script = Script(httpx.Response(400, text=f"bad request near {KEY}"))
    err = await extract_error(gemini(script))
    assert err.code == "vision_error"
    assert KEY not in err.message and "***" in err.message
    assert pauses == []


@pytest.mark.parametrize("offset", [285, 290, 295])
async def test_key_across_the_excerpt_boundary_is_hidden(pauses, offset):
    # RR2 #2: masking after the 300-char cut leaked the key's head.
    script = Script(httpx.Response(403, text="x" * offset + KEY + "y" * 50))
    err = await extract_error(gemini(script))
    assert KEY[:4] not in err.message


async def test_missing_key_is_not_configured_without_a_request():
    script = Script()
    err = await extract_error(gemini(script, key=""))
    assert (err.code, err.status_code) == ("vision_not_configured", 503)
    assert script.requests == []


async def test_no_candidates_is_bad_output():
    script = Script(httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}))
    err = await extract_error(gemini(script))
    assert err.code == "vision_bad_output"
    assert "SAFETY" in err.message


async def test_answer_that_is_not_json_keeps_the_raw_text():
    script = Script(gemini_ok("Here is the label: склад ..."))
    result = await gemini(script).extract(images(1), "p")
    assert result.data is None
    assert result.raw_text == "Here is the label: склад ..."


async def test_key_never_in_logs(caplog):
    caplog.set_level(logging.DEBUG)
    script = Script(httpx.Response(503, text=KEY), gemini_ok())
    await gemini(script).extract(images(1), "p")
    assert KEY not in caplog.text
    assert any(
        r.message == "vision request" and getattr(r, "total_tokens", 0) == 2500
        for r in caplog.records
    )


@pytest.mark.parametrize(
    ("text", "data"),
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('<think>hmm {"x": 0}</think>\n{"a": 1}', {"a": 1}),
        ("[1, 2]", None),
        ('{"a": ', None),
    ],
)
def test_parse_answer(text, data):
    assert parse_answer(text) == data


# --- Groq ------------------------------------------------------------------------------------


async def test_groq_success_with_data_uris():
    script = Script(groq_ok())
    result = await groq(script).extract(images(2), "PROMPT")
    assert result.data == ANSWER
    assert result.model == "groq/qwen/qwen3.8-27b"
    assert result.usage["total_tokens"] == 5700
    request = script.requests[0]
    assert request.headers["authorization"] == "Bearer gsk-secret"
    body = json.loads(request.content)
    assert body["response_format"] == {"type": "json_object"}
    content = body["messages"][0]["content"]
    urls = [c["image_url"]["url"] for c in content if c["type"] == "image_url"]
    assert len(urls) == 2 and all(u.startswith("data:image/jpeg;base64,") for u in urls)


async def test_groq_401_is_invalid_key():
    err = await extract_error(groq(Script(httpx.Response(401, json={"error": "invalid_api_key"}))))
    assert err.code == "vision_invalid_key" and "GROQ_API_KEY" in err.message


async def test_groq_as_primary_refuses_4_photos_without_a_request():
    script = Script()
    with pytest.raises(Exception) as err:
        await groq(script).extract(images(4), "p")
    assert (err.value.status_code, err.value.code) == (422, "too_many_images")
    assert script.requests == []


# --- fallback --------------------------------------------------------------------------------


async def test_fallback_after_503_retries_run_out(pauses):
    primary = Script(*[httpx.Response(503)] * 4)
    secondary = Script(groq_ok())
    client = FallbackVisionClient(gemini(primary), groq(secondary))
    result = await client.extract(images(3), "p")
    assert result.model.startswith("groq/")
    assert len(primary.requests) == 4 and len(secondary.requests) == 1


async def test_fallback_on_429_without_retries(pauses):
    primary = Script(httpx.Response(429))
    secondary = Script(groq_ok())
    result = await FallbackVisionClient(gemini(primary), groq(secondary)).extract(images(1), "p")
    assert result.model.startswith("groq/")
    assert pauses == []


async def test_no_fallback_for_4_photos():
    primary = Script(httpx.Response(429))
    secondary = Script()
    client = FallbackVisionClient(gemini(primary), groq(secondary))
    err = await extract_error(client, n=4)
    assert err.code == "vision_rate_limited"
    assert "до 3 фото" in err.message
    assert secondary.requests == []


async def test_no_fallback_on_invalid_key_or_bad_output():
    for response in (httpx.Response(400, text="API_KEY_INVALID"), httpx.Response(200, json={})):
        secondary = Script()
        client = FallbackVisionClient(gemini(Script(response)), groq(secondary))
        err = await extract_error(client)
        assert err.code in ("vision_invalid_key", "vision_bad_output")
        assert secondary.requests == []


async def test_primary_cooldown_goes_straight_to_fallback():
    primary = Script(httpx.Response(429))
    secondary = Script(groq_ok(), groq_ok())
    client = FallbackVisionClient(gemini(primary), groq(secondary))
    await client.extract(images(1), "p")
    await client.extract(images(1), "p")
    assert len(primary.requests) == 1 and len(secondary.requests) == 2


async def test_cooldown_fallback_limited_tries_primary_once_then_fails():
    primary = Script(httpx.Response(429), httpx.Response(429))
    secondary = Script(groq_ok(), httpx.Response(429))
    client = FallbackVisionClient(gemini(primary), groq(secondary))
    await client.extract(images(1), "p")
    err = await extract_error(client)
    assert err.code == "vision_rate_limited"
    assert len(primary.requests) == 2 and len(secondary.requests) == 2


# --- wiring ----------------------------------------------------------------------------------


def test_get_vision_client_from_settings():
    plain = get_vision_client(Settings(vision_provider="gemini", vision_fallback_provider=""))
    assert (plain.provider, plain.fallback_provider) == ("gemini", None)
    both = get_vision_client(Settings(vision_provider="gemini", vision_fallback_provider="groq"))
    assert (both.provider, both.fallback_provider, both.max_images) == ("gemini", "groq", 4)


async def test_fake_vision_scripts_answers_and_errors():
    fake = FakeVision([ANSWER, VisionError("down", code="vision_unavailable")])
    assert (await fake.extract(images(2), "p")).data == ANSWER
    with pytest.raises(VisionError):
        await fake.extract(images(1), "p")
    assert [len(c[0]) for c in fake.calls] == [2, 1]


async def test_health_shows_the_running_client(db_client):
    from app.main import app

    app.state.vision = FallbackVisionClient(FakeVision(), groq(Script()))
    try:
        body = (await db_client.get("/health")).json()
    finally:
        del app.state.vision
    assert (body["vision_provider"], body["vision_fallback_provider"]) == ("fake", "groq")
