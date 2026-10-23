import json
import logging
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from trip_pilot.adapters.db.reference import Destination

log = logging.getLogger(__name__)


async def seed_reference(session: AsyncSession, reference_dir: Path) -> None:
    """Справочник направлений. Существующие slug не трогаем: повторный запуск безопасен."""
    rows = json.loads((reference_dir / "destinations.json").read_text(encoding="utf-8"))
    result = await session.execute(
        insert(Destination).values(rows).on_conflict_do_nothing(index_elements=["slug"])
    )
    log.info("Направления: добавлено %d из %d", result.rowcount, len(rows))
