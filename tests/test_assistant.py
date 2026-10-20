import threading

import pytest

from docassist import assistant as mod
from docassist.assistant import (
    NO_ANSWER,
    NOT_FOUND_TEXT,
    Assistant,
    Library,
    Source,
    _plain,
    _prompt,
    _with_sources,
)
from docassist.llm import LLMError
from docassist.search import Chunk


def test_answer_with_sources(assistant, llm):
    llm.reply = "Гарантия на детали — **6 месяцев** [1]. На работы — 90 дней [1, 1]."
    answer = assistant.ask("Какая гарантия на детали?")
    assert answer.found
    assert answer.text == "Гарантия на детали — 6 месяцев [1]. На работы — 90 дней [1]."
    assert answer.sources == [Source("Договор на ремонт.pdf", 3)]
    system, user = llm.calls[0]
    assert NO_ANSWER in system["content"]
    assert "[1] (Договор на ремонт.pdf, стр. 3)" in user["content"]
    assert user["content"].endswith("Вопрос: Какая гарантия на детали?")


def test_sources_renumbered_in_order_of_mention(assistant, llm):
    llm.reply = "Сначала заявление [2], деньги вернут на карту [3]. Неверная ссылка [9]."
    answer = assistant.ask("Как вернуть деньги за ремонт по гарантии?")
    prompt = llm.calls[0][1]["content"]
    assert prompt.count("\n[") >= 3
    # номера в тексте идут 1, 2… по порядку упоминания, лишний [9] выброшен
    assert "[9]" not in answer.text and answer.text.endswith("Неверная ссылка.")
    assert answer.text.startswith("Сначала заявление [1]")
    assert len(answer.sources) == len({*answer.sources})


def test_model_says_no_answer(assistant, llm):
    llm.reply = NO_ANSWER
    answer = assistant.ask("Есть ли доставка в Казань?")
    assert not answer.found and answer.text == NOT_FOUND_TEXT and answer.sources == []


def test_no_hits_no_model_call(assistant, llm):
    answer = assistant.ask("пароль wifi")
    assert not answer.found and llm.calls == []


def test_answer_without_citations(assistant, llm):
    llm.reply = "С 10:00 до 18:00."
    answer = assistant.ask("Во сколько работаете в субботу?")
    assert answer.text == "С 10:00 до 18:00." and answer.sources == []


def test_model_failure_goes_up(assistant, llm):
    llm.reply = LLMError("down")
    with pytest.raises(LLMError):
        assistant.ask("Какая гарантия?")


def test_library_add_and_remove(library, tmp_path):
    new = library.folder / "Прайс.txt"
    new.write_text("Замена дисплея телефона — 4 500 рублей.", encoding="utf-8")
    pages = library.add(new)
    assert pages[0].source == "Прайс.txt" and "Прайс.txt" in library.pages
    assert library.index.search("дисплей")[0][0].source == "Прайс.txt"

    assert library.remove("Прайс.txt")
    assert not new.exists() and library.index.search("дисплей") == []
    assert not library.remove("нет такого.pdf")


def test_library_drops_unreadable_upload(library):
    bad = library.folder / "скан.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(Exception, match="не открылся"):
        library.add(bad)
    assert not bad.exists() and "скан.pdf" not in library.pages


def test_library_skips_bad_files_on_start(library):
    (library.folder / "битый.pdf").write_bytes(b"garbage")
    (library.folder / "картинка.png").write_bytes(b"\x89PNG")
    library.reload()
    assert set(library.pages) == {
        "Договор на ремонт.pdf",
        "Регламент возвратов.docx",
        "Памятка приёмщику.txt",
    }


def test_unreadable_replacement_leaves_no_ghost(library):
    """Битый файл поверх прежнего: старый текст не должен остаться в поиске без файла."""
    path = library.folder / "Памятка приёмщику.txt"
    path.write_text("  ")
    with pytest.raises(Exception, match="нет текста"):
        library.add(path)
    assert "Памятка приёмщику.txt" not in library.pages
    assert all(c.source != "Памятка приёмщику.txt" for c in library.index.chunks)


def test_plain_keeps_paragraphs():
    text = "Ответ.\n\n## Итог\nтекст __важно__\n\n * пункт\n• ещё"
    assert _plain(text) == "Ответ.\n\nИтог\nтекст важно\n\n— пункт\n— ещё"


