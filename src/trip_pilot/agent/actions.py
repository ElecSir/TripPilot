"""Действия пользователя, которые приходят в агента не текстом, а кнопкой в UI. Контракт лида."""

from typing import Literal

from pydantic import BaseModel


class SelectPackage(BaseModel):
    type: Literal["select_package"] = "select_package"
    package_id: str


# Новые действия добавляются сюда и становятся объединением с discriminator="type".
AgentAction = SelectPackage
