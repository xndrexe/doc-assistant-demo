"""Прогоняет настоящего бота с настоящей моделью и рисует переписку как чат Telegram.

Вопросы идут через диспетчер aiogram, ответы даёт модель из .env (LLM_*);
подменена только отправка в Telegram — её перехватываем и рисуем. Итог —
HTML в build/screens/, снимки делает tools/shoot.py.

    .venv/bin/python tools/render_chat.py
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.methods import SendMessage  # noqa: E402
from aiogram.types import Chat, Message, Update  # noqa: E402

from docassist import tg  # noqa: E402
from docassist.assistant import Assistant, Library  # noqa: E402
from docassist.config import load_config  # noqa: E402
from docassist.llm import LLM  # noqa: E402

OUT = ROOT / "build" / "screens"
ADMIN, CLIENT = 1, 100
PRICE = (
    "Прайс на работы «ТехноДом», с 01.10.2026\n"
    "Замена дисплея телефона — от 4 500 рублей, срок 1 день.\n"
    "Замена аккумулятора телефона — 1 800 рублей, срок 1 час.\n"
    "Чистка ноутбука от пыли с заменой термопасты — 2 200 рублей.\n"
    "Замена подшипников стиральной машины — от 5 500 рублей.\n"
)


@dataclass
class Bubble:
    side: str  # "in" — бот, "out" — человек
    text: str
    time: str
    file_name: str | None = None


class Capture(BaseSession):
    """Вместо Telegram: ответы бота складываются в текущую ленту."""

    def __init__(self):
        super().__init__()
        self.feed: list[Bubble] = []
        self.clock = datetime(2026, 10, 14, 10, 12)

    def stamp(self) -> str:
        self.clock += timedelta(seconds=40)
        return f"{self.clock:%H:%M}"

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, SendMessage):
            self.feed.append(Bubble("in", method.text, self.stamp()))
            return Message(message_id=1, date=datetime.now(), chat=Chat(id=method.chat_id, type="private"))
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        raise NotImplementedError


def update(user_id: int, text: str | None = None, file_name: str | None = None) -> Update:
    message = {
        "message_id": 1,
        "date": 0,
        "chat": {"id": user_id, "type": "private"},
        "from": {"id": user_id, "is_bot": False, "first_name": "Ирина"},
    }
    if text:
        message["text"] = text
        if text.startswith("/"):
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    if file_name:
        message["document"] = {"file_id": "f", "file_unique_id": "u", "file_name": file_name}
    return Update.model_validate({"update_id": 1, "message": message})


CSS = """
* { box-sizing: border-box; margin: 0; }
body { font: 15px/1.38 Inter, 'Noto Color Emoji', sans-serif; background: #fff; }
.phone { width: 390px; background: linear-gradient(160deg, #a9c6dc 0%, #c8d9c0 50%, #9db8c9 100%); }
.bar { display: flex; align-items: center; gap: 10px; padding: 10px 14px;
  background: #fff; border-bottom: 1px solid #e3e3e3; }
.ava { width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; font-size: 20px;
  background: linear-gradient(135deg, #5aa0d8, #2f6ea8); color: #fff; }
.bar b { font-size: 16px; display: block; }
.bar span { color: #8a8a8a; font-size: 13px; }
.caption { padding: 8px 14px; background: #2f6ea8; color: #fff; font-size: 13px; font-weight: 600; }
.chat { padding: 10px 8px 14px; display: flex; flex-direction: column; gap: 6px; }
.msg { max-width: 88%; padding: 7px 10px 6px; border-radius: 16px; white-space: pre-wrap;
  box-shadow: 0 1px 1px rgba(0,0,0,.12); word-wrap: break-word; }
.in { background: #fff; align-self: flex-start; border-bottom-left-radius: 5px; }
.out { background: #e1fec6; align-self: flex-end; border-bottom-right-radius: 5px; }
.t { float: right; margin: 6px 0 -4px 10px; font-size: 11px; color: #9aa59a; }
.out .t { color: #5fae58; }
.src { color: #2f6ea8; }
.file { display: flex; gap: 10px; align-items: center; }
.file i { width: 42px; height: 42px; border-radius: 50%; background: #2f6ea8; color: #fff; display: grid;
  place-items: center; font-style: normal; font-size: 12px; font-weight: 700; }
.file small { display: block; color: #6f9a63; }
"""


def bubble_html(b: Bubble) -> str:
    if b.file_name:
        ext = Path(b.file_name).suffix.lstrip(".").upper()
        name = escape(b.file_name)
        body = f'<div class="file"><i>{ext}</i><div><b>{name}</b><small>0,4 КБ</small></div></div>'
    else:
        text, _, sources = b.text.partition("\n\nИсточники:\n")
        body = escape(text)
        if sources:
            body += '\n\n<span class="src">Источники:\n' + escape(sources) + "</span>"
    return f'<div class="msg {b.side}">{body}<span class="t">{b.time}</span></div>'


def render(title: str, feed: list[Bubble]) -> str:
    return (
        f"<!doctype html><meta charset=utf-8><style>{CSS}</style>"
        '<div class="phone"><div class="bar"><div class="ava">📄</div>'
        "<div><b>ТехноДом · помощник</b><span>бот</span></div></div>"
        f'<div class="caption">{escape(title)}</div>'
        f'<div class="chat">{"".join(map(bubble_html, feed))}</div></div>'
    )


async def main() -> None:
    cfg = load_config()
    if not cfg.llm_base_url or not cfg.llm_model:
        sys.exit("Нужны LLM_BASE_URL и LLM_MODEL — ответы на снимках даёт настоящая модель.")
    work = Path(tempfile.mkdtemp(prefix="docassist-shots-"))
    try:
        for src in (ROOT / "samples").iterdir():
            shutil.copy(src, work / src.name)
        llm = LLM(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model, max_tokens=cfg.llm_max_tokens)
        bot, dp = tg.build(Assistant(Library(work), llm), "42:SHOTS", frozenset({ADMIN}))
        session = Capture()
        bot.session = session

        async def fake_download(file, destination):
            destination.write_text(PRICE, encoding="utf-8")

        bot.download = fake_download

        async def say(user_id: int, text: str | None = None, file_name: str | None = None) -> None:
            session.feed.append(Bubble("out", text or "", session.stamp(), file_name))
            await dp.feed_update(bot, update(user_id, text, file_name))

        screens = [
            (
                "1-voprosy.html",
                "Вопросы по договору",
                CLIENT,
                ["/start", "Сколько стоит диагностика, если я передумаю чинить стиральную машину?"],
            ),
            (
                "2-neskolko-dokumentov.html",
                "Ответ из разных документов и честное «нет»",
                CLIENT,
                [
                    "Ремонт не помог, как вернуть деньги и сколько ждать на карту?",
                    "Вы работаете в субботу?",
                    "Есть доставка в Казань?",
                ],
            ),
            (
                "3-admin.html",
                "Администратор добавляет документ",
                ADMIN,
                ["file:Прайс на работы.txt", "Сколько стоит заменить аккумулятор в телефоне?", "/docs"],
            ),
        ]
        OUT.mkdir(parents=True, exist_ok=True)
        for file, title, user, steps in screens:
            session.feed = []
            for step in steps:
                if step.startswith("file:"):
                    await say(user, file_name=step[5:])
                else:
                    await say(user, step)
            (OUT / file).write_text(render(title, session.feed), encoding="utf-8")
            for b in session.feed:
                print(f"{b.side}: {b.file_name or b.text}\n")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"html: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
