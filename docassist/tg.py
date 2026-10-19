"""Telegram-бот: вопросы — всем, загрузка и удаление документов — администраторам."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from .assistant import Answer, Assistant
from .llm import LLMError
from .loader import SUPPORTED, Page, UnreadableDocument

log = logging.getLogger(__name__)

MAX_FILE_MB = 20  # больше Telegram боту скачать не даёт

START = (
    "Здравствуйте! Я отвечаю на вопросы по документам компании и показываю, "
    "откуда взял ответ.\n\n"
    "Просто напишите вопрос, например:\n"
    "— Сколько стоит диагностика, если отказаться от ремонта?\n"
    "— Какая гарантия на детали?\n"
    "— Как вернуть деньги за ремонт?\n\n"
    "Список документов — /docs"
)
FAILED = "Не получилось получить ответ, попробуйте через минуту."
ADMIN_HELP = (
    "\n\nВы администратор: пришлите файл PDF, Word, TXT или Markdown — добавлю его в базу. "
    "Удалить документ — /remove имя файла"
)


def format_answer(answer: Answer) -> str:
    if not answer.sources:
        return answer.text
    lines = [f"[{i}] {s.label()}" for i, s in enumerate(answer.sources, 1)]
    return answer.text + "\n\nИсточники:\n" + "\n".join(lines)


def _pdf_pages(pages: list[Page]) -> int:
    # страницы с номером есть только у PDF; у Word и текста — ноль
    return sum(1 for p in pages if p.page)


def build(assistant: Assistant, token: str, admins: frozenset[int]) -> tuple[Bot, Dispatcher]:
    bot = Bot(token)
    router = Router()
    library = assistant.library

    def is_admin(message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in admins

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer(START + (ADMIN_HELP if is_admin(message) else ""))

    @router.message(Command("docs"))
    async def docs(message: Message) -> None:
        if not library.pages:
            await message.answer("В базе пока нет документов.")
            return
        lines = []
        for name, pages in library.pages.items():
            count = _pdf_pages(pages)
            lines.append(f"— {name}" + (f" ({count} стр.)" if count else ""))
        await message.answer("Документы в базе:\n" + "\n".join(lines))

    @router.message(Command("remove"))
    async def remove(message: Message, command: CommandObject) -> None:
        if not is_admin(message):
            await message.answer("Удалять документы может только администратор.")
            return
        name = (command.args or "").strip()
        # удаление ждёт замка, пока загрузка в другом потоке собирает индекс, — не держим цикл событий
        if await asyncio.to_thread(library.remove, name):
            await message.answer(f"Удалил «{name}». Документов в базе: {len(library.pages)}.")
        else:
            await message.answer("Такого документа нет. Точное имя — в списке /docs.")

    @router.message(F.document)
    async def upload(message: Message, bot: Bot) -> None:
        if not is_admin(message):
            await message.answer("Загружать документы может только администратор.")
            return
        doc = message.document
        name = Path(doc.file_name or "документ").name
        if Path(name).suffix.lower() not in SUPPORTED:
            await message.answer("Пришлите PDF, Word (.docx) или текстовый файл.")
            return
        if (doc.file_size or 0) > MAX_FILE_MB * 1024 * 1024:
            await message.answer(f"Файл больше {MAX_FILE_MB} МБ — Telegram не даст его скачать.")
            return
        # качаем во временную папку: битый файл не должен затереть прежний документ с тем же именем
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / name
            await bot.download(doc, destination=path)
            try:
                pages = await asyncio.to_thread(library.add, path)
            except UnreadableDocument as e:
                await message.answer(f"Не смог прочитать «{name}»: {e}.")
                return
        count = _pdf_pages(pages)
        size = f", {count} стр." if count else ""
        await message.answer(f"Добавил «{name}»{size}. Документов в базе: {len(library.pages)}.")

    @router.message(F.text)
    async def question(message: Message, bot: Bot) -> None:
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        try:
            answer = await asyncio.to_thread(assistant.ask, message.text)
        except LLMError as e:
            log.warning("llm failed: %s", e)
            await message.answer(FAILED)
            return
        await message.answer(format_answer(answer))

    dp = Dispatcher()
    dp.include_router(router)
    return bot, dp
