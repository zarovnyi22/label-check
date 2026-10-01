"""Photos -> LabelExtraction: the cache, one model call, validation, one re-ask.

Cache key (SPEC §3): sha256 of the photo hashes in upload order + PROMPT_VERSION + model.
The order is part of the key because photo_index in the extraction refers to it. A result
is looked up under the primary model and stored under the model that answered, so a
fallback's answer never stands in for the primary's (the trust number is the primary's).
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import asyncpg
from pydantic import ValidationError

from app.images import PreparedImage
from app.schemas import LabelExtraction
from app.vision.base import TOKEN_FIELDS, VisionClient, VisionError, VisionResult
from app.vision.prompt import PROMPT_VERSION, RETRY_SUFFIX, build_prompt

logger = logging.getLogger("app.extraction")


class BadOutputError(VisionError):
    """vision_bad_output, carrying what the model said: it is stored for audit."""

    def __init__(self, message: str, raw_text: str, usage: dict[str, int], model: str) -> None:
        super().__init__(message, code="vision_bad_output", status_code=502)
        self.raw_text = raw_text
        self.usage = usage
        self.model = model


@dataclass
class Extracted:
    extraction: LabelExtraction
    raw_text: str
    model: str
    cache_hit: bool
    usage: dict[str, int] = field(default_factory=dict)  # {} on a cache hit: no tokens spent


def model_id(vision: VisionClient) -> str:
    return f"{vision.provider}/{vision.model}"


def cache_key(images: list[PreparedImage], model: str) -> str:
    photos = hashlib.sha256("|".join(i.sha256 for i in images).encode()).hexdigest()
    return hashlib.sha256(f"{photos}|{PROMPT_VERSION}|{model}".encode()).hexdigest()


def validate(result: VisionResult) -> LabelExtraction:
    """The model's answer -> LabelExtraction; ValueError with a reason the model can act on."""
    if result.data is None:
        raise ValueError("the answer is not a single JSON object")
    try:
        return LabelExtraction.model_validate(result.data)
    except ValidationError as exc:
        reasons = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
        )
        raise ValueError(f"the JSON does not match the format: {reasons}") from None


async def extract_label(
    pool: asyncpg.Pool, vision: VisionClient, images: list[PreparedImage]
) -> Extracted:
    primary_key = cache_key(images, model_id(vision))
    row = await pool.fetchrow(
        "SELECT extraction, raw_text, model FROM extraction_cache WHERE cache_key = $1",
        primary_key,
    )
    if row:
        extraction = LabelExtraction.model_validate_json(row["extraction"])
        return Extracted(extraction, row["raw_text"], row["model"], cache_hit=True)

    prompt = build_prompt(len(images))
    result = await vision.extract(images, prompt)
    usage = dict(result.usage)
    try:
        extraction = validate(result)
    except ValueError as first:
        logger.warning("vision bad output, asking again", extra={"reason": str(first)})
        retry = await vision.extract(images, prompt + RETRY_SUFFIX.format(error=first))
        usage = _add(usage, retry.usage)
        try:
            extraction = validate(retry)
        except ValueError as second:
            raw = f"{result.raw_text}\n--- retry ---\n{retry.raw_text}"
            raise BadOutputError(
                f"Модель двічі повернула непридатну відповідь: {second}", raw, usage, retry.model
            ) from None
        result = retry

    await pool.execute(
        "INSERT INTO extraction_cache (cache_key, prompt_version, model, extraction, raw_text, "
        "usage) VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (cache_key) DO NOTHING",
        cache_key(images, result.model),
        PROMPT_VERSION,
        result.model,
        extraction.model_dump_json(),
        result.raw_text,
        json.dumps(usage),
    )
    return Extracted(extraction, result.raw_text, result.model, cache_hit=False, usage=usage)


def _add(a: dict[str, Any], b: dict[str, Any]) -> dict[str, int]:
    return {f: a.get(f, 0) + b.get(f, 0) for f in TOKEN_FIELDS if f in a or f in b}
