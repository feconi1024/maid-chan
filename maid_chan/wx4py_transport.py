"""wx4py adapter for foreground WeChat desktop UI automation."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .wechat import WeChatError, WeChatMessage


WX4PY_VERSION = "0.2.1"


class Wx4PyTransport:
    """wx4py adapter for a logged-in foreground WeChat 4.x desktop client."""

    def __init__(self, client_factory: Callable[[], Any] | None = None):
        """Create an adapter with an optional fake client for tests."""
        self._client_factory = client_factory
        self._client: Any = None
        self._outgoing: dict[str, deque[str]] = defaultdict(
            lambda: deque(maxlen=100)
        )

    @staticmethod
    def dependency_available() -> bool:
        """Return whether the pinned ``wx4py`` package is importable."""
        return importlib.util.find_spec("wx4py") is not None

    def connect(self) -> str:
        """Attach to the visible logged-in WeChat 4.x desktop client."""
        if self._client is not None:
            return "wx4py desktop session"
        try:
            if self._client_factory is None:
                from wx4py import WeChatClient

                client = WeChatClient()
            else:
                client = self._client_factory()
            if not client.connect():
                raise WeChatError("wx4py could not connect to the WeChat window")
        except WeChatError:
            raise
        except ImportError as exc:
            raise WeChatError(
                "wx4py is not installed; run `maid-chan wechat install` while "
                "UI mode is selected"
            ) from exc
        except Exception as exc:
            raise WeChatError(
                "wx4py could not attach to WeChat 4.x; log in to the desktop "
                "client, keep its window visible, and try again"
            ) from exc
        self._client = client
        return "wx4py desktop session"

    def disconnect(self) -> None:
        """Disconnect the underlying wx4py client if one is active."""
        client, self._client = self._client, None
        if client is not None:
            try:
                client.disconnect()
            except Exception as exc:
                raise WeChatError(f"wx4py disconnect failed: {exc}") from exc

    def _require_client(self):
        """Return a connected wx4py client, connecting on demand."""
        if self._client is None:
            self.connect()
        return self._client

    def _open_exact_contact(self, contact: str):
        """Open exactly one contact and reject ambiguous partial matches."""
        chat = self._require_client().chat_window
        try:
            results = chat.search(contact)
            contact_results = list(results.get("联系人", ()))
            wanted = contact.casefold()
            exact = [
                item
                for item in contact_results
                if str(getattr(item, "name", "")).casefold()
                == wanted
            ]
            unsafe_partial = [
                item
                for item in [
                    *results.get("最常使用", ()),
                    *contact_results,
                ]
                if wanted in str(getattr(item, "name", "")).casefold()
                and str(getattr(item, "name", "")).casefold()
                != wanted
            ]
            if len(exact) != 1 or unsafe_partial:
                raise WeChatError(
                    f"wx4py could not resolve {contact!r} to one exact contact; "
                    "use a unique exact WeChat remark"
                )
            if not chat.open_chat(
                contact,
                target_type="contact",
                raise_on_target_not_found=True,
            ):
                raise WeChatError(f"wx4py could not open contact {contact!r}")
        except WeChatError:
            raise
        except Exception as exc:
            raise WeChatError(
                f"wx4py could not safely open contact {contact!r}"
            ) from exc
        return chat

    def read_chat(self, contact: str) -> list[WeChatMessage]:
        """Read recent chat history and mark known worker sends as self."""
        chat = self._open_exact_contact(contact)
        try:
            history = chat.get_chat_history(
                contact,
                target_type="contact",
                since="today",
                max_count=100,
            )
        except Exception as exc:
            raise WeChatError(f"wx4py could not read {contact!r}") from exc
        if not isinstance(history, list):
            raise WeChatError("wx4py returned invalid chat history")

        outgoing = Counter(self._outgoing[contact])
        self_indexes: set[int] = set()
        for index in range(len(history) - 1, -1, -1):
            item = history[index]
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "")
            if outgoing[content] > 0:
                self_indexes.add(index)
                outgoing[content] -= 1

        messages: list[WeChatMessage] = []
        for index, item in enumerate(history):
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "")
            message_type = str(item.get("type") or "")
            attr = "self" if index in self_indexes else "friend"
            messages.append(
                WeChatMessage(
                    attr=attr,
                    type=message_type,
                    sender="" if attr == "self" else contact,
                    content=content,
                    timestamp=str(item.get("time") or ""),
                )
            )
        return messages

    def send_text(self, contact: str, text: str) -> None:
        """Send a plain text message through the UI adapter."""
        self.send_payload(contact, text)

    def send_payload(
        self,
        contact: str,
        text: str,
        media_paths: Sequence[Path] = (),
    ) -> None:
        """Send text and optional local files through the UI adapter."""
        chat = self._open_exact_contact(contact)
        try:
            if media_paths:
                success = chat.send_file(
                    [str(path.resolve()) for path in media_paths],
                    message=text or None,
                )
            else:
                success = chat.send_message(text)
        except Exception as exc:
            raise WeChatError(f"wx4py send to {contact!r} failed") from exc
        if not success:
            raise WeChatError(f"wx4py reported that sending to {contact!r} failed")
        if text:
            self._outgoing[contact].append(text)


def install_wx4py(*, output=print) -> None:
    """Install the pinned wx4py dependency into the active Python environment."""
    output(f"Installing wx4py {WX4PY_VERSION} for UI automation...")
    user_args = [] if sys.prefix != sys.base_prefix else ["--user"]
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                *user_args,
                f"wx4py=={WX4PY_VERSION}",
            ],
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WeChatError(f"could not install wx4py: {exc}") from exc


def probe_wx4py(*, output=print) -> None:
    """Verify that wx4py can attach to the current desktop WeChat session."""
    transport = Wx4PyTransport()
    try:
        session = transport.connect()
        output(f"[wx4py] 已连接：{session}")
    finally:
        transport.disconnect()


def send_many_with_wx4py(
    messages: Sequence[tuple[str, str, Sequence[Path]]],
    *,
    output=print,
    transport_factory=Wx4PyTransport,
) -> None:
    """Send multiple messages through one wx4py session."""
    transport = transport_factory()
    try:
        transport.connect()
        for name, text, media in messages:
            transport.send_payload(name, text, media)
            output(f"[wx4py] 已发送给：{name}")
    finally:
        transport.disconnect()
