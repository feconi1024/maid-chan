"""Shared WeChat configuration, transport protocol, and UI polling runner."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from .client import APIError
from .engine import MaidChanEngine


FORMAT_NAME = "maid-chan-wechat"
FORMAT_VERSION = 1
DEFAULT_CONFIG_PATH = Path(".maid-chan") / "wechat.local.json"
AUTOMATION_MODES = {"ui", "wechaty"}


class WeChatError(RuntimeError):
    """The WeChat transport could not perform an operation."""


class WeChatConfigError(ValueError):
    """The local WeChat control file is invalid."""


@dataclass(frozen=True)
class WeChatContact:
    """One exact allowlisted WeChat contact and its memory visibility ceiling."""

    name: str
    memory_privacy_level: int = 1


@dataclass(frozen=True)
class WeChatConfig:
    """Local operator-controlled WeChat automation settings."""

    enabled: bool = False
    contacts: tuple[WeChatContact, ...] = ()
    poll_interval: float = 2.0
    mode: str = "wechaty"

    def contact(self, name: str) -> WeChatContact | None:
        """Return an allowlisted contact by case-insensitive exact name."""
        wanted = name.casefold()
        return next(
            (contact for contact in self.contacts if contact.name.casefold() == wanted),
            None,
        )


@dataclass(frozen=True)
class WeChatMessage:
    """Normalized message row returned by a WeChat transport."""

    attr: str
    type: str
    sender: str
    content: str
    timestamp: str = ""

    @property
    def fingerprint(self) -> tuple[str, str, str, str, str]:
        """Return stable fields used to align repeated UI history reads."""
        return (self.attr, self.type, self.sender, self.content, self.timestamp)


class WeChatTransport(Protocol):
    """Minimal synchronous transport contract for UI-style polling workers."""

    def connect(self) -> str:
        """Attach to the underlying WeChat session and describe it."""
        ...

    def read_chat(self, contact: str) -> list[WeChatMessage]:
        """Return recent normalized history for one exact contact."""
        ...

    def send_text(self, contact: str, text: str) -> None:
        """Send a text reply to one exact contact."""
        ...


def _config_path(path: Path | None = None) -> Path:
    """Resolve the WeChat control file path from argument or environment."""
    if path is not None:
        return path
    configured = os.getenv("MAID_CHAN_WECHAT_CONFIG")
    return Path(configured) if configured else DEFAULT_CONFIG_PATH


class WeChatConfigStore:
    """Read, validate, and atomically update the local WeChat control file."""

    def __init__(self, path: Path | None = None):
        """Create a store for the selected config path."""
        self.path = _config_path(path)

    def load(self) -> WeChatConfig:
        """Load the current config, returning defaults when absent."""
        if not self.path.exists():
            return WeChatConfig()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise WeChatConfigError(
                f"{self.path}:{exc.lineno}:{exc.colno}: invalid JSON"
            ) from exc
        except OSError as exc:
            raise WeChatConfigError(f"could not read {self.path}: {exc}") from exc
        return parse_wechat_config(data, location=str(self.path))

    def save(self, config: WeChatConfig) -> None:
        """Write a config atomically so workers never read a partial file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "enabled": config.enabled,
            "poll_interval": config.poll_interval,
            "mode": config.mode,
            "contacts": [
                {
                    "name": contact.name,
                    "memory_privacy_level": contact.memory_privacy_level,
                }
                for contact in config.contacts
            ],
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError as exc:
            raise WeChatConfigError(f"could not write {self.path}: {exc}") from exc

    def set_enabled(self, enabled: bool) -> WeChatConfig:
        """Enable or disable automatic replies after safety validation."""
        current = self.load()
        if enabled and not current.contacts:
            raise WeChatConfigError("add at least one allowed contact before enabling")
        updated = WeChatConfig(
            enabled, current.contacts, current.poll_interval, current.mode
        )
        self.save(updated)
        return updated

    def add_contact(self, name: str, memory_privacy_level: int = 1) -> WeChatConfig:
        """Add or update an exact contact allowlist entry."""
        normalized = name.strip()
        if not normalized or len(normalized) > 128:
            raise WeChatConfigError("contact name must contain 1 to 128 characters")
        if not 1 <= memory_privacy_level <= 5:
            raise WeChatConfigError("memory privacy level must be from 1 to 5")
        current = self.load()
        contacts = [
            item for item in current.contacts if item.name.casefold() != normalized.casefold()
        ]
        contacts.append(WeChatContact(normalized, memory_privacy_level))
        updated = WeChatConfig(
            current.enabled,
            tuple(sorted(contacts, key=lambda item: item.name.casefold())),
            current.poll_interval,
            current.mode,
        )
        self.save(updated)
        return updated

    def remove_contact(self, name: str) -> WeChatConfig:
        """Remove a contact and disable replies if the allowlist becomes empty."""
        current = self.load()
        contacts = tuple(
            item for item in current.contacts if item.name.casefold() != name.casefold()
        )
        if len(contacts) == len(current.contacts):
            raise WeChatConfigError(f"contact is not allowed: {name}")
        updated = WeChatConfig(
            current.enabled and bool(contacts),
            contacts,
            current.poll_interval,
            current.mode,
        )
        self.save(updated)
        return updated

    def set_poll_interval(self, seconds: float) -> WeChatConfig:
        """Update the UI polling interval within supported bounds."""
        if not 0.5 <= seconds <= 60:
            raise WeChatConfigError("poll interval must be from 0.5 to 60 seconds")
        current = self.load()
        updated = WeChatConfig(
            current.enabled, current.contacts, float(seconds), current.mode
        )
        self.save(updated)
        return updated

    def set_mode(self, mode: str) -> WeChatConfig:
        """Persist the selected automation backend."""
        normalized = mode.strip().casefold()
        if normalized not in AUTOMATION_MODES:
            raise WeChatConfigError(
                "automation mode must be either 'ui' or 'wechaty'"
            )
        current = self.load()
        updated = WeChatConfig(
            current.enabled,
            current.contacts,
            current.poll_interval,
            normalized,
        )
        self.save(updated)
        return updated


