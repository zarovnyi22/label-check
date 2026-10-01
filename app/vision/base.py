"""Provider-neutral vision interface: photos + prompt -> the model's JSON answer.

The client only transports: it does not validate the answer against LabelExtraction or
retry on bad JSON (extraction.py, B3b). Switching providers is VISION_PROVIDER=gemini|groq;
VISION_FALLBACK_PROVIDER adds a second one behind it (fallback.py). Same shape as
`pet`'s app/llm/base.py, with vision_* error codes.
"""

import asyncio
import json
import logging
import random
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.errors import AppError
from app.images import PreparedImage

logger = logging.getLogger("app.vision")


class VisionError(AppError):
    def __init__(self, message: str, *, code: str = "vision_error", status_code: int = 502) -> None:
        super().__init__(status_code, code, message)


@dataclass
class VisionResult:
    data: dict[str, Any] | None  # the answer parsed as a JSON object; None if it is not one
    raw_text: str  # verbatim, kept for audit even when it does not parse
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""  # "provider/model" that answered


class VisionClient(ABC):
    provider: str
    model: str
    max_images: int = 4
    fallback_provider: str | None = None

    @abstractmethod
    async def extract(
        self, images: list[PreparedImage], prompt: str, *, schema: dict[str, Any] | None = None
    ) -> VisionResult:
        """One model call with all photos. `schema`: a response schema, where supported."""

    async def aclose(self) -> None:  # noqa: B027 — optional hook, no-op by default
        pass


TOKEN_FIELDS = ("input_tokens", "output_tokens", "reasoning_tokens", "total_tokens")
UsageParser = Callable[[dict[str, Any]], dict[str, int]]

# 503 and timeouts are transient (B1b/pet: Gemini "high demand" for seconds): retried with
# growing pauses plus jitter, all pauses and attempts within RETRY_BUDGET_SECONDS. 429 is not
# retried (a per-minute quota will not recover in seconds; the fallback may take it), neither
# is an invalid key or any other 4xx.
RETRYABLE = ("vision_unavailable", "vision_timeout")
RETRY_DELAYS_SECONDS = (2.0, 4.0, 8.0)
RETRY_JITTER_SECONDS = 1.0
RETRY_BUDGET_SECONDS = 60.0
_sleep = asyncio.sleep  # replaced in tests
_clock = time.monotonic  # replaced in tests


@dataclass
class Endpoint:
    """Where and how to call one provider; key_env names the key variable for messages."""

    provider: str
    key_env: str
    api_key: str
    url: str
    headers: dict[str, str]
    usage: UsageParser


async def post_json(http: httpx.AsyncClient, endpoint: Endpoint, body: dict) -> dict:
    """POST with retries on 503/timeout; the last error is raised when they run out."""
    started = _clock()
    for delay in (*RETRY_DELAYS_SECONDS, None):
        try:
            return await _post_once(http, endpoint, body)
        except VisionError as exc:
            if exc.code not in RETRYABLE or delay is None:
                raise
            pause = delay + random.uniform(0, RETRY_JITTER_SECONDS)
            if _clock() - started + pause > RETRY_BUDGET_SECONDS:
                raise
            logger.warning(
                "vision retry",
                extra={"provider": endpoint.provider, "reason": exc.code, "pause_s": pause},
            )
            await _sleep(pause)
    raise AssertionError("unreachable")


async def _post_once(http: httpx.AsyncClient, endpoint: Endpoint, body: dict) -> dict:
    provider = endpoint.provider
    started = time.monotonic()
    try:
        resp = await http.post(endpoint.url, headers=endpoint.headers, json=body)
    except httpx.TimeoutException:
        logger.info("vision request", extra={"provider": provider, "error": "timeout"})
        raise VisionError(
            f"{provider}: немає відповіді за відведений час", code="vision_timeout", status_code=504
        ) from None
    except httpx.HTTPError as exc:  # DNS, refused connection: may recover
        logger.info("vision request", extra={"provider": provider, "error": type(exc).__name__})
        raise VisionError(
            f"{provider} недоступний: {type(exc).__name__}",
            code="vision_unavailable",
            status_code=503,
        ) from None
    data = _json_or_none(resp) if resp.status_code < 400 else None
    logger.info(
        "vision request",
        extra={
            "provider": provider,
            "status": resp.status_code,
            "duration_ms": int((time.monotonic() - started) * 1000),
            **(endpoint.usage(data) if data else {}),
        },
    )
    if resp.status_code == 401 or (resp.status_code == 400 and "API_KEY_INVALID" in resp.text):
        # Groq: 401 invalid_api_key; Gemini: 400 API_KEY_INVALID. Configuration, not a
        # provider failure: the variable to fix, never the body (it may quote the key).
        raise VisionError(
            f"{endpoint.key_env} недійсний (провайдер {provider})",
            code="vision_invalid_key",
            status_code=503,
        )
    if resp.status_code == 429:
        raise VisionError(
            f"{provider}: перевищено ліміт запитів", code="vision_rate_limited", status_code=503
        )
    if resp.status_code in (500, 502, 503, 504):
        raise VisionError(
            f"{provider} тимчасово недоступний (HTTP {resp.status_code}): "
            f"{_excerpt(resp.text, endpoint.api_key)}",
            code="vision_unavailable",
            status_code=503,
        )
    if resp.status_code >= 400:
        raise VisionError(
            f"{provider} повернув HTTP {resp.status_code}: {_excerpt(resp.text, endpoint.api_key)}"
        )
    if data is None:
        raise VisionError(f"{provider}: відповідь API не JSON", code="vision_bad_output")
    return data


def _json_or_none(resp: httpx.Response) -> dict | None:
    try:
        data = resp.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _excerpt(text: str, api_key: str) -> str:
    """A short piece of a provider's error body, never with the key in it."""
    # Mask before cutting: a key across the 300-char boundary would leak its head (RR2 #2).
    return (text.replace(api_key, "***") if api_key else text)[:300]


_THINK_RE = re.compile(r"<think>.*?</think>", re.S)
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def parse_answer(text: str) -> dict[str, Any] | None:
    """The model's text -> a JSON object, or None. Strips <think> blocks and a ``` fence
    (JSON modes still sometimes wrap); anything else that is not one object is None."""
    text = _THINK_RE.sub("", text).strip()
    if m := _FENCE_RE.match(text):
        text = m[1]
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def require_key(provider: str, env_var: str, key: str) -> None:
    if not key:
        raise VisionError(
            f"{env_var} не задано (VISION_PROVIDER={provider})",
            code="vision_not_configured",
            status_code=503,
        )


def get_vision_client(settings) -> VisionClient:
    """VISION_PROVIDER's client, behind which VISION_FALLBACK_PROVIDER's, if set."""
    primary = _provider_client(settings.vision_provider, settings)
    if not settings.vision_fallback_provider:
        return primary
    from app.vision.fallback import FallbackVisionClient

    return FallbackVisionClient(
        primary, _provider_client(settings.vision_fallback_provider, settings)
    )


def _provider_client(name: str, settings) -> VisionClient:
    # Imported here so the fake and tests never pull in provider modules they do not need.
    if name == "gemini":
        from app.vision.gemini import GeminiVision

        return GeminiVision(
            settings.gemini_api_key, settings.vision_model, settings.vision_timeout_seconds
        )
    if name == "groq":
        from app.vision.groq import GroqVision

        return GroqVision(
            settings.groq_api_key, settings.groq_vision_model, settings.vision_timeout_seconds
        )
    raise ValueError(f"unknown vision provider: {name}")
