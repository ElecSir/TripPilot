"""Служебные команды: python -m trip_pilot.cli {bootstrap,migrate,seed}.

bootstrap запускается в docker compose одноразовым сервисом перед стартом api.
"""

import argparse
import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from trip_pilot.adapters.db.engine import create_engine, create_session_factory
from trip_pilot.config import get_settings
from trip_pilot.logs import setup_logging
from trip_pilot.rag.index import build_index
from trip_pilot.seed.reference import seed_reference

log = logging.getLogger("trip_pilot.cli")


def migrate() -> None:
    cfg = Config(str(Path("alembic.ini").resolve()))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


async def seed() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        async with create_session_factory(engine)() as session:
            await seed_reference(session, settings.data_dir / "reference")
            await build_index(session, settings.data_dir / "knowledge")
            await session.commit()
    finally:
        await engine.dispose()


def bootstrap() -> None:
    log.info("Миграции")
    migrate()
    # alembic сам вызывает asyncio.run, поэтому асинхронная часть идёт отдельно, после него
    log.info("Сидирование и RAG-индекс")
    asyncio.run(seed())
    log.info("Bootstrap завершён")


def main() -> None:
    parser = argparse.ArgumentParser(prog="trip_pilot.cli")
    parser.add_argument("command", choices=["bootstrap", "migrate", "seed"])
    args = parser.parse_args()

    setup_logging(get_settings().log_level)
    match args.command:
        case "bootstrap":
            bootstrap()
        case "migrate":
            migrate()
        case "seed":
            asyncio.run(seed())


if __name__ == "__main__":
    main()
