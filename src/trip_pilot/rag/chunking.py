"""Разбор Markdown-документов базы знаний на фрагменты."""

import re
from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(frozen=True)
class KnowledgeChunk:
    """Фрагмент документа для полнотекстового поиска."""

    heading_path: str | None
    content: str
    meta: dict[str, Any]


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Разобрать YAML в начале Markdown-файла."""
    content = content.removeprefix("\ufeff")

    match = re.match(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)", content, re.DOTALL)

    if not match:
        raise ValueError("Не найден YAML frontmatter")

    metadata = yaml.safe_load(match.group(1))
    if not isinstance(metadata, dict):
        raise ValueError("YAML frontmatter должен быть словарём")

    required = {"title", "doc_type", "destination", "months", "tags", "source"}
    missing = required - metadata.keys()
    if missing:
        raise ValueError(f"В frontmatter отсутствуют поля: {', '.join(sorted(missing))}")

    if not isinstance(metadata["months"], list):
        raise ValueError("Поле months должно быть списком")

    if not isinstance(metadata["tags"], list):
        raise ValueError("Поле tags должно быть списком")

    for field in ("title", "doc_type", "source"):
        if not isinstance(metadata[field], str) or not metadata[field].strip():
            raise ValueError(f"Поле {field} должно быть непустой строкой")

    destination = metadata["destination"]
    if destination is not None and (
        not isinstance(destination, str) or not destination.strip()
    ):
        raise ValueError("Поле destination должно быть строкой или null")

    body = content[match.end():].strip()
    return metadata, body


def split_into_chunks(
    title: str,
    body: str,
    months: list[int],
    tags: list[str],
) -> list[KnowledgeChunk]:
    """Разделить текст по заголовкам второго уровня."""
    meta = {"months": months, "tags": tags}
    heading_pattern = re.compile(r"(?m)^##\s+(.+?)\s*$")
    matches = list(heading_pattern.finditer(body))
    chunks: list[KnowledgeChunk] = []

    # Сохраняем текст перед первым заголовком, если он есть.
    intro = body[:matches[0].start()].strip() if matches else body.strip()
    if intro:
        chunks.append(
            KnowledgeChunk(
                heading_path=title,
                content=intro,
                meta=meta,
            )
        )

    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        section_body = body[start:end].strip()

        if not section_body:
            continue

        chunks.append(
            KnowledgeChunk(
                heading_path=f"{title} › {heading}",
                # Заголовок входит в текст для полнотекстового поиска.
                content=f"{heading}\n\n{section_body}",
                meta=meta,
            )
        )

    if not chunks and body:
        chunks.append(
            KnowledgeChunk(
                heading_path=title,
                content=body,
                meta=meta,
            )
        )

    return chunks
