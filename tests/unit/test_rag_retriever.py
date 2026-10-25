"""Тесты полнотекстового поиска RAG."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from trip_pilot.rag.retriever import search


def test_search_returns_empty_for_blank_query():
    """Пустой запрос не должен обращаться к базе данных."""
    session = MagicMock()
    session.execute = AsyncMock()

    result = asyncio.run(search(session, "   "))

    assert result == []
    session.execute.assert_not_awaited()


def test_search_returns_empty_for_non_positive_limit():
    """Неположительный лимит не требует запроса к БД."""
    session = MagicMock()
    session.execute = AsyncMock()

    result = asyncio.run(search(session, "отдых с детьми", limit=0))

    assert result == []
    session.execute.assert_not_awaited()


def test_search_executes_query_with_filters():
    """Поиск учитывает направление и тип документа."""
    session = MagicMock()
    db_result = MagicMock()
    db_result.all.return_value = []
    session.execute = AsyncMock(return_value=db_result)

    result = asyncio.run(
        search(
            session,
            "отдых с детьми",
            destination="antalya",
            doc_type="destination",
            limit=3,
        )
    )

    assert result == []
    session.execute.assert_awaited_once()

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": False}))

    assert "websearch_to_tsquery" in sql
    assert "ts_rank_cd" in sql
    assert "kb_chunk" in sql
    assert "kb_document" in sql
    assert "destination" in sql
    assert "LIMIT" in sql.upper()
