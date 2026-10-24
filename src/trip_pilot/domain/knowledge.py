from pydantic import BaseModel


class KnowledgeHit(BaseModel):
    """Найденный фрагмент базы знаний. Знания, а не факты: цен и расписаний здесь нет."""

    text: str
    title: str
    heading_path: str | None = None  # «Анталья › С детьми»
    source: str  # wikivoyage | synthetic | …
    score: float
