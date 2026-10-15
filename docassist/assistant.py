"""База документов и ответ на вопрос по ней со ссылками на источник."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .llm import LLM
from .loader import SUPPORTED, Page, UnreadableDocument, read_document
from .search import Chunk, Index, split_pages

log = logging.getLogger(__name__)

NO_ANSWER = "НЕТ_ОТВЕТА"
NOT_FOUND_TEXT = "В документах ответа нет. Уточните вопрос или спросите сотрудника."

SYSTEM_PROMPT = f"""Ты — помощник, который отвечает на вопросы только по документам компании.
Тебе дают пронумерованные фрагменты документов и вопрос.
Правила:
- отвечай по-русски одним-тремя полными предложениями, обычным текстом без разметки;
- бери факты только из фрагментов, ничего не додумывай: цифры, сроки и условия — ровно как в тексте;
- после каждого факта ставь номер фрагмента в квадратных скобках, например [2];
- если во фрагментах нет ответа на вопрос, ответь одним словом {NO_ANSWER}."""

_CITE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


@dataclass(frozen=True)
class Source:
    name: str
    page: int | None

    def label(self) -> str:
        return f"{self.name}, стр. {self.page}" if self.page else self.name


@dataclass
class Answer:
    text: str
    sources: list[Source] = field(default_factory=list)
    found: bool = True


class Library:
    """Папка с документами и поисковый индекс по ней."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)
        self.pages: dict[str, list[Page]] = {}
        self.index = Index([])
        self.reload()

    def reload(self) -> None:
        pages = {}
        for path in sorted(self.folder.iterdir()):
            if path.suffix.lower() not in SUPPORTED:
                continue
            try:
                pages[path.name] = read_document(path)
            except UnreadableDocument as e:
                log.warning("skip %s: %s", path.name, e)
        self._swap(pages)

    def add(self, path: Path) -> list[Page]:
        """Читает новый файл; не читается — файл убирается и ошибка идёт выше."""
        try:
            doc = read_document(path)
        except UnreadableDocument:
            # файл с тем же именем мог заменить прежний — убираем и его из поиска
            path.unlink(missing_ok=True)
            self._swap({k: v for k, v in self.pages.items() if k != path.name})
            raise
        self._swap({**self.pages, path.name: doc})
        return doc

    def remove(self, name: str) -> bool:
        if name not in self.pages:
            return False
        (self.folder / name).unlink(missing_ok=True)
        self._swap({k: v for k, v in self.pages.items() if k != name})
        return True

    def _swap(self, pages: dict[str, list[Page]]) -> None:
        # новый индекс собирается целиком и подменяется одной операцией: вопрос,
        # который идёт в это время, дочитает старый
        chunks = [c for doc in pages.values() for c in split_pages(doc)]
        self.pages, self.index = pages, Index(chunks)


class Assistant:
    def __init__(self, library: Library, llm: LLM, fragments: int = 5):
        self.library = library
        self.llm = llm
        self.fragments = fragments

    def ask(self, question: str) -> Answer:
        hits = self.library.index.search(question, top=self.fragments)
        if not hits:
            # ни одного общего слова с документами — модель не зовём
            return Answer(NOT_FOUND_TEXT, found=False)
        chunks = [chunk for chunk, _ in hits]
        reply = self.llm.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _prompt(question, chunks)},
            ]
        )
        if NO_ANSWER in reply:
            return Answer(NOT_FOUND_TEXT, found=False)
        return _with_sources(_plain(reply), chunks)


def _prompt(question: str, chunks: list[Chunk]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        where = Source(c.source, c.page).label()
        parts.append(f"[{i}] ({where})\n{c.text}")
    return "Фрагменты:\n\n" + "\n\n".join(parts) + f"\n\nВопрос: {question}"


def _with_sources(reply: str, chunks: list[Chunk]) -> Answer:
    """Номера фрагментов в ответе → номера источников по порядку.

    Несколько фрагментов одной страницы — один источник; номер, которого не
    было среди фрагментов, выбрасывается.
    """
    sources: list[Source] = []

    def renumber(m: re.Match) -> str:
        numbers = []
        for raw in m.group(1).split(","):
            i = int(raw)
            if not 1 <= i <= len(chunks):
                continue
            src = Source(chunks[i - 1].source, chunks[i - 1].page)
            if src not in sources:
                sources.append(src)
            n = sources.index(src) + 1
            if n not in numbers:
                numbers.append(n)
        return "[" + ", ".join(map(str, numbers)) + "]" if numbers else ""

    text = _CITE.sub(renumber, reply)
    # «[1][2]» про два фрагмента одной страницы после перенумерации стало бы «[1][1]»
    text = re.sub(r"(\[[\d, ]+\])(?:[ \t]*\1)+", r"\1", text)
    text = re.sub(r"[ \t]+([.,;:])", r"\1", re.sub(r"[ \t]{2,}", " ", text)).strip()
    return Answer(text, sources)


def _plain(text: str) -> str:
    """Убирает разметку, которую модели ставят вопреки просьбе."""
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), text)
    # только пробелы и табы: \s захватил бы переводы строк и склеил абзацы
    text = re.sub(r"^[ \t]*#+[ \t]*", "", text, flags=re.M)
    return re.sub(r"^[ \t]*[*•][ \t]+", "— ", text, flags=re.M)
