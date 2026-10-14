"""Клиент модели на местном сервере, который отвечает в формате OpenAI."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from docassist.llm import LLM, LLMError


class Server:
    def __init__(self, replies):
        self.replies = list(replies)  # (код, тело) по очереди
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append((self.path, self.headers.get("Authorization"), body))
                code, payload = outer.replies.pop(0)
                data = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def close(self):
        self.httpd.shutdown()


def ok(text):
    return 200, {"choices": [{"message": {"role": "assistant", "content": text}}]}


@pytest.fixture
def server():
    servers = []

    def make(*replies):
        s = Server(replies)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()


def test_request_format(server):
    s = server(ok(" Гарантия 90 дней [1]. "))
    llm = LLM(s.url + "/", "secret", "free-model", max_tokens=700)
    assert llm.chat([{"role": "user", "content": "вопрос"}]) == "Гарантия 90 дней [1]."
    path, auth, body = s.requests[0]
    assert path == "/v1/chat/completions"
    assert auth == "Bearer secret"
    assert body["model"] == "free-model" and body["max_tokens"] == 700 and body["temperature"] == 0


def test_retries_on_limit_and_server_errors(server):
    s = server((429, {"error": "slow down"}), (502, {}), ok("готово"))
    llm = LLM(s.url, "k", "m", pause=0.01)
    assert llm.chat([]) == "готово"
    assert len(s.requests) == 3


def test_gives_up_after_attempts(server):
    s = server(*[(503, {})] * 3)
    with pytest.raises(LLMError, match="после 3 попыток"):
        LLM(s.url, "k", "m", pause=0.01).chat([])


def test_wrong_key_no_retry(server):
    s = server((401, {"error": "bad key"}))
    with pytest.raises(LLMError, match="ключ не подходит"):
        LLM(s.url, "bad", "m", pause=0.01).chat([])
    assert len(s.requests) == 1


def test_empty_and_strange_answers(server):
    s = server(ok(None), (200, {"oops": 1}), (400, {"error": "unknown model"}))
    llm = LLM(s.url, "k", "m")
    with pytest.raises(LLMError, match="пустой ответ"):
        llm.chat([])
    with pytest.raises(LLMError, match="непонятный ответ"):
        llm.chat([])
    with pytest.raises(LLMError, match="400"):
        llm.chat([])


def test_no_connection():
    with pytest.raises(LLMError, match="нет связи"):
        LLM("http://127.0.0.1:9/v1", "k", "m", pause=0.01, attempts=2, timeout=1).chat([])


def test_no_key_no_header(server):
    s = server(ok("локальная модель"))
    LLM(s.url, "", "llama").chat([])
    assert s.requests[0][1] is None
