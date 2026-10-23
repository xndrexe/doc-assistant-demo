"""Запуск: бот в Telegram или вопрос из командной строки.

python -m docassist ask "Какая гарантия на ремонт?"
python -m docassist bot
python -m docassist --docs путь ask "вопрос"   # другая папка с документами на один запуск
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .assistant import Assistant, Library
from .config import load_config
from .llm import LLM, LLMError
from .tg import build, format_answer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docassist", description="ИИ-помощник по документам")
    parser.add_argument(
        "--docs",
        type=Path,
        help="папка с документами (по умолчанию DOCS_DIR из .env); относительный путь — от текущей папки",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    ask = sub.add_parser("ask", help="задать вопрос и получить ответ со ссылками")
    ask.add_argument("question", nargs="+")
    sub.add_parser("bot", help="запустить Telegram-бота")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    if not cfg.llm_base_url or not cfg.llm_model:
        print("Заполните LLM_BASE_URL и LLM_MODEL в .env (образец — .env.example).", file=sys.stderr)
        return 2
    library = Library(args.docs or cfg.docs_dir)
    llm = LLM(cfg.llm_base_url, cfg.llm_api_key, cfg.llm_model, max_tokens=cfg.llm_max_tokens)
    assistant = Assistant(library, llm)

    if args.cmd == "ask":
        try:
            answer = assistant.ask(" ".join(args.question))
        except LLMError as e:
            print(f"Модель не ответила: {e}", file=sys.stderr)
            return 1
        print(format_answer(answer))
        return 0

    if not cfg.telegram_token:
        print("Заполните TELEGRAM_TOKEN в .env.", file=sys.stderr)
        return 2
    bot, dp = build(assistant, cfg.telegram_token, cfg.admins)
    asyncio.run(dp.start_polling(bot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
