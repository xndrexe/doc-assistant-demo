"""Бот через настоящий диспетчер aiogram без сети: подменена только отправка в Telegram."""

from datetime import datetime

import pytest
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendChatAction, SendMessage
from aiogram.types import Chat, Message, Update

from docassist import tg
from docassist.assistant import Answer, Source
from docassist.llm import LLMError

ADMIN, GUEST = 1, 42


class FakeTelegram(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=len(self.calls), date=datetime.now(), chat=Chat(id=method.chat_id, type="private")
            )
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        raise NotImplementedError

    def texts(self):
        return [c.text for c in self.calls if isinstance(c, SendMessage)]


def update(user_id, text=None, document=None):
    message = {
        "message_id": 1,
        "date": 0,
        "chat": {"id": user_id, "type": "private"},
        "from": {"id": user_id, "is_bot": False, "first_name": "Ирина"},
    }
    if text is not None:
        message["text"] = text
        if text.startswith("/"):
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    if document is not None:
        message["document"] = document
    return Update.model_validate({"update_id": 1, "message": message})


@pytest.fixture
def chat(assistant):
    bot, dp = tg.build(assistant, "42:TEST", frozenset({ADMIN}))
    session = FakeTelegram()
    bot.session = session

    async def send(user_id, text=None, document=None):
        session.calls.clear()
        await dp.feed_update(bot, update(user_id, text, document))
        return session.texts()

    send.bot = bot
    send.session = session
    return send


async def test_start_and_docs(chat):
    (hello,) = await chat(GUEST, "/start")
    assert "Какая гарантия на детали?" in hello and "администратор" not in hello
    (hello,) = await chat(ADMIN, "/start")
    assert "добавлю его в базу" in hello
    (docs,) = await chat(GUEST, "/docs")
    assert "Договор на ремонт.pdf (3 стр.)" in docs and "Памятка приёмщику.txt" in docs


async def test_question_with_sources(chat, llm):
    llm.reply = "Гарантия на детали — 6 месяцев [1]."
    (reply,) = await chat(GUEST, "Какая гарантия на детали?")
    assert isinstance(chat.session.calls[0], SendChatAction)
    assert reply == "Гарантия на детали — 6 месяцев [1].\n\nИсточники:\n[1] Договор на ремонт.pdf, стр. 3"


async def test_model_down_polite_message(chat, llm):
    llm.reply = LLMError("502 from provider")
    (reply,) = await chat(GUEST, "Какая гарантия?")
    assert reply == tg.FAILED and "502" not in reply


def doc(name, size=1000):
    return {"file_id": "f1", "file_unique_id": "u1", "file_name": name, "file_size": size}


async def test_admin_uploads_document(chat, assistant, monkeypatch):
    async def fake_download(file, destination):
        destination.write_text("Замена дисплея телефона — 4 500 рублей.", encoding="utf-8")

    monkeypatch.setattr(chat.bot, "download", fake_download)
    (reply,) = await chat(ADMIN, document=doc("Прайс.txt"))
    assert reply == "Добавил «Прайс.txt». Документов в базе: 4."
    assert assistant.library.index.search("дисплей")[0][0].source == "Прайс.txt"

    (reply,) = await chat(ADMIN, "/remove Прайс.txt")
    assert reply.startswith("Удалил «Прайс.txt»") and "Прайс.txt" not in assistant.library.pages


async def test_upload_refusals(chat, monkeypatch):
    async def scan(file, destination):
        destination.write_bytes(b"%PDF-1.4 no text")

    monkeypatch.setattr(chat.bot, "download", scan)
    assert (await chat(GUEST, document=doc("Прайс.txt")))[0].startswith("Загружать документы может только")
    assert "PDF, Word" in (await chat(ADMIN, document=doc("фото.jpg")))[0]
    assert "больше 20 МБ" in (await chat(ADMIN, document=doc("big.pdf", 25 * 1024 * 1024)))[0]
    (reply,) = await chat(ADMIN, document=doc("скан.pdf"))
    assert reply.startswith("Не смог прочитать «скан.pdf»")
    assert (await chat(GUEST, "/remove Договор на ремонт.pdf"))[0].startswith(
        "Удалять документы может только"
    )
    assert "Такого документа нет" in (await chat(ADMIN, "/remove нет.pdf"))[0]


def test_format_without_sources():
    assert tg.format_answer(Answer("Ответа нет.", found=False)) == "Ответа нет."
    two = Answer("А [1], Б [2].", [Source("a.pdf", 2), Source("b.docx", None)])
    assert tg.format_answer(two).endswith("Источники:\n[1] a.pdf, стр. 2\n[2] b.docx")


async def test_empty_library_and_remove_without_name(tmp_path, llm):
    from docassist.assistant import Assistant, Library

    bot, dp = tg.build(Assistant(Library(tmp_path / "docs"), llm), "42:TEST", frozenset({ADMIN}))
    bot.session = session = FakeTelegram()
    await dp.feed_update(bot, update(GUEST, "/docs"))
    await dp.feed_update(bot, update(ADMIN, "/remove"))
    assert session.texts() == [
        "В базе пока нет документов.",
        "Такого документа нет. Точное имя — в списке /docs.",
    ]


async def test_upload_strips_path_from_name(chat, assistant, monkeypatch):
    saved = []

    async def fake_download(file, destination):
        saved.append(destination)
        destination.write_text("Скидка пенсионерам 10%.", encoding="utf-8")

    monkeypatch.setattr(chat.bot, "download", fake_download)
    (reply,) = await chat(ADMIN, document=doc("../../Скидки.txt"))
    assert reply.startswith("Добавил «Скидки.txt»")
    assert saved[0].name == "Скидки.txt" and saved[0].parent != assistant.library.folder
    assert (assistant.library.folder / "Скидки.txt").exists() and not saved[0].exists()


async def test_broken_reupload_keeps_old_document(chat, assistant, monkeypatch):
    name = "Памятка приёмщику.txt"
    before = (assistant.library.folder / name).read_text(encoding="utf-8")

    async def blank(file, destination):
        destination.write_text("   ", encoding="utf-8")

    monkeypatch.setattr(chat.bot, "download", blank)
    (reply,) = await chat(ADMIN, document=doc(name))
    assert reply.startswith(f"Не смог прочитать «{name}»")
    assert (assistant.library.folder / name).read_text(encoding="utf-8") == before
    assert name in assistant.library.pages


async def test_question_without_hits(chat, llm):
    (reply,) = await chat(GUEST, "пароль wifi")
    assert reply == "В документах ответа нет. Уточните вопрос или спросите сотрудника." and llm.calls == []


async def test_answer_of_only_bad_citations_not_empty(chat, llm):
    # пустой текст Telegram не принимает — бот должен ответить честным «нет»
    llm.reply = "[9]"
    (reply,) = await chat(GUEST, "Какая гарантия на детали?")
    assert reply == "В документах ответа нет. Уточните вопрос или спросите сотрудника."
