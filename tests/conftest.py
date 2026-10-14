from pathlib import Path

import pytest

from docassist.assistant import Assistant, Library

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


class FakeLLM:
    """Вместо модели: запоминает запросы и отдаёт заготовленный ответ."""

    def __init__(self, reply="Ответ [1]."):
        self.reply = reply
        self.calls = []

    def chat(self, messages):
        self.calls.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def library(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    for src in SAMPLES.iterdir():
        (folder / src.name).write_bytes(src.read_bytes())
    return Library(folder)


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def assistant(library, llm):
    return Assistant(library, llm)
