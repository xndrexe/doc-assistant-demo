"""Чтение документов: PDF по страницам, Word и текст — целиком."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from pypdf import PdfReader

SUPPORTED = (".pdf", ".docx", ".txt", ".md")


class UnreadableDocument(Exception):
    """Файл не читается или в нём нет текста (например, скан без распознавания)."""


@dataclass(frozen=True)
class Page:
    source: str  # имя файла, его видит пользователь в ссылке на источник
    page: int | None  # номер страницы PDF; у Word и текста страниц нет
    text: str


def read_document(path: Path) -> list[Page]:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise UnreadableDocument(f"формат {suffix or 'без расширения'} не поддерживается")
    try:
        if suffix == ".pdf":
            pages = _read_pdf(path)
        elif suffix == ".docx":
            pages = [Page(path.name, None, _read_docx(path))]
        else:
            pages = [Page(path.name, None, path.read_text(encoding="utf-8", errors="replace"))]
    except UnreadableDocument:
        raise
    except Exception as e:  # битый файл любого формата — одна понятная ошибка
        raise UnreadableDocument(f"файл не открылся: {e}") from e
    pages = [p for p in pages if p.text.strip()]
    if not pages:
        raise UnreadableDocument("в файле нет текста — похоже на скан")
    return pages


def _read_pdf(path: Path) -> list[Page]:
    reader = PdfReader(str(path))
    # строки PDF переносятся посреди фразы — склеиваем всю страницу в один абзац
    return [Page(path.name, i, _squash(page.extract_text() or "")) for i, page in enumerate(reader.pages, 1)]


def _read_docx(path: Path) -> str:
    doc = Document(str(path))
    lines = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(line for line in lines if line.strip())


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
