"""Deprecated Tencent Weixin iLink transport and worker implementation.

The iLink path uses an independent bot identity and remains only as a migration
bridge. New personal-account automation should go through ``maid_chan.wechat``.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import APIError
from .engine import MaidChanEngine


FORMAT_NAME = "maid-chan-weixin-ilink"
FORMAT_VERSION = 1
DEFAULT_STATE_PATH = Path(".maid-chan") / "weixin-ilink.local.json"
DEFAULT_API_BASE_URL = "https://ilinkai.weixin.qq.com"
ILINK_APP_ID = "bot"
ILINK_CHANNEL_VERSION = "2.4.6"
ILINK_CLIENT_VERSION = (2 << 16) | (4 << 8) | 6
BOT_AGENT = "MaidChan/0.1.0"


class WeixinError(RuntimeError):
    """The direct Weixin iLink transport failed."""


class WeixinConfigError(ValueError):
    """The local iLink state file is invalid."""


class WeixinSessionExpired(WeixinError):
    """The persisted iLink bot token must be authorized again."""


class WeixinPollTimeout(WeixinError):
    """A normal iLink long poll ended without an update."""


@dataclass(frozen=True)
class WeixinContact:
    """One allowlisted iLink user ID and its memory visibility ceiling."""

    user_id: str
    label: str = ""
    memory_privacy_level: int = 1


@dataclass(frozen=True)
class WeixinState:
    """Persisted iLink credentials, cursor, allowlist, and runtime caches."""

    enabled: bool = False
    account_id: str = ""
    token: str = ""
    base_url: str = DEFAULT_API_BASE_URL
    owner_user_id: str = ""
    sync_cursor: str = ""
    contacts: tuple[WeixinContact, ...] = ()
    context_tokens: dict[str, str] | None = None
    observed_users: dict[str, str] | None = None

    @property
    def authenticated(self) -> bool:
        """Whether this state contains the credentials needed for API calls."""
        return bool(self.account_id and self.token)

    def contact(self, user_id: str) -> WeixinContact | None:
        """Return the allowlisted contact matching a stable iLink user ID."""
        return next((item for item in self.contacts if item.user_id == user_id), None)


def _clean_string(value: object, location: str, maximum: int = 512) -> str:
    """Validate and trim a bounded string from the state file."""
    if not isinstance(value, str):
        raise WeixinConfigError(f"{location} must be a string")
    result = value.strip()
    if len(result) > maximum:
        raise WeixinConfigError(f"{location} exceeds {maximum} characters")
    return result


def parse_weixin_state(data: object, *, location: str = "<weixin-state>") -> WeixinState:
    """Validate a raw iLink state JSON object."""
    if not isinstance(data, dict):
        raise WeixinConfigError(f"{location} must be a JSON object")
    allowed = {
        "format",
        "version",
        "enabled",
        "account",
        "sync_cursor",
        "contacts",
        "context_tokens",
        "observed_users",
    }
    unknown = set(data) - allowed
    if unknown:
        raise WeixinConfigError(
            f"{location} has unsupported fields: {', '.join(sorted(unknown))}"
        )
    if data.get("format") != FORMAT_NAME or data.get("version") != FORMAT_VERSION:
        raise WeixinConfigError(
            f"{location} must use {FORMAT_NAME!r} version {FORMAT_VERSION}"
        )
    enabled = data.get("enabled")
    if not isinstance(enabled, bool):
        raise WeixinConfigError(f"{location}.enabled must be a boolean")
    account = data.get("account")
    if not isinstance(account, dict):
        raise WeixinConfigError(f"{location}.account must be an object")
    if set(account) - {"account_id", "token", "base_url", "owner_user_id"}:
        raise WeixinConfigError(f"{location}.account has unsupported fields")
    account_id = _clean_string(account.get("account_id", ""), f"{location}.account_id")
    token = _clean_string(account.get("token", ""), f"{location}.token", 4096)
    base_url = _clean_string(
        account.get("base_url", DEFAULT_API_BASE_URL), f"{location}.base_url", 2048
    )
    owner_user_id = _clean_string(
        account.get("owner_user_id", ""), f"{location}.owner_user_id"
    )
    parsed_url = urllib.parse.urlparse(base_url)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise WeixinConfigError(f"{location}.base_url must be an HTTPS URL")

    raw_contacts = data.get("contacts", [])
    if not isinstance(raw_contacts, list):
        raise WeixinConfigError(f"{location}.contacts must be an array")
    contacts: list[WeixinContact] = []
    contact_ids: set[str] = set()
    for index, raw in enumerate(raw_contacts):
        item_location = f"{location}.contacts[{index}]"
        if not isinstance(raw, dict) or set(raw) - {
            "user_id",
            "label",
            "memory_privacy_level",
        }:
            raise WeixinConfigError(f"{item_location} is invalid")
        user_id = _clean_string(raw.get("user_id"), f"{item_location}.user_id")
        if not user_id:
            raise WeixinConfigError(f"{item_location}.user_id cannot be empty")
        if user_id in contact_ids:
            raise WeixinConfigError(f"{item_location} duplicates {user_id!r}")
        level = raw.get("memory_privacy_level", 1)
        if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 5:
            raise WeixinConfigError(
                f"{item_location}.memory_privacy_level must be from 1 to 5"
            )
        contacts.append(
            WeixinContact(
                user_id,
                _clean_string(raw.get("label", ""), f"{item_location}.label", 128),
                level,
            )
        )
        contact_ids.add(user_id)

    def string_map(key: str, value_maximum: int) -> dict[str, str]:
        """Validate a string-to-string runtime cache map."""
        raw_map = data.get(key, {})
        if not isinstance(raw_map, dict):
            raise WeixinConfigError(f"{location}.{key} must be an object")
        result: dict[str, str] = {}
        for raw_key, raw_value in raw_map.items():
            map_key = _clean_string(raw_key, f"{location}.{key} key")
            map_value = _clean_string(
                raw_value, f"{location}.{key}[{map_key!r}]", value_maximum
            )
            if map_key and map_value:
                result[map_key] = map_value
        return result

    state = WeixinState(
        enabled=enabled,
        account_id=account_id,
        token=token,
        base_url=base_url,
        owner_user_id=owner_user_id,
        sync_cursor=_clean_string(
            data.get("sync_cursor", ""), f"{location}.sync_cursor", 1_000_000
        ),
        contacts=tuple(contacts),
        context_tokens=string_map("context_tokens", 4096),
        observed_users=string_map("observed_users", 64),
    )
    if state.enabled and (not state.authenticated or not state.contacts):
        raise WeixinConfigError(
            f"{location} cannot be enabled without authentication and contacts"
        )
    return state


class WeixinStateStore:
    """Read and atomically update the deprecated iLink state file."""

    def __init__(self, path: Path | None = None):
        """Create a store using an explicit path or environment override."""
        configured = os.getenv("MAID_CHAN_WEIXIN_STATE")
        self.path = path or (Path(configured) if configured else DEFAULT_STATE_PATH)

    def worker_lease(self) -> WeixinWorkerLease:
        """Return the lock object used to guard the long-poll cursor."""
        return WeixinWorkerLease(self.path.with_suffix(self.path.suffix + ".run.lock"))

    def load(self) -> WeixinState:
        """Load state from disk, returning unauthenticated defaults if absent."""
        if not self.path.exists():
            return WeixinState(context_tokens={}, observed_users={})
        try:
            return parse_weixin_state(
                json.loads(self.path.read_text(encoding="utf-8")),
                location=str(self.path),
            )
        except json.JSONDecodeError as exc:
            raise WeixinConfigError(
                f"{self.path}:{exc.lineno}:{exc.colno}: invalid JSON"
            ) from exc
        except OSError as exc:
            raise WeixinConfigError(f"could not read {self.path}: {exc}") from exc

    def save(self, state: WeixinState) -> None:
        """Write state atomically and best-effort restrict file permissions."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "format": FORMAT_NAME,
            "version": FORMAT_VERSION,
            "enabled": state.enabled,
            "account": {
                "account_id": state.account_id,
                "token": state.token,
                "base_url": state.base_url,
                "owner_user_id": state.owner_user_id,
            },
            "sync_cursor": state.sync_cursor,
            "contacts": [
                {
                    "user_id": item.user_id,
                    "label": item.label,
                    "memory_privacy_level": item.memory_privacy_level,
                }
                for item in state.contacts
            ],
            "context_tokens": state.context_tokens or {},
            "observed_users": state.observed_users or {},
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
        except OSError as exc:
            raise WeixinConfigError(f"could not write {self.path}: {exc}") from exc

    def set_enabled(self, enabled: bool) -> WeixinState:
        """Enable or disable replies after credential and allowlist checks."""
        state = self.load()
        if enabled and not state.authenticated:
            raise WeixinConfigError("authorize with `weixin login` first")
        if enabled and not state.contacts:
            raise WeixinConfigError("allow at least one stable user ID first")
        updated = replace(state, enabled=enabled)
        self.save(updated)
        return updated

    def add_contact(
        self, user_id: str, label: str = "", memory_privacy_level: int = 1
    ) -> WeixinState:
        """Add or update one stable iLink user ID in the allowlist."""
        user_id = user_id.strip()
        if not user_id or len(user_id) > 512:
            raise WeixinConfigError("user ID must contain 1 to 512 characters")
        if not 1 <= memory_privacy_level <= 5:
            raise WeixinConfigError("memory privacy level must be from 1 to 5")
        state = self.load()
        contacts = [item for item in state.contacts if item.user_id != user_id]
        contacts.append(WeixinContact(user_id, label.strip(), memory_privacy_level))
        updated = replace(
            state, contacts=tuple(sorted(contacts, key=lambda item: item.user_id))
        )
        self.save(updated)
        return updated

    def remove_contact(self, user_id: str) -> WeixinState:
        """Remove one stable user ID and disable replies if none remain."""
        state = self.load()
        contacts = tuple(item for item in state.contacts if item.user_id != user_id)
        if len(contacts) == len(state.contacts):
            raise WeixinConfigError(f"user ID is not allowed: {user_id}")
        updated = replace(state, contacts=contacts, enabled=state.enabled and bool(contacts))
        self.save(updated)
        return updated

    def save_login(
        self,
        *,
        account_id: str,
        token: str,
        base_url: str,
        owner_user_id: str,
    ) -> WeixinState:
        """Persist freshly authorized iLink credentials and reset runtime data."""
        state = self.load()
        updated = replace(
            state,
            enabled=False,
            account_id=account_id,
            token=token,
            base_url=base_url or DEFAULT_API_BASE_URL,
            owner_user_id=owner_user_id,
            sync_cursor="",
            context_tokens={},
            observed_users={},
        )
        self.save(updated)
        return updated

    def clear_login(self) -> WeixinState:
        """Remove credentials, cursor, and cached per-user context tokens."""
        state = self.load()
        updated = replace(
            state,
            enabled=False,
            account_id="",
            token="",
            base_url=DEFAULT_API_BASE_URL,
            owner_user_id="",
            sync_cursor="",
            context_tokens={},
            observed_users={},
        )
        self.save(updated)
        return updated

    def save_runtime(
        self,
        *,
        sync_cursor: str,
        context_tokens: dict[str, str],
        observed_users: dict[str, str],
    ) -> WeixinState:
        """Persist long-poll cursor and per-user reply context tokens."""
        current = self.load()
        updated = replace(
            current,
            sync_cursor=sync_cursor,
            context_tokens=context_tokens,
            observed_users=observed_users,
        )
        self.save(updated)
        return updated


