from docassist.loader import Page
from docassist.search import Index, split_pages, tokens


def test_word_forms_match():
    assert set(tokens("гарантии")) & set(tokens("Гарантия на детали"))
    assert tokens("Ёлка") == tokens("елка")
    assert tokens("дисплей") == tokens("дисплея") == tokens("дисплеем")
    assert tokens("как и что") == []


def test_best_fragment_by_meaning(library):
    top = lambda q: library.index.search(q, top=1)[0][0]  # noqa: E731
    assert top("Какая гарантия на детали?").page == 3
    assert top("Сколько стоит диагностика при отказе от ремонта?").page == 1
    assert top("Как вернуть деньги?").source == "Регламент возвратов.docx"
    assert top("Во сколько работаете в субботу?").source == "Памятка приёмщику.txt"


def test_nothing_in_common(library):
    assert library.index.search("пароль wifi") == []


def test_chunks_overlap_and_limit():
    text = " ".join(f"Предложение номер {i} про гарантию." for i in range(60))
    chunks = split_pages([Page("a.txt", None, text)], limit=200)
    assert len(chunks) > 5
    assert all(len(c.text) <= 260 for c in chunks)
    # последнее предложение фрагмента повторяется в начале следующего
    last = chunks[0].text.split(". ")[-1]
    assert chunks[1].text.startswith(last.rstrip("."))


def test_empty_index():
    assert Index([]).search("что угодно") == []
