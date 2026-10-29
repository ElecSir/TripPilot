"""Тесты полнотекстового поиска RAG."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trip_pilot.ports import LLMUnavailable
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

    disabled_llm = MagicMock()
    disabled_llm.enabled = False

    with patch(
        "trip_pilot.rag.retriever._get_llm",
        return_value=disabled_llm,
    ):
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
    assert session.execute.await_count == 2

    statement = session.execute.await_args_list[0].args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": False}))

    assert "websearch_to_tsquery" in sql
    assert "ts_rank_cd" in sql
    assert "kb_chunk" in sql
    assert "kb_document" in sql
    assert "destination" in sql
    assert "LIMIT" in sql.upper()



def _make_db_row(chunk_id, *, score=0.0, distance=0.0):
    """Создать имитацию строки результата PostgreSQL."""
    chunk = SimpleNamespace(
        id=chunk_id,
        content=f"Фрагмент {chunk_id}",
        heading_path="Почему ехать",
    )

    row = MagicMock()
    row.__getitem__.return_value = chunk
    row.document_title = f"Документ {chunk_id}"
    row.destination = "antalya"
    row.source = f"source-{chunk_id}"
    row.score = score
    row.distance = distance

    return row


def _make_db_result(rows):
    """Создать имитацию результата session.execute()."""
    result = MagicMock()
    result.all.return_value = rows
    return result


def test_search_merges_results_with_rrf():
    """RRF объединяет выдачи и повышает фрагмент, найденный обоими способами."""
    session = MagicMock()

    text_rows = [
        _make_db_row(1, score=0.9),
        _make_db_row(2, score=0.8),
    ]
    vector_rows = [
        _make_db_row(2, distance=0.1),
        _make_db_row(3, distance=0.2),
    ]

    session.execute = AsyncMock(
        side_effect=[
            _make_db_result(text_rows),
            _make_db_result(vector_rows),
        ]
    )

    llm = MagicMock()
    llm.enabled = True
    llm.embed = AsyncMock(return_value=[[0.1] * 1024])

    with patch(
        "trip_pilot.rag.retriever._get_llm",
        return_value=llm,
    ):
        result = asyncio.run(search(session, "отдых у моря", limit=5))

    # Фрагмент 2 найден обоими способами и должен оказаться первым.
    assert [hit.chunk.id for hit in result] == [2, 1, 3]

    # RRF использует позиции в выдаче, а не исходные score/distance.
    assert result[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert result[1].score == pytest.approx(1 / 61)
    assert result[2].score == pytest.approx(1 / 62)

    # Повторяющиеся фрагменты не дублируются.
    assert len({hit.chunk.id for hit in result}) == len(result)

    llm.embed.assert_awaited_once_with(["отдых у моря"])
    assert session.execute.await_count == 2


def test_search_rrf_respects_limit():
    """Гибридный поиск возвращает не больше указанного количества фрагментов."""
    session = MagicMock()

    text_rows = [
        _make_db_row(1),
        _make_db_row(2),
        _make_db_row(3),
    ]
    vector_rows = [
        _make_db_row(4),
        _make_db_row(5),
    ]

    session.execute = AsyncMock(
        side_effect=[
            _make_db_result(text_rows),
            _make_db_result(vector_rows),
        ]
    )

    llm = MagicMock()
    llm.enabled = True
    llm.embed = AsyncMock(return_value=[[0.1] * 1024])

    with patch(
        "trip_pilot.rag.retriever._get_llm",
        return_value=llm,
    ):
        result = asyncio.run(search(session, "отдых", limit=2))

    assert len(result) == 2
    assert len({hit.chunk.id for hit in result}) == 2


def test_search_falls_back_to_text_when_embedding_fails():
    """Ошибка embedding не должна ломать полнотекстовый поиск."""
    session = MagicMock()

    text_row = _make_db_row(1, score=0.9)
    db_result = _make_db_result([text_row])
    session.execute = AsyncMock(return_value=db_result)

    llm = MagicMock()
    llm.enabled = True
    llm.embed = AsyncMock(
        side_effect=LLMUnavailable("Embedding API недоступен")
    )

    with patch(
        "trip_pilot.rag.retriever._get_llm",
        return_value=llm,
    ):
        result = asyncio.run(
            search(session, "отдых у моря", limit=5)
        )

    assert len(result) == 1
    assert result[0].chunk.id == 1
    assert result[0].score == pytest.approx(0.9)

    llm.embed.assert_awaited_once_with(["отдых у моря"])
    # Векторный SQL-запрос не должен выполняться.
    assert session.execute.await_count == 1