def parse_wechat_config(data: object, *, location: str = "<wechat-config>") -> WeChatConfig:
    """Validate a raw local WeChat configuration object."""
    if not isinstance(data, dict):
        raise WeChatConfigError(f"{location} must be a JSON object")
    allowed = {
        "format",
        "version",
        "enabled",
        "poll_interval",
        "contacts",
        "mode",
    }
    unknown = set(data) - allowed
    if unknown:
        raise WeChatConfigError(
            f"{location} has unsupported fields: {', '.join(sorted(unknown))}"
        )
    if data.get("format") != FORMAT_NAME or data.get("version") != FORMAT_VERSION:
        raise WeChatConfigError(
            f"{location} must use {FORMAT_NAME!r} version {FORMAT_VERSION}"
        )
    enabled = data.get("enabled")
    if not isinstance(enabled, bool):
        raise WeChatConfigError(f"{location}.enabled must be a boolean")
    interval = data.get("poll_interval", 2.0)
    if (
        isinstance(interval, bool)
        or not isinstance(interval, (int, float))
        or not 0.5 <= float(interval) <= 60
    ):
        raise WeChatConfigError(
            f"{location}.poll_interval must be from 0.5 to 60 seconds"
        )
    raw_contacts = data.get("contacts")
    if not isinstance(raw_contacts, list):
        raise WeChatConfigError(f"{location}.contacts must be an array")
    contacts: list[WeChatContact] = []
    names: set[str] = set()
    for index, raw in enumerate(raw_contacts):
        item_location = f"{location}.contacts[{index}]"
        if not isinstance(raw, dict) or set(raw) != {
            "name",
            "memory_privacy_level",
        }:
            raise WeChatConfigError(
                f"{item_location} must contain name and memory_privacy_level"
            )
        name = raw["name"]
        level = raw["memory_privacy_level"]
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 128:
            raise WeChatConfigError(f"{item_location}.name is invalid")
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 5:
            raise WeChatConfigError(
                f"{item_location}.memory_privacy_level must be from 1 to 5"
            )
        folded = name.strip().casefold()
        if folded in names:
            raise WeChatConfigError(f"{item_location} duplicates contact {name!r}")
        names.add(folded)
        contacts.append(WeChatContact(name.strip(), level))
    if enabled and not contacts:
        raise WeChatConfigError(f"{location} cannot be enabled without contacts")
    mode = data.get("mode", "wechaty")
    if not isinstance(mode, str) or mode not in AUTOMATION_MODES:
        raise WeChatConfigError(
            f"{location}.mode must be either 'ui' or 'wechaty'"
        )
    return WeChatConfig(enabled, tuple(contacts), float(interval), mode)


