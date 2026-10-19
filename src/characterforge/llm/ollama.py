"""Small, dependency-free Ollama adapter; connects only to IPv4 loopback."""

from dataclasses import dataclass
import json
import socket
import time
from typing import Callable
from urllib import error, parse, request


class OllamaError(RuntimeError):
    """A local service, protocol, or inference failure."""


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OllamaError("Local model endpoint tried to redirect; request blocked.")


@dataclass
class ChatResult:
    content: str
    elapsed_s: float
    ttft_s: float | None
    final: dict
    thinking_observed: bool


class OllamaClient:
    def __init__(self, endpoint: str = "http://127.0.0.1:11435", timeout: float = 120):
        url = parse.urlsplit(endpoint)
        try:
            port = url.port
        except ValueError as exc:
            raise ValueError("Invalid local endpoint port.") from exc
        if (url.scheme != "http" or url.hostname != "127.0.0.1"
                or url.username or url.password or url.query or url.fragment
                or url.path not in ("", "/") or not port):
            raise ValueError("Endpoint must be http://127.0.0.1:<port> only.")
        if timeout <= 0:
            raise ValueError("Timeout must be positive.")
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        # Explicitly ignore HTTP(S)_PROXY and system proxy settings.
        self.opener = request.build_opener(request.ProxyHandler({}), _NoRedirect())

    def _open(self, route: str, payload: dict | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(self.endpoint + route, data=data,
                              headers={"Content-Type": "application/json"})
        try:
            return self.opener.open(req, timeout=self.timeout)
        except error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise OllamaError(f"Ollama returned HTTP {exc.code}: {detail}") from exc
        except (error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            raise OllamaError(f"Cannot use local Ollama at {self.endpoint}: {exc}") from exc

    @staticmethod
    def _decode(raw: bytes) -> dict:
        try:
            item = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise OllamaError("Ollama returned invalid JSON.") from exc
        if not isinstance(item, dict):
            raise OllamaError("Ollama returned a non-object response.")
        if item.get("error"):
            raise OllamaError(str(item["error"]))
        return item

    def json_request(self, route: str, payload: dict | None = None) -> dict:
        try:
            with self._open(route, payload) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise OllamaError("Ollama response exceeded the size limit.")
            return self._decode(raw)
        except (socket.timeout, TimeoutError, OSError) as exc:
            raise OllamaError(f"Reading Ollama response failed: {exc}") from exc

    def model_identity(self, model: str) -> dict:
        tags = self.json_request("/api/tags")
        for item in tags.get("models", []):
            if model in (item.get("name"), item.get("model")):
                if not item.get("digest"):
                    raise OllamaError("Model digest missing from /api/tags.")
                return item
        raise OllamaError(f"Model {model!r} is not installed in this Ollama service.")

    @staticmethod
    def _message(item: dict) -> dict:
        message = item.get("message", {})
        if not isinstance(message, dict) or not isinstance(message.get("content", ""), str):
            raise OllamaError("Ollama returned an invalid chat message.")
        return message

    @staticmethod
    def chat_payload(model: str, messages: list[dict], options: dict,
                     *, stream: bool = False, keep_alive: str = "5m",
                     runner: str = "llamacpp") -> dict:
        return {"model": model, "messages": messages, "options": options,
                "stream": stream, "think": False, "keep_alive": keep_alive,
                "runner": runner}

    def chat(self, model: str, messages: list[dict], options: dict,
             *, stream: bool = False, keep_alive: str = "5m",
             runner: str = "llamacpp",
             on_text: Callable[[str], None] | None = None) -> ChatResult:
        payload = self.chat_payload(model, messages, options, stream=stream,
                                    keep_alive=keep_alive, runner=runner)
        started = time.perf_counter()
        first_text = None
        chunks = []
        thinking = False
        final = None
        total_bytes = 0
        try:
            with self._open("/api/chat", payload) as response:
                if stream:
                    while True:
                        raw = response.readline(1024 * 1024 + 1)
                        if not raw:
                            break
                        total_bytes += len(raw)
                        if len(raw) > 1024 * 1024 or total_bytes > 16 * 1024 * 1024:
                            raise OllamaError("Ollama stream exceeded the size limit.")
                        if time.perf_counter() - started > self.timeout:
                            raise OllamaError("Ollama request exceeded its total timeout.")
                        if not raw.strip():
                            continue
                        item = self._decode(raw)
                        message = self._message(item)
                        thinking = thinking or bool(message.get("thinking"))
                        content = message.get("content", "")
                        if content:
                            if first_text is None:
                                first_text = time.perf_counter() - started
                            chunks.append(content)
                            if on_text:
                                on_text(content)
                        if item.get("done"):
                            final = item
                            break
                else:
                    raw = response.read(16 * 1024 * 1024 + 1)
                    if len(raw) > 16 * 1024 * 1024:
                        raise OllamaError("Ollama response exceeded the size limit.")
                    final = self._decode(raw)
                    message = self._message(final)
                    thinking = bool(message.get("thinking"))
                    chunks.append(message.get("content", ""))
                    if on_text and chunks[0]:
                        on_text(chunks[0])
        except (socket.timeout, TimeoutError, OSError) as exc:
            raise OllamaError(f"Reading Ollama response failed: {exc}") from exc
        elapsed = time.perf_counter() - started
        if final is None or not final.get("done"):
            raise OllamaError("Ollama response ended without a completion record.")
        if elapsed > self.timeout:
            raise OllamaError("Ollama request exceeded its total timeout.")
        content = "".join(chunks)
        if not content.strip():
            raise OllamaError("Ollama completed without a visible answer.")
        return ChatResult(content, elapsed, first_text, final, thinking)
