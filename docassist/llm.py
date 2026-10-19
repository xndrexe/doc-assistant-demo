"""Клиент любой модели с API в формате OpenAI (chat/completions).

Так подходят OpenAI, OpenRouter (в том числе бесплатные модели), Groq,
YandexGPT через совместимый API, локальная Ollama и свой шлюз вроде LiteLLM:
меняются только адрес, ключ и имя модели в .env.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class LLMError(Exception):
    """Модель не ответила. Текст — для журнала, пользователю показывается общее сообщение."""


@dataclass
class LLM:
    base_url: str
    api_key: str
    model: str
    max_tokens: int = 1500  # «думающим» моделям нужен запас: часть уходит на рассуждение
    timeout: float = 60
    attempts: int = 3
    pause: float = 2.0  # первая пауза между попытками, дальше вдвое больше

    def chat(self, messages: list[dict]) -> str:
        url = self.base_url.rstrip("/") + "/chat/completions"
        body = {"model": self.model, "messages": messages, "max_tokens": self.max_tokens, "temperature": 0}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        wait = self.pause
        for attempt in range(1, self.attempts + 1):
            try:
                r = requests.post(url, json=body, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                problem = f"нет связи: {e}"
            else:
                if r.status_code in (401, 403):
                    raise LLMError(f"ключ не подходит ({r.status_code})")
                if r.status_code not in RETRY_STATUS:
                    return self._content(r)
                problem = f"ответ {r.status_code}"
                wait = max(wait, _retry_after(r))
            if attempt < self.attempts:
                log.warning("llm attempt %s failed (%s), retry in %.0fs", attempt, problem, wait)
                time.sleep(wait)
                wait *= 2
        raise LLMError(f"модель не ответила после {self.attempts} попыток: {problem}")

    @staticmethod
    def _content(r: requests.Response) -> str:
        if r.status_code != 200:
            raise LLMError(f"ответ {r.status_code}: {r.text[:300]}")
        try:
            content = r.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise LLMError(f"непонятный ответ: {r.text[:300]}") from e
        if content is not None and not isinstance(content, str):
            # иначе .strip() упал бы с AttributeError мимо LLMError, и бот замолчал бы без ответа
            raise LLMError(f"непонятный ответ: {r.text[:300]}")
        if not content:
            raise LLMError("пустой ответ — мало max_tokens для этой модели?")
        return content.strip()


def _retry_after(r: requests.Response) -> float:
    try:
        return min(float(r.headers.get("Retry-After", 0)), 30.0)
    except ValueError:
        return 0.0
