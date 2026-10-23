"""Все ORM-модели проекта. Этот модуль импортирует migrations/env.py, чтобы Alembic видел
полную схему. Новый модуль с моделями добавляется сюда через лида.
"""

from trip_pilot.adapters.db import chat, inventory, knowledge, orders, reference  # noqa: F401
from trip_pilot.adapters.db.base import Base

__all__ = ["Base"]
