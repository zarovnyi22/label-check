"""Scripted vision model for tests: queued answers, never touches the network."""

import json
from typing import Any

from app.images import PreparedImage
from app.vision.base import VisionClient, VisionError, VisionResult, parse_answer


class FakeVision(VisionClient):
    provider = "fake"
    model = "fake"

    def __init__(self, answers: list[str | dict | VisionError] | None = None) -> None:
        self.answers = list(answers or [])
        # every call received, for assertions: (images, prompt, schema)
        self.calls: list[tuple[list[PreparedImage], str, dict[str, Any] | None]] = []

    async def extract(
        self, images: list[PreparedImage], prompt: str, *, schema: dict[str, Any] | None = None
    ) -> VisionResult:
        self.calls.append((list(images), prompt, schema))
        if not self.answers:
            raise AssertionError("FakeVision: no scripted answers left")
        answer = self.answers.pop(0)
        if isinstance(answer, VisionError):
            raise answer
        text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        return VisionResult(parse_answer(text), text, {"total_tokens": 0}, "fake/fake")
