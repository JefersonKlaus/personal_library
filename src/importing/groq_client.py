"""Minimal client of the Groq API (chat in the OpenAI API format), with no dependencies.

Only used when the user ticks "Usar Groq AI" in the Import tab.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

DEFAULT_MODEL = "llama-3.3-70b-versatile"
# GROQ_BASE_URL allows pointing to a proxy (or to a test server).
BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
API_KEY_ENV = "GROQ_API_KEY"  # used when the key field is left empty
_RETRY_IN = re.compile(r"try again in ([\d.]+)(ms|s)", re.I)


class GroqError(Exception):
    """Failure while querying Groq. `fatal` = there is no point going on with the other
    books (invalid key, non-existing model, no connection)."""

    def __init__(self, message: str, fatal: bool = False) -> None:
        super().__init__(message)
        self.fatal = fatal


class GroqClient:
    """Asks questions to Groq and returns the answer as JSON."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, base_url: str | None = None,
                 timeout: float = 60, max_retries: int = 4,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.api_key = api_key.strip()
        self.model = (model or DEFAULT_MODEL).strip()
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.sleep = sleep

    def chat_json(self, system: str, user: str,
                  cancel: threading.Event | None = None) -> dict:
        """Sends the conversation and returns the JSON object the model answered."""
        body = json.dumps({
            "model": self.model, "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }).encode("utf-8")
        for attempt in range(self.max_retries + 1):
            try:
                return self._parse(self._post("/chat/completions", body))
            except urllib.error.HTTPError as exc:
                wait = self._handle_http_error(exc, attempt)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise GroqError(f"Sem conexão com a Groq ({getattr(exc, 'reason', exc)}).",
                                fatal=True) from exc
            if cancel is not None:
                if cancel.wait(wait):  # waits, but wakes up at once if the user cancels
                    raise GroqError("cancelado")
            else:
                self.sleep(wait)
        raise GroqError("A Groq continua recusando (limite de uso). Tente de novo mais tarde.")

    def _post(self, path: str, body: bytes) -> dict:
        request = urllib.request.Request(
            self.base_url + path, data=body, method="POST",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json", "User-Agent": "personal-library"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _handle_http_error(self, exc: urllib.error.HTTPError, attempt: int) -> float:
        """Returns how many seconds to wait before trying again, or raises GroqError."""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except (ValueError, AttributeError, OSError):
            detail = ""
        if exc.code in (401, 403):
            raise GroqError("Chave da API da Groq inválida ou sem permissão.", fatal=True)
        if exc.code == 404 or "model" in detail.lower() and exc.code == 400:
            raise GroqError(f"Modelo '{self.model}' indisponível na Groq: {detail}", fatal=True)
        if exc.code == 429 or exc.code >= 500:
            if attempt >= self.max_retries:
                raise GroqError(f"A Groq recusou após {attempt + 1} tentativas: {detail or exc}")
            return _retry_after(exc, detail, attempt)
        raise GroqError(f"A Groq respondeu {exc.code}: {detail or exc.reason}")

    @staticmethod
    def _parse(payload: dict) -> dict:
        try:
            content = payload["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GroqError("A resposta da IA não veio em JSON.") from exc
        if not isinstance(data, dict):
            raise GroqError("A resposta da IA não veio em JSON.")
        return data


def _retry_after(exc: urllib.error.HTTPError, detail: str, attempt: int) -> float:
    """How long to wait: the Retry-After header, the 'try again in 7.5s' of the message or
    a growing wait (2, 4, 8... s), at most 60 s."""
    header = exc.headers.get("retry-after") if exc.headers else None
    try:
        if header:
            return min(60.0, float(header))
    except ValueError:
        pass
    match = _RETRY_IN.search(detail)
    if match:
        seconds = float(match.group(1)) / (1000 if match.group(2).lower() == "ms" else 1)
        return min(60.0, seconds + 0.5)
    return min(60.0, 2.0 ** (attempt + 1))


def resolve_api_key(typed: str) -> str:
    """The typed key or, if empty, the one in the GROQ_API_KEY environment variable."""
    return (typed or "").strip() or os.environ.get(API_KEY_ENV, "").strip()
