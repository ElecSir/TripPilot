"""Протокол событий агента: API отдаёт их потоком SSE, UI и бот рисуют.

Одна строка SSE = одно событие: `data: {"type": "step", "text": "..."}`.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter


class StageEvent(BaseModel):
    type: Literal["stage"] = "stage"
    stage: str


class StepEvent(BaseModel):
    type: Literal["step"] = "step"
    text: str


class QuestionEvent(BaseModel):
    type: Literal["question"] = "question"
    text: str
    options: list[str] = []


class PlanEvent(BaseModel):
    type: Literal["plan"] = "plan"
    data: dict[str, Any]


class DeltaEvent(BaseModel):
    type: Literal["delta"] = "delta"
    text: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    text: str


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"


AgentEvent = Annotated[
    StageEvent | StepEvent | QuestionEvent | PlanEvent | DeltaEvent | ErrorEvent | DoneEvent,
    Field(discriminator="type"),
]

_adapter: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)


def to_sse(event: BaseModel) -> str:
    return f"data: {event.model_dump_json()}\n\n"


def parse_event(raw: str) -> AgentEvent:
    return _adapter.validate_json(raw)