class WeixinWorkerLease:
    """Prevent two local workers from consuming the same persisted cursor."""

    def __init__(self, path: Path):
        """Create a filesystem lock owned by the current process ID."""
        self.path = path
        self.pid = os.getpid()
        self.acquired = False

    @staticmethod
    def _pid_is_running(pid: int) -> bool:
        """Return whether a process ID appears to still be alive."""
        if pid <= 0:
            return False
        if os.name == "nt":
            import ctypes

            process_query_limited_information = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                process_query_limited_information, False, pid
            )
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def __enter__(self) -> WeixinWorkerLease:
        """Acquire the worker lease, clearing a stale lock when safe."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _attempt in range(2):
            try:
                descriptor = os.open(
                    self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
            except FileExistsError:
                try:
                    owner = int(self.path.read_text(encoding="ascii").strip())
                except (OSError, ValueError):
                    owner = -1
                if self._pid_is_running(owner):
                    raise WeixinConfigError(
                        f"another local Weixin worker is already running (PID {owner})"
                    )
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    raise WeixinConfigError(
                        f"could not clear stale worker lock {self.path}: {exc}"
                    ) from exc
                continue
            try:
                os.write(descriptor, f"{self.pid}\n".encode("ascii"))
            finally:
                os.close(descriptor)
            self.acquired = True
            return self
        raise WeixinConfigError(f"could not acquire worker lock {self.path}")

    def __exit__(self, *_args: object) -> None:
        """Release the worker lease if it is still owned by this process."""
        if not self.acquired:
            return
        try:
            owner = int(self.path.read_text(encoding="ascii").strip())
            if owner == self.pid:
                self.path.unlink()
        except (FileNotFoundError, OSError, ValueError):
            pass
        self.acquired = False


class WeixinIlinkAPI:
    """Minimal HTTP client for the deprecated iLink bot API."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_API_BASE_URL,
        token: str = "",
        timeout: float = 45.0,
    ):
        """Create an iLink API client for one base URL and token."""
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    @staticmethod
    def _base_info() -> dict[str, object]:
        """Return common iLink channel metadata for request bodies."""
        return {"channel_version": ILINK_CHANNEL_VERSION, "bot_agent": BOT_AGENT}

    @staticmethod
    def _common_headers(*, authenticated: bool) -> dict[str, str]:
        """Build shared iLink headers for authenticated or public endpoints."""
        headers = {
            "iLink-App-Id": ILINK_APP_ID,
            "iLink-App-ClientVersion": str(ILINK_CLIENT_VERSION),
        }
        if authenticated:
            random_uin = str(secrets.randbits(32)).encode("ascii")
            headers.update(
                {
                    "Content-Type": "application/json",
                    "AuthorizationType": "ilink_bot_token",
                    "X-WECHAT-UIN": base64.b64encode(random_uin).decode("ascii"),
                }
            )
        return headers

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        body: dict[str, object] | None = None,
        authenticated: bool = True,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send one iLink request and return its JSON object response."""
        url = urllib.parse.urljoin(self.base_url + "/", endpoint)
        headers = self._common_headers(authenticated=authenticated)
        if method == "POST":
            random_uin = str(secrets.randbits(32)).encode("ascii")
            headers.update(
                {
                    "Content-Type": "application/json",
                    "AuthorizationType": "ilink_bot_token",
                    "X-WECHAT-UIN": base64.b64encode(random_uin).decode("ascii"),
                }
            )
        if authenticated:
            if not self.token:
                raise WeixinSessionExpired("no iLink bot token is configured")
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            url,
            data=(
                json.dumps(body, ensure_ascii=False).encode("utf-8")
                if body is not None
                else None
            ),
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request, timeout=timeout if timeout is not None else self.timeout
            ) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise WeixinError(f"iLink HTTP {exc.code}: {detail}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise WeixinPollTimeout("iLink long poll timed out") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise WeixinPollTimeout("iLink long poll timed out") from exc
            raise WeixinError(f"could not reach the iLink API: {exc.reason}") from exc
        except (json.JSONDecodeError, TypeError) as exc:
            raise WeixinError("iLink returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise WeixinError("iLink returned a non-object response")
        return payload

    def get_login_qr(self, local_tokens: list[str] | None = None) -> dict[str, Any]:
        """Request a QR-code login challenge."""
        return self._request(
            "POST",
            "ilink/bot/get_bot_qrcode?bot_type=3",
            body={"local_token_list": local_tokens or []},
            authenticated=False,
        )

    def get_login_status(self, qrcode: str, verify_code: str = "") -> dict[str, Any]:
        """Poll the QR-code login status, optionally with a verification code."""
        query = urllib.parse.urlencode(
            {"qrcode": qrcode, **({"verify_code": verify_code} if verify_code else {})}
        )
        return self._request(
            "GET",
            f"ilink/bot/get_qrcode_status?{query}",
            authenticated=False,
            timeout=40,
        )

    def get_updates(
        self, cursor: str, long_poll_timeout_ms: int = 35_000
    ) -> dict[str, Any]:
        """Long-poll for inbound iLink messages from the current cursor."""
        try:
            return self._request(
                "POST",
                "ilink/bot/getupdates",
                body={"get_updates_buf": cursor, "base_info": self._base_info()},
                timeout=max(5.0, long_poll_timeout_ms / 1000 + 10),
            )
        except WeixinPollTimeout:
            # An empty long poll is expected. Keep the current cursor and continue.
            return {"ret": 0, "msgs": [], "get_updates_buf": cursor}

    def _notify_lifecycle(self, endpoint: str) -> None:
        """Notify iLink that a bot worker started or stopped."""
        response = self._request(
            "POST",
            endpoint,
            body={"base_info": self._base_info()},
        )
        if response.get("ret") not in {None, 0}:
            raise WeixinError(
                f"{endpoint.rsplit('/', 1)[-1]} failed: ret={response.get('ret')} "
                f"{response.get('errmsg', '')}".strip()
            )

    def notify_start(self) -> None:
        """Notify iLink that the worker is starting."""
        self._notify_lifecycle("ilink/bot/msg/notifystart")

    def notify_stop(self) -> None:
        """Notify iLink that the worker is stopping."""
        self._notify_lifecycle("ilink/bot/msg/notifystop")

    def send_text(self, user_id: str, context_token: str, text: str) -> None:
        """Send a text message to an allowlisted stable iLink user ID."""
        response = self._request(
            "POST",
            "ilink/bot/sendmessage",
            body={
                "msg": {
                    "to_user_id": user_id,
                    "context_token": context_token,
                    "item_list": [{"type": 1, "text_item": {"text": text}}],
                },
                "base_info": self._base_info(),
            },
        )
        if response.get("ret") not in {None, 0}:
            raise WeixinError(
                f"send failed: ret={response.get('ret')} "
                f"{response.get('errmsg', '')}".strip()
            )


def display_qr(value: str) -> None:
    """Render a QR code in the terminal when the optional dependency exists."""
    try:
        import qrcode
    except ImportError:
        print("未安装 qrcode，无法在终端绘制二维码。请打开以下链接：")
        print(value)
        return
    qr = qrcode.QRCode(border=1)
    qr.add_data(value)
    qr.make(fit=True)
    qr.print_ascii(out=sys.stdout, tty=True)
    print(value)


def _now_text() -> str:
    """Return the current UTC timestamp in compact RFC 3339 form."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text_from_message(message: dict[str, Any]) -> str:
    """Extract text items from an iLink message payload."""
    parts: list[str] = []
    for item in message.get("item_list") or []:
        if not isinstance(item, dict) or item.get("type") != 1:
            continue
        text_item = item.get("text_item")
        if isinstance(text_item, dict) and isinstance(text_item.get("text"), str):
            text = text_item["text"].strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


