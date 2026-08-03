"""OpenAI-compatible chat-completions HTTP client.

The module intentionally uses the Python standard library so the base
Maid-chan CLI has no runtime dependencies beyond Python itself.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

from .config import Settings


class APIError(RuntimeError):
    """An OpenAI-compatible API request failed."""


class ChatClient:
    """Small wrapper around a configured Chat Completions endpoint."""

    def __init__(self, settings: Settings):
        """Store immutable request settings shared by all completions."""
        self.settings = settings

    def _request(self, messages: list[dict[str, str]], *, stream: bool):
        """Submit one chat-completions request and return the raw response."""
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
            "stream": stream,
        }
        if self.settings.is_official_deepseek:
            payload["thinking"] = {
                "type": "enabled" if self.settings.thinking else "disabled"
            }
        request = urllib.request.Request(
            self.settings.chat_completions_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if stream else "application/json",
                "User-Agent": "maid-chan-cli/0.1",
            },
            method="POST",
        )
        try:
            return urllib.request.urlopen(request, timeout=self.settings.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(detail)
                detail = parsed.get("error", {}).get("message", detail)
            except (json.JSONDecodeError, AttributeError):
                pass
            raise APIError(f"API returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise APIError(f"Could not connect to the API: {exc.reason}") from exc

    def complete(self, messages: list[dict[str, str]]) -> str:
        """Return one non-streaming assistant message.

        Raises:
            APIError: If the endpoint is unreachable or returns malformed data.
        """
        with self._request(messages, stream=False) as response:
            try:
                data: dict[str, Any] = json.load(response)
                content = data["choices"][0]["message"]["content"]
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                raise APIError("API returned an invalid chat completion response") from exc
        if not isinstance(content, str) or not content.strip():
            raise APIError("API returned an empty response")
        return content.strip()

    def stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        """Yield content chunks from a Server-Sent Events response.

        The method validates each event enough to fail loudly on provider
        schema drift instead of silently printing an incomplete answer.
        """
        received_content = False
        with self._request(messages, stream=True) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                    content = event["choices"][0].get("delta", {}).get("content")
                except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                    raise APIError("API returned an invalid streaming event") from exc
                if content:
                    received_content = True
                    yield str(content)
        if not received_content:
            raise APIError("API returned an empty streamed response")
