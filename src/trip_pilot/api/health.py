import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

log = logging.getLogger(__name__)
router = APIRouter()


async def database_ok(request: Request) -> bool:
    async def ping() -> None:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(ping(), timeout=2)
        return True
    except Exception as exc:  # health должен ответить при любой ошибке БД
        log.warning("health: БД недоступна: %r", exc)
        return False


@router.get("/health")
async def health(db_ok: Annotated[bool, Depends(database_ok)]) -> JSONResponse:
    if db_ok:
        return JSONResponse({"status": "ok"})
    return JSONResponse({"status": "degraded", "db": "unavailable"}, status_code=503)