def test_with_sources_edge_cases():
    chunks = [Chunk("a.pdf", 1, "x"), Chunk("a.pdf", 1, "y"), Chunk("b.docx", None, "z")]
    # два фрагмента одной страницы — один источник; [0] и [4] вне диапазона
    answer = _with_sources("Раз [2, 1] два [3,4] три [0] .", chunks)
    assert answer.text == "Раз [1] два [2] три."
    assert answer.sources == [Source("a.pdf", 1), Source("b.docx", None)]
    assert Source("b.docx", None).label() == "b.docx"
    # соседние ссылки на одну страницу схлопываются
    assert _with_sources("Цена [1][2], срок [1] [2] [3].", chunks).text == "Цена [1], срок [1] [2]."


def test_fragments_limit_passed_to_search(library, llm):
    Assistant(library, llm, fragments=2).ask("Какая гарантия на ремонт и детали?")
    prompt = llm.calls[0][1]["content"]
    assert "[2] (" in prompt and "[3] (" not in prompt


def test_library_ignores_other_files_and_creates_folder(tmp_path):
    folder = tmp_path / "новая" / "папка"
    lib = Library(folder)
    assert folder.is_dir() and lib.pages == {} and lib.index.search("гарантия") == []
    (folder / "заметка.MD").write_text("# Гарантия\nГарантия 30 дней.", encoding="utf-8")
    (folder / "подпапка").mkdir()
    lib.reload()
    assert list(lib.pages) == ["заметка.MD"]


def test_only_bad_citations_is_no_answer(assistant, llm):
    """От ответа «[9]» после чистки ничего не остаётся — пустой текст не отдаём."""
    llm.reply = "[9] **[7]**"
    answer = assistant.ask("Какая гарантия на детали?")
    assert not answer.found and answer.text == NOT_FOUND_TEXT and answer.sources == []


def test_unreadable_external_file_left_in_place(library, tmp_path):
    """Файл не из папки базы при неудаче не удаляется — он чужой."""
    outside = tmp_path / "мой.pdf"
    outside.write_bytes(b"not a pdf")
    with pytest.raises(Exception, match="не открылся"):
        library.add(outside)
    assert outside.exists() and not (library.folder / "мой.pdf").exists()
    assert "мой.pdf" not in library.pages


def test_external_file_moved_into_folder(library, tmp_path):
    outside = tmp_path / "Прайс.md"
    outside.write_text("Чистка ноутбука — 1 200 рублей.", encoding="utf-8")
    library.add(outside)
    assert not outside.exists() and (library.folder / "Прайс.md").exists()
    assert library.index.search("чистка ноутбука")[0][0].source == "Прайс.md"


def test_prompt_label_without_page():
    prompt = _prompt("Вопрос?", [Chunk("a.txt", None, "текст"), Chunk("b.pdf", 2, "ещё")])
    assert prompt == "Фрагменты:\n\n[1] (a.txt)\nтекст\n\n[2] (b.pdf, стр. 2)\nещё\n\nВопрос: Вопрос?"


def test_plain_leaves_inline_symbols():
    # решётка и звёздочка посреди строки — не разметка
    assert _plain("Тариф #2 стоит 5*3 рубля.") == "Тариф #2 стоит 5*3 рубля."
    assert _plain("**без пары") == "**без пары"


def test_remove_during_add_does_not_resurrect(library, monkeypatch):
    """Удаление во время сборки индекса для загрузки: удалённый документ не должен вернуться в поиск."""
    target = "Памятка приёмщику.txt"
    real_index = mod.Index
    fired = []

    def slow_index(chunks):
        if not fired:
            fired.append(True)
            # администратор удаляет документ ровно в момент сборки индекса для новой загрузки
            other = threading.Thread(target=library.remove, args=(target,))
            other.start()
            other.join(timeout=0.3)
            fired.append(other)
        return real_index(chunks)

    monkeypatch.setattr(mod, "Index", slow_index)
    new = library.folder / "Прайс.txt"
    new.write_text("Замена дисплея телефона — 4 500 рублей.", encoding="utf-8")
    library.add(new)
    fired[1].join()

    assert target not in library.pages
    assert all(c.source != target for c in library.index.chunks)
    assert "Прайс.txt" in library.pages
