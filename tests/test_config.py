"""Настройки из окружения; настоящий .env не читается."""

import pytest

from docassist import config

KEYS = (
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_MAX_TOKENS",
    "DOCS_DIR",
    "TELEGRAM_TOKEN",
    "ADMIN_IDS",
)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_defaults(env):
    cfg = config.load_config()
    assert cfg.llm_base_url == "" and cfg.llm_model == "" and cfg.telegram_token == ""
    assert cfg.llm_max_tokens == 1500
    assert cfg.docs_dir == config.ROOT / "samples"
    assert cfg.admins == frozenset()


def test_values(env, tmp_path):
    env.setenv("LLM_MAX_TOKENS", "700")
    env.setenv("ADMIN_IDS", " 1, 22 ,,333")
    env.setenv("DOCS_DIR", str(tmp_path))
    cfg = config.load_config()
    assert cfg.llm_max_tokens == 700
    assert cfg.admins == {1, 22, 333}
    assert cfg.docs_dir == tmp_path


def test_relative_docs_dir_from_project_root(env):
    env.setenv("DOCS_DIR", "data/docs")
    env.setenv("LLM_MAX_TOKENS", "")
    cfg = config.load_config()
    assert cfg.docs_dir == config.ROOT / "data" / "docs" and cfg.llm_max_tokens == 1500