class WeixinAutoReplyRunner:
    """Long-polling auto-reply worker for the deprecated iLink transport."""

    def __init__(
        self,
        store: WeixinStateStore,
        engine: MaidChanEngine,
        *,
        output=print,
        api_factory=WeixinIlinkAPI,
    ):
        """Create an iLink worker with injectable API factory for tests."""
        self.store = store
        self.engine = engine
        self.output = output
        self.api_factory = api_factory
        self.long_poll_timeout_ms = 35_000

    def poll_once(self) -> int:
        """Poll iLink once and return the number of replies sent."""
        initial = self.store.load()
        if not initial.authenticated:
            raise WeixinSessionExpired("authorize with `weixin login` first")
        api = self.api_factory(base_url=initial.base_url, token=initial.token)
        response = api.get_updates(initial.sync_cursor, self.long_poll_timeout_ms)
        if response.get("ret") == -14 or response.get("errcode") == -14:
            raise WeixinSessionExpired("iLink session expired; run `weixin login` again")
        if response.get("ret") not in {None, 0}:
            raise WeixinError(
                f"getUpdates failed: ret={response.get('ret')} "
                f"{response.get('errmsg', '')}".strip()
            )
        suggested_timeout = response.get("longpolling_timeout_ms")
        if (
            isinstance(suggested_timeout, int)
            and not isinstance(suggested_timeout, bool)
            and 1_000 <= suggested_timeout <= 120_000
        ):
            self.long_poll_timeout_ms = suggested_timeout
        new_cursor = response.get("get_updates_buf")
        if not isinstance(new_cursor, str):
            new_cursor = initial.sync_cursor
        contexts = dict(initial.context_tokens or {})
        observed = dict(initial.observed_users or {})
        messages = response.get("msgs") or []
        if not isinstance(messages, list):
            raise WeixinError("getUpdates returned an invalid message list")

        candidates: list[tuple[str, str, str]] = []
        for raw_message in messages:
            if not isinstance(raw_message, dict) or raw_message.get("message_type") == 2:
                continue
            user_id = raw_message.get("from_user_id")
            if not isinstance(user_id, str) or not user_id:
                continue
            observed[user_id] = _now_text()
            context_token = raw_message.get("context_token")
            if isinstance(context_token, str) and context_token:
                contexts[user_id] = context_token
            text = _text_from_message(raw_message)
            if text and contexts.get(user_id):
                candidates.append((user_id, contexts[user_id], text))

        current = self.store.save_runtime(
            sync_cursor=new_cursor,
            context_tokens=contexts,
            observed_users=observed,
        )
        if not initial.sync_cursor:
            if messages:
                self.output("[微信 API] 已建立服务端游标，不回复首次同步中的消息")
            return 0
        if not current.enabled:
            return 0

        replies = 0
        for user_id, context_token, text in candidates:
            contact = current.contact(user_id)
            if contact is None:
                self.output(f"[微信 API] 未授权用户：{user_id}")
                continue
            try:
                reply = self.engine.reply(
                    text,
                    conversation_id=f"weixin:{current.account_id}:{user_id}",
                    memory_privacy_level=contact.memory_privacy_level,
                )
                api.send_text(user_id, context_token, reply)
            except (APIError, WeixinError) as exc:
                self.output(f"[微信 API] {contact.label or user_id}: 回复失败：{exc}")
                continue
            replies += 1
            self.output(f"[微信 API] {contact.label or user_id}: 已回复")
        return replies

    def run_forever(self) -> None:
        """Run the iLink worker loop until interrupted or credentials expire."""
        with self.store.worker_lease():
            state = self.store.load()
            if not state.authenticated:
                raise WeixinSessionExpired("authorize with `weixin login` first")
            lifecycle_api = self.api_factory(base_url=state.base_url, token=state.token)
            lifecycle_api.notify_start()
            self.output("[微信 API] 无 UI 长轮询工作进程已启动")
            failures = 0
            try:
                while True:
                    try:
                        self.poll_once()
                        failures = 0
                    except WeixinSessionExpired:
                        raise
                    except WeixinError as exc:
                        failures += 1
                        delay = min(30, 2**min(failures, 5))
                        self.output(f"[微信 API] {exc}；{delay} 秒后重试")
                        time.sleep(delay)
            finally:
                try:
                    lifecycle_api.notify_stop()
                except WeixinError as exc:
                    self.output(f"[微信 API] 停止通知失败：{exc}")
