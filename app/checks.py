"""run_check: prepared photos + optional recipe -> extraction -> findings -> verdict.

Shared by POST /checks and eval (B5a). Steps: (1) photos are prepared by the caller
(app.images), (2) extraction from the cache or one model call, (3) validation with one
re-ask, (4) rules in code, (5) verdict. The whole extraction runs under
VISION_DEADLINE_SECONDS. save_check/save_error store the audit record (SPEC §3).
"""

import asyncio
import json
import time
from collections import Counter
from dataclasses import dataclass

import asyncpg

from app.extraction import BadOutputError, Extracted, extract_label, model_id
from app.images import PreparedImage
from app.rules.engine import RULES_VERSION, run_rules
from app.schemas import CheckOut, Finding, LabelExtraction, ProductSpec, Verdict
from app.vision.base import VisionClient, VisionError
from app.vision.prompt import PROMPT_VERSION


@dataclass
class CheckRun:
    extracted: Extracted
    findings: list[Finding]
    verdict: Verdict
    duration_ms: int


async def run_check(
    pool: asyncpg.Pool,
    vision: VisionClient,
    images: list[PreparedImage],
    spec: ProductSpec | None,
    deadline_seconds: float,
) -> CheckRun:
    started = time.monotonic()
    try:
        async with asyncio.timeout(deadline_seconds):
            extracted = await extract_label(pool, vision, images)
    except TimeoutError:
        raise VisionError(
            f"Модель не відповіла за {deadline_seconds:g} с (VISION_DEADLINE_SECONDS) — "
            "повторіть пізніше.",
            code="vision_timeout",
            status_code=504,
        ) from None
    findings, verdict = run_rules(extracted.extraction, spec)
    return CheckRun(extracted, findings, verdict, int((time.monotonic() - started) * 1000))


SUMMARY_UK = {
    "fail": "Є порушення — етикетку потрібно виправити.",
    "needs_review": "Порушень не знайдено, але частину перевірок має підтвердити технолог.",
    "incomplete": "Порушень не знайдено, але не все можна було перевірити.",
    "pass": "Усі застосовні перевірки пройдено.",
}
STATUS_UK = {
    "violation": "порушення",
    "needs_review": "на перевірку",
    "not_checked": "не перевірено",
    "pass": "пройдено",
}


def summary(findings: list[Finding], verdict: Verdict) -> str:
    counts = Counter(f.status for f in findings)
    parts = [f"{STATUS_UK[s]}: {counts[s]}" for s in STATUS_UK if counts[s]]
    return f"{SUMMARY_UK[verdict]} ({', '.join(parts)})" if parts else SUMMARY_UK[verdict]


async def _insert(conn, images: list[PreparedImage], **fields) -> int:
    columns = ", ".join(fields)
    params = ", ".join(f"${i}" for i in range(1, len(fields) + 1))
    check_id = await conn.fetchval(
        f"INSERT INTO checks ({columns}) VALUES ({params}) RETURNING id", *fields.values()
    )
    await conn.executemany(
        "INSERT INTO check_images (check_id, idx, sha256, mime, width, height, data) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        [
            (check_id, i, im.sha256, im.mime, im.width, im.height, im.data)
            for i, im in enumerate(images)
        ],
    )
    return check_id


def _spec_json(spec: ProductSpec | None) -> str | None:
    return spec.model_dump_json() if spec else None


async def save_check(
    pool: asyncpg.Pool, images: list[PreparedImage], spec: ProductSpec | None, run: CheckRun
) -> CheckOut:
    ex = run.extracted
    async with pool.acquire() as conn, conn.transaction():
        check_id = await _insert(
            conn,
            images,
            status="done",
            verdict=run.verdict,
            spec=_spec_json(spec),
            extraction=ex.extraction.model_dump_json(),
            findings=json.dumps([f.model_dump() for f in run.findings], ensure_ascii=False),
            model=ex.model,
            prompt_version=PROMPT_VERSION,
            rules_version=RULES_VERSION,
            usage=json.dumps(ex.usage),
            raw_text=ex.raw_text,
            cache_hit=ex.cache_hit,
            duration_ms=run.duration_ms,
        )
    return CheckOut(
        check_id=check_id,
        status="done",
        verdict=run.verdict,
        summary=summary(run.findings, run.verdict),
        findings=run.findings,
        extraction=ex.extraction,
        model=ex.model,
        rules_version=RULES_VERSION,
        prompt_version=PROMPT_VERSION,
        cache_hit=ex.cache_hit,
        duration_ms=run.duration_ms,
    )


async def save_error(
    pool: asyncpg.Pool,
    images: list[PreparedImage],
    spec: ProductSpec | None,
    vision: VisionClient,
    error: VisionError,
    duration_ms: int,
) -> int:
    """A failed check is stored too (status=error, no verdict): never a pass."""
    bad = error if isinstance(error, BadOutputError) else None
    async with pool.acquire() as conn, conn.transaction():
        return await _insert(
            conn,
            images,
            status="error",
            spec=_spec_json(spec),
            error=json.dumps({"code": error.code, "message": error.message}, ensure_ascii=False),
            model=bad.model if bad else model_id(vision),
            prompt_version=PROMPT_VERSION,
            rules_version=RULES_VERSION,
            usage=json.dumps(bad.usage) if bad else None,
            raw_text=bad.raw_text if bad else None,
            cache_hit=False,
            duration_ms=duration_ms,
        )


async def load_check(pool: asyncpg.Pool, check_id: int) -> CheckOut | None:
    row = await pool.fetchrow("SELECT * FROM checks WHERE id = $1", check_id)
    if row is None:
        return None
    findings = [Finding.model_validate(f) for f in json.loads(row["findings"] or "[]")]
    return CheckOut(
        check_id=row["id"],
        status=row["status"],
        verdict=row["verdict"],
        summary=(
            summary(findings, row["verdict"])
            if row["verdict"]
            else "Перевірку не виконано: помилка моделі (див. error)."
        ),
        findings=findings,
        extraction=(
            LabelExtraction.model_validate_json(row["extraction"]) if row["extraction"] else None
        ),
        model=row["model"],
        rules_version=row["rules_version"],
        prompt_version=row["prompt_version"],
        cache_hit=row["cache_hit"],
        duration_ms=row["duration_ms"],
        error=json.loads(row["error"]) if row["error"] else None,
    )