def new_messages(
    previous: Sequence[WeChatMessage],
    current: Sequence[WeChatMessage],
) -> list[WeChatMessage] | None:
    """Return appended messages, or None when the view cannot be aligned safely."""
    old = [item.fingerprint for item in previous]
    new = [item.fingerprint for item in current]
    if not old:
        return list(current)
    if len(new) >= len(old) and new[: len(old)] == old:
        return list(current[len(old) :])
    maximum = min(len(old), len(new))
    for overlap in range(maximum, 0, -1):
        if old[-overlap:] == new[:overlap]:
            return list(current[overlap:])
    return None


class WeChatAutoReplyRunner:
    """Poll a UI transport and reply only to newly appended friend messages."""

    def __init__(
        self,
        store: WeChatConfigStore,
        transport: WeChatTransport,
        engine: MaidChanEngine,
        *,
        output=print,
    ):
        """Create a foreground auto-reply worker."""
        self.store = store
        self.transport = transport
        self.engine = engine
        self.output = output
        self._snapshots: dict[str, list[WeChatMessage]] = {}
        self._last_enabled: bool | None = None

    def poll_once(self) -> int:
        """Poll configured contacts once and return the number of replies sent."""
        config = self.store.load()
        active = config.enabled and config.mode == "ui"
        if active != self._last_enabled:
            self._snapshots.clear()
            self._last_enabled = active
        configured_names = {contact.name for contact in config.contacts}
        for name in set(self._snapshots) - configured_names:
            self._snapshots.pop(name, None)
            self.engine.reset(f"wechat:{name}")
        if not active:
            return 0

        replies = 0
        for contact in config.contacts:
            try:
                current = self.transport.read_chat(contact.name)
            except WeChatError as exc:
                self.output(f"[微信] {contact.name}: {exc}")
                continue
            previous = self._snapshots.get(contact.name)
            self._snapshots[contact.name] = current
            if previous is None:
                self.output(f"[微信] {contact.name}: 已建立消息基线，不回复历史消息")
                continue
            delta = new_messages(previous, current)
            if delta is None:
                self.output(f"[微信] {contact.name}: 消息窗口无法安全对齐，已重新建立基线")
                continue
            incoming = [
                item.content.strip()
                for item in delta
                if item.attr == "friend"
                and item.type == "text"
                and item.content.strip()
            ]
            if not incoming:
                continue
            user_message = "\n".join(incoming[-5:])
            try:
                reply = self.engine.reply(
                    user_message,
                    conversation_id=f"wechat:{contact.name}",
                    memory_privacy_level=contact.memory_privacy_level,
                )
                self.transport.send_text(contact.name, reply)
            except (APIError, WeChatError) as exc:
                self.output(f"[微信] {contact.name}: 回复失败：{exc}")
                continue
            replies += 1
            self.output(f"[微信] {contact.name}: 已回复")
        return replies

    def run_forever(self) -> None:
        """Run the UI polling worker until interrupted by the operator."""
        session = self.transport.connect()
        self.output(f"[微信] 已连接：{session}")
        last_reported_enabled: bool | None = None
        try:
            while True:
                config = self.store.load()
                active = config.enabled and config.mode == "ui"
                if active != last_reported_enabled:
                    self.output(
                        "[微信] UI 自动回复已开启"
                        if active
                        else "[微信] UI 模式待机中"
                    )
                    last_reported_enabled = active
                self.poll_once()
                time.sleep(config.poll_interval)
        finally:
            disconnect = getattr(self.transport, "disconnect", None)
            if callable(disconnect):
                disconnect()
