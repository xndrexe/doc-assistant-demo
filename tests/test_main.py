"""Командная строка: модель и Telegram подменены."""

import pytest

from docassist import __main__ as cli
from docassist.config import Config
from docassist.llm import LLMError
from tests.conftest import FakeLLM


@pytest.fixture
def setup(monkeypatch, library):
    state = {"cfg": Config("http://llm", "", "m", 100, library.folder, "", frozenset()), "llm": FakeLLM()}
    monkeypatch.setattr(cli, "load_config", lambda: state["cfg"])
    monkeypatch.setattr(cli, "LLM", lambda *a, **k: state["llm"])
    return state


def test_ask_prints_answer_with_sources(setup, capsys):
    setup["llm"].reply = "Шесть месяцев [1]."
    assert cli.main(["ask", "Какая", "гарантия", "на", "детали?"]) == 0
    out = capsys.readouterr().out
    assert "Шесть месяцев [1]." in out and "Договор на ремонт.pdf, стр. 3" in out
    assert setup["llm"].calls[0][1]["content"].endswith("Вопрос: Какая гарантия на детали?")


def test_ask_model_down(setup, capsys):
    setup["llm"].reply = LLMError("502")
    assert cli.main(["ask", "Какая гарантия?"]) == 1
    assert "Модель не ответила: 502" in capsys.readouterr().err


def test_not_configured(setup, capsys):
    cfg = setup["cfg"]
    setup["cfg"] = Config("", "", "", 100, cfg.docs_dir, "", frozenset())
    assert cli.main(["ask", "вопрос"]) == 2
    assert "LLM_BASE_URL" in capsys.readouterr().err
    setup["cfg"] = cfg
    assert cli.main(["bot"]) == 2
    assert "TELEGRAM_TOKEN" in capsys.readouterr().err


def test_docs_option_overrides_config(setup, tmp_path, capsys):
    other = tmp_path / "другие"
    other.mkdir()
    (other / "a.txt").write_text("Доставка по городу бесплатно.", encoding="utf-8")
    setup["llm"].reply = "Бесплатно [1]."
    assert cli.main(["--docs", str(other), "ask", "Сколько стоит доставка?"]) == 0
    assert capsys.readouterr().out.endswith("[1] a.txt\n")
