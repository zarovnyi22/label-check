"""Groq via its OpenAI-compatible chat completions API, no SDK: photos as data-URIs.

qwen/qwen3.8-27b is Groq's only vision model and takes at most 3 photos a request (B0), so
this client is the fallback for requests of <= 3 photos (fallback.py).
"""

import base64
from typing import Any

import httpx

from app.errors import AppError
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

URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_IMAGES = 3


class GroqVision(VisionClient):
    provider = "groq"
    key_env = "GROQ_API_KEY"
    max_images = MAX_IMAGES

    def __init__(
        self, api_key: str, model: str, timeout: float, http: httpx.AsyncClient | None = None
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._http = http or httpx.AsyncClient(timeout=timeout)

    async def extract(
        self, images: list[PreparedImage], prompt: str, *, schema: dict[str, Any] | None = None
    ) -> VisionResult:
        """`schema` is ignored: Groq's JSON mode takes no schema."""
        require_key(self.provider, self.key_env, self._api_key)
        if len(images) > self.max_images:
            # Only when groq is the primary provider: the fallback never sends more.
            raise AppError(
                422,
                "too_many_images",
                f"VISION_PROVIDER=groq приймає до {self.max_images} фото на запит, "
                f"надіслано {len(images)}",
            )
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for i, image in enumerate(images):
            content.append({"type": "text", "text": f"Photo {i}:"})
            url = f"data:{image.mime};base64,{base64.b64encode(image.data).decode()}"
            content.append({"type": "image_url", "image_url": {"url": url}})
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        endpoint = Endpoint(
            self.provider,
            self.key_env,
            self._api_key,
            URL,
            {"Authorization": f"Bearer {self._api_key}"},
            usage,
        )
        data = await post_json(self._http, endpoint, body)
        choices = data.get("choices") or []
        if not choices:
            raise VisionError("groq не дав відповіді", code="vision_bad_output")
        text = (choices[0].get("message") or {}).get("content") or ""
        return VisionResult(parse_answer(text), text, usage(data), f"groq/{self.model}")

    async def aclose(self) -> None:
        await self._http.aclose()


def usage(data: dict[str, Any]) -> dict[str, int]:
    u = data.get("usage")
    if not u:
        return {}
    details = u.get("completion_tokens_details") or {}
    return {
        "input_tokens": u.get("prompt_tokens", 0),
        "output_tokens": u.get("completion_tokens", 0),
        "reasoning_tokens": details.get("reasoning_tokens", 0),
        "total_tokens": u.get("total_tokens", 0),
    }
