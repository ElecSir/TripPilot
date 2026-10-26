"""Справочник направлений: загрузка из data/reference/destinations.json."""

import json
import logging
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from trip_pilot.adapters.db.reference import Destination

log = logging.getLogger(__name__)


async def seed_reference(session: AsyncSession, reference_dir: Path) -> None:
    """Новые направления добавляются; у существующих обновляются теги и тёплые месяцы.

    Остальные поля существующих slug не трогаем. Повторный запуск безопасен.
    """
    rows = json.loads((reference_dir / "destinations.json").read_text(encoding="utf-8"))
    statement = insert(Destination).values(rows)
    statement = statement.on_conflict_do_update(
        index_elements=["slug"],
        set_={
            "tags": statement.excluded.tags,
            "warm_months": statement.excluded.warm_months,
        },
    )
    await session.execute(statement)
    log.info("Направления: обработано %d", len(rows))
