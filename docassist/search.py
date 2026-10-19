"""Нарезка документов на фрагменты и поиск по ним (BM25 с учётом словоформ).

Поиск работает без сети и без платных моделей: «гарантии», «гарантийный» и
«гарантия» сводятся к одной основе, поэтому вопрос своими словами находит
нужный пункт договора.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

import snowballstemmer

from .loader import Page

CHUNK_CHARS = 700  # фрагмент — пара абзацев: модели хватает смысла, лишнего мало
_ru = snowballstemmer.stemmer("russian")
_en = snowballstemmer.stemmer("english")
_WORD = re.compile(r"[a-zа-я0-9]+")
_SENTENCE = re.compile(r"(?<=[.!?…])\s+|\n+")
STOP = set(
    "и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было "
    "вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас "
    "нибудь опять уж вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя их "
    "чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой "
    "совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при "
    "наконец два об другой хоть после над больше тот через эти нас про всего них какая много разве "
    "три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда "
    "конечно всю между сколько каком какие какое ваш наш".split()
)

# вопрос «сколько длится ремонт» и пункт «срок ремонта» не делят ни одного слова — сводим к одной основе
SYNONYMS = {stem: "срок" for stem in ("длит", "длительн", "продолжительн", "ждат", "ждем", "ждут")}


def tokens(text: str) -> list[str]:
    words = _WORD.findall(text.lower().replace("ё", "е"))
    out = []
    for w in words:
        if w in STOP:
            continue
        if re.search("[а-я]", w):
            stem = _ru.stemWord(w)
            # снежок режет «дисплей» до «диспл», а «дисплея» до «диспле» — сводим к одному
            if len(stem) > 3 and stem.endswith("е"):
                stem = stem[:-1]
        else:
            stem = _en.stemWord(w)
        out.append(SYNONYMS.get(stem, stem))
    return out


@dataclass(frozen=True)
class Chunk:
    source: str
    page: int | None
    text: str


def split_pages(pages: list[Page], limit: int = CHUNK_CHARS) -> list[Chunk]:
    """Режет по предложениям, соседние фрагменты делят одно предложение — чтобы
    мысль на стыке не потерялась."""
    chunks = []
    for page in pages:
        sentences = [s.strip() for s in _SENTENCE.split(page.text) if s.strip()]
        current: list[str] = []
        for sentence in sentences:
            if current and len(" ".join(current)) + len(sentence) > limit:
                chunks.append(Chunk(page.source, page.page, " ".join(current)))
                # фрагмент из одного предложения не переносим: следующий целиком его повторил бы
                current = current[-1:] if len(current) > 1 else []
            current.append(sentence)
        if current:
            chunks.append(Chunk(page.source, page.page, " ".join(current)))
    return chunks


@dataclass
class Index:
    chunks: list[Chunk]
    k1: float = 1.5
    b: float = 0.75
    _docs: list[Counter] = field(init=False, repr=False)
    _idf: dict[str, float] = field(init=False, repr=False)
    _avg: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._docs = [Counter(tokens(c.text)) for c in self.chunks]
        n = len(self._docs)
        df: Counter = Counter()
        for doc in self._docs:
            df.update(doc.keys())
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self._avg = sum(sum(d.values()) for d in self._docs) / n if n else 0.0

    def search(self, query: str, top: int = 5) -> list[tuple[Chunk, float]]:
        terms = set(tokens(query))
        scored = []
        for chunk, doc in zip(self.chunks, self._docs, strict=True):
            length = sum(doc.values())
            score = 0.0
            for t in terms:
                f = doc.get(t)
                if f:
                    norm = f + self.k1 * (1 - self.b + self.b * length / self._avg)
                    score += self._idf[t] * f * (self.k1 + 1) / norm
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top]
