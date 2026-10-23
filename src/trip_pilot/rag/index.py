import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)


async def build_index(session: AsyncSession, knowledge_dir: Path) -> None:
    """Шаг bootstrap для RAG-индекса: data/knowledge/*.md → kb_document / kb_chunk.

    Заглушка этапа 0: таблицы уже созданы миграцией 0001, разбор документов на фрагменты
    и эмбеддинги появятся на этапе 3.
    """
    docs = sorted(knowledge_dir.glob("*.md")) if knowledge_dir.is_dir() else []
    log.info("RAG: документов в %s: %d, индексация будет на этапе 3", knowledge_dir, len(docs))
