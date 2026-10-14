import pytest

from docassist.loader import UnreadableDocument, read_document
from tests.conftest import SAMPLES


def test_pdf_by_pages():
    pages = read_document(SAMPLES / "Договор на ремонт.pdf")
    assert [p.page for p in pages] == [1, 2, 3]
    assert "6 месяцев" in pages[2].text
    # переносы строк PDF склеены — фраза ищется целиком
    assert "на установленные новые детали" in pages[2].text


def test_docx_and_txt():
    (docx,) = read_document(SAMPLES / "Регламент возвратов.docx")
    assert docx.page is None and "service@technodom.example" in docx.text
    (txt,) = read_document(SAMPLES / "Памятка приёмщику.txt")
    assert "суббота с 10:00 до 18:00" in txt.text


def test_unreadable(tmp_path):
    empty = tmp_path / "скан.pdf"
    empty.write_bytes(b"%PDF-1.4 broken")
    with pytest.raises(UnreadableDocument):
        read_document(empty)
    blank = tmp_path / "пусто.txt"
    blank.write_text("  \n")
    with pytest.raises(UnreadableDocument, match="нет текста"):
        read_document(blank)
    with pytest.raises(UnreadableDocument, match="не поддерживается"):
        read_document(tmp_path / "таблица.xlsx")
