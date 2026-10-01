"""A second provider behind the first (VISION_FALLBACK_PROVIDER), as `pet`'s llm/fallback.py.

The primary gets its full retries first (post_json). Only if they run out on 503/timeout, or
the primary answers 429, does the same call go to the fallback, and only if the fallback
takes that many photos (Groq: <= 3); otherwise the error is vision_rate_limited (CLAUDE.md,
decision 7). After a fallback the primary is skipped for PRIMARY_COOLDOWN_SECONDS, so a run
of eval calls does not spend the same retries again on every call.
"""

import logging
import time
from typing import Any

from app.images import PreparedImage
from app.vision.base import VisionClient, VisionError, VisionResult

logger = logging.getLogger("app.vision")

FALLBACK_ON = ("vision_unavailable", "vision_timeout", "vision_rate_limited")
PRIMARY_COOLDOWN_SECONDS = 60.0


class FallbackVisionClient(VisionClient):
    def __init__(self, primary: VisionClient, fallback: VisionClient) -> None:
        self.primary = primary
        self.fallback = fallback
        self.provider = primary.provider
        self.model = primary.model
        self.max_images = primary.max_images
        self.fallback_provider = fallback.provider
        self._primary_down_until = 0.0

    async def extract(
        self, images: list[PreparedImage], prompt: str, *, schema: dict[str, Any] | None = None
    ) -> VisionResult:
        fits = len(images) <= self.fallback.max_images
        fallback_limited = False
        if fits and time.monotonic() < self._primary_down_until:
            self._log("primary cooling down", len(images))
            try:
                return await self.fallback.extract(images, prompt, schema=schema)
            except VisionError as exc:
                if exc.code != "vision_rate_limited":
                    raise
                # Live (pet), the primary had often recovered by then: one try before failing.
                fallback_limited = True
                self._log("fallback rate limited: trying the primary once", len(images))
        try:
            result = await self.primary.extract(images, prompt, schema=schema)
        except VisionError as exc:
            if exc.code not in FALLBACK_ON:
                raise
            if fallback_limited:
                raise VisionError(
                    f"{self.fallback.provider}: ліміт запитів, а {self.primary.provider} досі "
                    f"недоступний ({exc.code})",
                    code="vision_rate_limited",
                    status_code=503,
                ) from None
            if not fits:
                raise VisionError(
                    f"{self.primary.provider} недоступний ({exc.code}), а запасний "
                    f"{self.fallback.provider} приймає до {self.fallback.max_images} фото "
                    f"(надіслано {len(images)}) — повторіть пізніше або надішліть менше фото",
                    code="vision_rate_limited",
                    status_code=503,
                ) from None
            self._primary_down_until = time.monotonic() + PRIMARY_COOLDOWN_SECONDS
            self._log(exc.code, len(images))
            return await self.fallback.extract(images, prompt, schema=schema)
        self._primary_down_until = 0.0
        return result

    async def aclose(self) -> None:
        await self.primary.aclose()
        await self.fallback.aclose()

    def _log(self, reason: str, photos: int) -> None:
        logger.warning(
            "vision fallback",
            extra={
                "provider": self.primary.provider,
                "fallback": self.fallback.provider,
                "reason": reason,
                "photos": photos,
            },
        )
