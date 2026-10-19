"""Настройки из .env — всё, что заказчик меняет без правки кода."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_max_tokens: int
    docs_dir: Path
    telegram_token: str
    admins: frozenset[int]


def load_config() -> Config:
    load_dotenv(ROOT / ".env")
    docs = Path(os.getenv("DOCS_DIR") or "samples")
    # разделитель — запятая или пробел: «1 2» — два администратора, а не один с id 12
    admins = {int(x) for x in re.split(r"[,\s]+", os.getenv("ADMIN_IDS", "")) if x}
    return Config(
        llm_base_url=os.getenv("LLM_BASE_URL", ""),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", ""),
        llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS") or 1500),
        docs_dir=docs if docs.is_absolute() else ROOT / docs,
        telegram_token=os.getenv("TELEGRAM_TOKEN", ""),
        admins=frozenset(admins),
    )
