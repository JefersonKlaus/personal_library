"""Groq client against a local HTTP server that mimics the API (no internet)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.importing import groq_client
from src.importing.groq_client import GroqClient, GroqError


class FakeGroq:
    """Answers the programmed responses in order and records the requests."""

    def __init__(self):
        self.replies = []  # (status, body dict, headers)
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"path": self.path, "auth": self.headers["Authorization"],
                                      "body": body})
                status, payload, headers = fake.replies.pop(0)
                data = json.dumps(payload).encode()
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/openai/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def answer(self, content, status=200, headers=None):
        body = {"choices": [{"message": {"content": content}}]} if status == 200 else content
        self.replies.append((status, body, headers or {}))


@pytest.fixture
def groq():
    server = FakeGroq()
    yield server
    server.server.shutdown()


def _client(groq, waits=None, **kwargs):
    return GroqClient("gsk_teste", "modelo-x", base_url=groq.url,
                      sleep=(waits.append if waits is not None else lambda s: None), **kwargs)


def test_sends_json_request_and_parses_answer(groq):
    groq.answer('{"title": "Dom Casmurro"}')
    assert _client(groq).chat_json("sistema", "usuário") == {"title": "Dom Casmurro"}
    request = groq.requests[0]
    assert request["path"] == "/openai/v1/chat/completions"
    assert request["auth"] == "Bearer gsk_teste"
    assert request["body"]["model"] == "modelo-x"
    assert request["body"]["response_format"] == {"type": "json_object"}
    assert request["body"]["temperature"] == 0
    assert [m["role"] for m in request["body"]["messages"]] == ["system", "user"]


def test_invalid_key_is_fatal(groq):
    groq.answer({"error": {"message": "Invalid API Key"}}, status=401)
    with pytest.raises(GroqError, match="Chave da API") as info:
        _client(groq).chat_json("s", "u")
    assert info.value.fatal


def test_unknown_model_is_fatal(groq):
    groq.answer({"error": {"message": "The model `x` does not exist"}}, status=404)
    with pytest.raises(GroqError, match="Modelo 'modelo-x'") as info:
        _client(groq).chat_json("s", "u")
    assert info.value.fatal


def test_rate_limit_waits_and_retries(groq):
    """429: waits for the Retry-After (or the 'try again in 1.5s' of the message) and tries again."""
    groq.answer({"error": {"message": "Rate limit"}}, status=429, headers={"retry-after": "3"})
    groq.answer({"error": {"message": "Please try again in 250ms."}}, status=429)
    groq.answer({"error": {"message": "overloaded"}}, status=503)
    groq.answer('{"ok": true}')
    waits = []
    assert _client(groq, waits).chat_json("s", "u") == {"ok": True}
    assert waits == [3.0, 0.75, 8.0]  # 250 ms + margin; then a growing wait


def test_gives_up_after_max_retries(groq):
    for _ in range(3):
        groq.answer({"error": {"message": "Rate limit"}}, status=429)
    with pytest.raises(GroqError, match="recusou após 3") as info:
        _client(groq, [], max_retries=2).chat_json("s", "u")
    assert not info.value.fatal  # only this book fails


def test_answer_that_is_not_json(groq):
    groq.answer("isto não é json")
    with pytest.raises(GroqError, match="JSON") as info:
        _client(groq).chat_json("s", "u")
    assert not info.value.fatal


def test_no_connection_is_fatal():
    client = GroqClient("k", base_url="http://127.0.0.1:9/v1", timeout=2)
    with pytest.raises(GroqError, match="Sem conexão") as info:
        client.chat_json("s", "u")
    assert info.value.fatal


def test_api_key_from_environment(monkeypatch):
    monkeypatch.setenv(groq_client.API_KEY_ENV, " gsk_env ")
    assert groq_client.resolve_api_key("") == "gsk_env"
    assert groq_client.resolve_api_key(" gsk_digitada ") == "gsk_digitada"
