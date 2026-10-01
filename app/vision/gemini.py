"""Gemini via the REST API (generateContent), no SDK: all photos in one call, JSON mode."""

import base64
from typing import Any

import httpx

from app.images import PreparedImage
from app.vision.base import (
    Endpoint,
    VisionClient,
    VisionError,
    VisionResult,
    parse_answer,
    post_json,
    require_key,
)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiVision(VisionClient):
    provider = "gemini"
    key_env = "GEMINI_API_KEY"

    def __init__(
        self, api_key: str, model: str, timeout: float, http: httpx.AsyncClient | None = None
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._http = http or httpx.AsyncClient(timeout=timeout)

    async def extract(
        self, images: list[PreparedImage], prompt: str, *, schema: dict[str, Any] | None = None
    ) -> VisionResult:
        require_key(self.provider, self.key_env, self._api_key)
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for i, image in enumerate(images):
            parts.append({"text": f"Photo {i}:"})
            parts.append(
                {
                    "inline_data": {
                        "mime_type": image.mime,
                        "data": base64.b64encode(image.data).decode(),
                    }
                }
            )
        config: dict[str, Any] = {"temperature": 0, "responseMimeType": "application/json"}
        if schema is not None:
            config["responseSchema"] = schema
        body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
        # The key goes in a header, never in the URL: URLs end up in logs and tracebacks.
        endpoint = Endpoint(
            self.provider,
            self.key_env,
            self._api_key,
            f"{BASE_URL}/{self.model}:generateContent",
            {"x-goog-api-key": self._api_key},
            usage,
        )
        data = await post_json(self._http, endpoint, body)
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise VisionError(f"gemini не дав відповіді: {reason}", code="vision_bad_output")
        parts_out = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts_out if not p.get("thought"))
        return VisionResult(parse_answer(text), text, usage(data), f"gemini/{self.model}")

    async def aclose(self) -> None:
        await self._http.aclose()


def usage(data: dict[str, Any]) -> dict[str, int]:
    """usageMetadata -> our token fields; thinking counts as output (same limits)."""
    meta = data.get("usageMetadata")
    if not meta:
        return {}
    prompt = meta.get("promptTokenCount", 0)
    thoughts = meta.get("thoughtsTokenCount", 0)
    output = meta.get("candidatesTokenCount", 0) + thoughts
    return {
        "input_tokens": prompt,
        "output_tokens": output,
        "reasoning_tokens": thoughts,
        "total_tokens": meta.get("totalTokenCount", prompt + output),
    }
