from docassist.loader import Page
from docassist.search import Chunk, Index, split_pages, tokens


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


def test_duration_question_finds_term(library):
    """«Сколько длится» и «сколько ждать» находят пункт про срок ремонта."""
    assert tokens("длится") == tokens("срок") == tokens("ждать")
    for q in ("Сколько длится ремонт?", "Сколько ждать ремонт?"):
        pages = [chunk.page for chunk, _ in library.index.search(q)]
        assert 2 in pages, q


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


def test_long_sentences_no_duplicate_chunk():
    """Фрагмент из одного длинного предложения не должен целиком повторяться в следующем."""
    a, b, c = ("А" * 400 + ".", "Б" * 400 + ".", "В" * 400 + ".")
    chunks = split_pages([Page("a.txt", None, f"{a} {b} {c}")], limit=700)
    texts = [ch.text for ch in chunks]
    assert texts == [a, b, c]


def test_chunks_keep_page_and_source():
    pages = [Page("d.pdf", 1, "Первая страница."), Page("d.pdf", 2, "Вторая страница.\nЕщё строка.")]
    chunks = split_pages(pages)
    assert [(c.source, c.page) for c in chunks] == [("d.pdf", 1), ("d.pdf", 2)]
    assert chunks[1].text == "Вторая страница. Ещё строка."


def test_tokens_latin_digits_and_stopwords():
    assert tokens("Repairs phones") == tokens("repair phone")
    assert "4500" in tokens("цена 4500 руб")
    assert tokens("") == []


def test_ranking_prefers_rarer_word():
    index = Index(
        [
            Chunk("a.txt", None, "Ремонт телефона. Ремонт планшета."),
            Chunk("b.txt", None, "Ремонт ноутбука и замена клавиатуры."),
            Chunk("c.txt", None, "Ремонт часов."),
        ]
    )
    hits = index.search("замена клавиатуры при ремонте")
    assert hits[0][0].source == "b.txt"
    assert [s for _, s in hits] == sorted((s for _, s in hits), reverse=True)
    assert len(index.search("ремонт", top=2)) == 2
    assert index.search("и в на") == []


def test_blank_page_gives_no_chunks():
    assert split_pages([Page("a.txt", None, " \n\n "), Page("b.txt", None, "Текст.")]) == [
        Chunk("b.txt", None, "Текст.")
    ]


def test_index_of_stopword_chunks():
    # ни одного значимого слова во всех фрагментах: средняя длина 0, поиск не должен делить на ноль
    index = Index([Chunk("a.txt", None, "и в на"), Chunk("b.txt", None, "как же так")])
    assert index.search("гарантия и в на") == []
