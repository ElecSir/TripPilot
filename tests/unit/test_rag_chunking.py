"""Тесты разбиения документов базы знаний."""

from pathlib import Path

import pytest

from trip_pilot.rag.chunking import parse_frontmatter, split_into_chunks


def test_parse_frontmatter() -> None:
    content = """---
title: Анталья
doc_type: guide
destination: antalya
months: [5, 6, 7]
tags: [sea, kids]
source: synthetic
---
## С детьми

Подходит для семейного отдыха.
"""
    metadata, body = parse_frontmatter(content)

    assert metadata["title"] == "Анталья"
    assert metadata["destination"] == "antalya"
    assert metadata["months"] == [5, 6, 7]
    assert metadata["tags"] == ["sea", "kids"]
    assert "## С детьми" in body


def test_parse_frontmatter_without_header_raises_error() -> None:
    with pytest.raises(ValueError, match="frontmatter"):
        parse_frontmatter("Обычный текст без YAML")


def test_split_into_chunks() -> None:
    body = """Вводный текст.

## Почему ехать

Море и пляжи.

## С детьми

Семейные развлечения.
"""
    chunks = split_into_chunks(
        title="Анталья",
        body=body,
        months=[5, 6, 7],
        tags=["sea", "kids"],
    )

    assert len(chunks) == 3
    assert chunks[0].heading_path == "Анталья"
    assert chunks[1].heading_path == "Анталья › Почему ехать"
    assert chunks[2].heading_path == "Анталья › С детьми"
    assert "Семейные развлечения" in chunks[2].content
    assert chunks[2].meta == {"months": [5, 6, 7], "tags": ["sea", "kids"]}


def test_all_knowledge_files_have_valid_frontmatter() -> None:
    knowledge_dir = Path("data/knowledge")
    files = sorted(knowledge_dir.glob("*.md"))

    assert len(files) == 12

    for path in files:
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        assert metadata["destination"] == path.stem
        assert body
