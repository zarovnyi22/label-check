from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import check_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    db = await check_db(request.app.state.pool)
    ok = db == "ok"
    settings = get_settings()
    # Providers as configured: the vision client itself arrives in B3a.
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "ok" if ok else "degraded",
            "db": db,
            "vision_provider": settings.vision_provider,
            "vision_fallback_provider": settings.vision_fallback_provider or None,
        },
    )
