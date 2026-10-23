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


def test_admin_ids_separated_by_spaces(env):
    # «1 2» раньше склеивалось в одного администратора с id 12
    env.setenv("ADMIN_IDS", "111 222\t333,444")
    assert config.load_config().admins == {111, 222, 333, 444}


def test_admin_ids_not_numbers(env):
    # @username вместо числа — частая ошибка; падать трассировкой int() тут нечестно
    env.setenv("ADMIN_IDS", "111, @boss")
    with pytest.raises(ValueError, match="ADMIN_IDS.*@boss"):
        config.load_config()
