"""Общая база ORM-моделей.

Модели каждой зоны лежат в своём модуле (chat, orders, knowledge, reference, inventory),
полный список собирает models.py. Наружу из adapters/db модели не выходят: репозитории
отдают доменные модели. Схема меняется только миграциями Alembic, не руками в pgAdmin.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
