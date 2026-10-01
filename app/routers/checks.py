"""POST /checks (photos + optional recipe -> verdict) and GET /checks/{id}."""

import asyncio
import time
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import ValidationError

from app.checks import load_check, run_check, save_check, save_error
from app.config import get_settings
from app.errors import AppError
from app.images import PreparedImage, prepare_image
from app.schemas import CheckOut, ProductSpec
from app.vision.base import VisionError

router = APIRouter(tags=["checks"])

MAX_IMAGES = 4

SPEC_EXAMPLE = (
    '{"product_name": "Вафлі з молочною начинкою", "form": "solid", '
    '"ingredients": [{"name": "борошно пшеничне", "allergens": ["cereals"]}, '
    '{"name": "молоко сухе", "allergens": ["milk"]}, {"name": "цукор"}], '
    '"may_contain": ["nuts"]}'
)


def _error(code: str, message: str) -> dict:
    example = {"error": {"code": code, "message": message}}
    return {"content": {"application/json": {"example": example}}}


ERROR_RESPONSES = {
    404: {"description": "Не знайдено", **_error("not_found", "Перевірку 7 не знайдено")},
    422: {
        "description": "Фото або рецептура не прийняті (до виклику моделі)",
        **_error("too_many_images", "Максимум 4 фото, надіслано 5"),
    },
    502: {
        "description": "Модель двічі дала непридатну відповідь (збережено зі status=error)",
        **_error("vision_bad_output", "Модель двічі повернула непридатну відповідь: …"),
    },
    503: {
        "description": "Модель недоступна, ліміт або немає ключа",
        **_error("vision_rate_limited", "gemini: перевищено ліміт запитів"),
    },
    504: {
        "description": "Модель не відповіла за VISION_DEADLINE_SECONDS",
        **_error("vision_timeout", "Модель не відповіла за 90 с (VISION_DEADLINE_SECONDS)"),
    },
}


def parse_spec(raw: str | None) -> ProductSpec | None:
    if raw is None or not raw.strip():
        return None
    try:
        return ProductSpec.model_validate_json(raw)
    except ValidationError as exc:
        reasons = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'spec'}: {e['msg']}" for e in exc.errors()[:5]
        )
        raise AppError(422, "validation_error", f"spec: {reasons}") from None


async def read_images(files: list[UploadFile]) -> list[PreparedImage]:
    if len(files) > MAX_IMAGES:
        raise AppError(
            422, "too_many_images", f"Максимум {MAX_IMAGES} фото, надіслано {len(files)}"
        )
    prepared = []
    for i, file in enumerate(files):
        raw = await file.read()
        # Pillow decoding is CPU work: off the event loop.
        name = file.filename or f"фото {i + 1}"
        prepared.append(await asyncio.to_thread(prepare_image, raw, name))
    return prepared


@router.post(
    "/checks",
    response_model=CheckOut,
    responses=ERROR_RESPONSES,
    summary="Перевірити етикетку за фото",
)
async def create_check(
    request: Request,
    images: Annotated[
        list[UploadFile],
        File(description="1–4 фото упаковки (JPEG/PNG/WebP, ≤ 10 МБ): фронт, склад, таблиця"),
    ],
    spec: Annotated[
        str | None,
        Form(
            description="Необов'язково: рецептура (ProductSpec) JSON-рядком. Без неї повноту "
            "алергенів не перевірити — вердикт не буде pass.",
            examples=[SPEC_EXAMPLE],
        ),
    ] = None,
) -> CheckOut:
    """Модель лише переносить текст з фото в структуру; правила і вердикт — у коді.

    Вердикт: `fail` > `needs_review` > `incomplete` > `pass`. Помилка моделі ніколи не дає
    вердикту: перевірка зберігається зі `status=error`, відповідь — `{"error": {...}}`.
    """
    parsed_spec = parse_spec(spec)  # before any model call: a bad recipe costs nothing
    prepared = await read_images(images)
    pool = request.app.state.pool
    vision = request.app.state.vision
    settings = get_settings()
    started = time.monotonic()
    try:
        run = await run_check(pool, vision, prepared, parsed_spec, settings.vision_deadline_seconds)
    except VisionError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        check_id = await save_error(pool, prepared, parsed_spec, vision, exc, duration_ms)
        raise AppError(
            exc.status_code, exc.code, f"{exc.message} (перевірка {check_id} збережена з помилкою)"
        ) from None
    return await save_check(pool, prepared, parsed_spec, run)


@router.get("/checks/{check_id}", response_model=CheckOut, responses={404: ERROR_RESPONSES[404]})
async def get_check(request: Request, check_id: int) -> CheckOut:
    """Збережена перевірка, зокрема та, що завершилась помилкою моделі (`status=error`)."""
    check = await load_check(request.app.state.pool, check_id)
    if check is None:
        raise AppError(404, "not_found", f"Перевірку {check_id} не знайдено")
    return check
