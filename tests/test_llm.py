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


class FakeResponse:
    def __init__(self, code, headers=None, payload=None):
        self.status_code = code
        self.headers = headers or {}
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def test_pauses_double_and_respect_retry_after(monkeypatch):
    replies = [
        FakeResponse(503),
        FakeResponse(429, {"Retry-After": "10"}),
        FakeResponse(429, {"Retry-After": "999"}),
        FakeResponse(200, payload=ok("ok")[1]),
    ]
    sleeps = []
    monkeypatch.setattr("docassist.llm.requests.post", lambda *a, **k: replies.pop(0))
    monkeypatch.setattr("docassist.llm.time.sleep", sleeps.append)
    assert LLM("http://x", "k", "m", pause=1, attempts=4).chat([]) == "ok"
    # 1, затем Retry-After 10 больше удвоенной паузы, затем потолок 30 секунд
    assert sleeps == [1, 10, 30]


def test_retry_after_bad_values():
    from docassist.llm import _retry_after

    assert _retry_after(FakeResponse(429)) == 0
    assert _retry_after(FakeResponse(429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})) == 0
    assert _retry_after(FakeResponse(429, {"Retry-After": "2.5"})) == 2.5


def test_forbidden_no_retry(monkeypatch):
    calls = []
    monkeypatch.setattr("docassist.llm.requests.post", lambda *a, **k: calls.append(1) or FakeResponse(403))
    with pytest.raises(LLMError, match="403"):
        LLM("http://x", "k", "m").chat([])
    assert len(calls) == 1


def test_content_not_string(server):
    # часть шлюзов отдаёт content списком частей — это ошибка модели, а не падение бота
    s = server((200, {"choices": [{"message": {"content": [{"type": "text", "text": "Да"}]}}]}))
    with pytest.raises(LLMError, match="непонятный ответ"):
        LLM(s.url, "", "m", attempts=1).chat([])
    s = server((200, {"choices": [{"message": {"content": None}}]}))
    with pytest.raises(LLMError, match="пустой ответ"):
        LLM(s.url, "", "m", attempts=1).chat([])
