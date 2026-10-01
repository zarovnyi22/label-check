from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import check_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    db = await check_db(request.app.state.pool)
    ok = db == "ok"
    # The providers of the client the app actually runs with (tests may put a FakeVision
    # there); without the lifespan, the configured ones.
    vision = getattr(request.app.state, "vision", None)
    settings = get_settings()
    provider = vision.provider if vision else settings.vision_provider
    fallback = vision.fallback_provider if vision else settings.vision_fallback_provider or None
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "ok" if ok else "degraded",
            "db": db,
            "vision_provider": provider,
            "vision_fallback_provider": fallback,
        },
    )
