import logging
import sys


def setup_logging(level: str) -> None:
    """Логи в stdout: их видно в `docker compose logs`."""
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
