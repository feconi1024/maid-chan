"""Wechaty Web-protocol runtime management, bridge control, and runner."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from importlib.resources import files
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Iterator, Sequence

from .client import APIError
from .engine import MaidChanEngine
from .wechat import WeChatConfigError, WeChatConfigStore, WeChatError


DEFAULT_RUNTIME_PATH = Path(".maid-chan") / "wechaty-runtime"
DEFAULT_PROFILE_PATH = Path(".maid-chan") / "wechaty-profile"
RUNTIME_FILES = ("bridge.mjs", "package.json", "package-lock.json", "UPSTREAM.md")


def _runtime_path(path: Path | None = None) -> Path:
    """Resolve the local Wechaty runtime directory."""
    configured = os.getenv("MAID_CHAN_WECHATY_RUNTIME")
    return path or (Path(configured) if configured else DEFAULT_RUNTIME_PATH)


def _profile_path(path: Path | None = None) -> Path:
    """Resolve the persistent Wechaty profile directory."""
    configured = os.getenv("MAID_CHAN_WECHATY_PROFILE")
    return path or (Path(configured) if configured else DEFAULT_PROFILE_PATH)


class WechatyRuntime:
    """Manage pinned Node bridge assets and dependency installation."""

    def __init__(
        self,
        runtime_path: Path | None = None,
        profile_path: Path | None = None,
    ):
        """Create a runtime descriptor for bridge files and login profile."""
        self.runtime_path = _runtime_path(runtime_path)
        self.profile_path = _profile_path(profile_path)

    @staticmethod
    def node_available() -> bool:
        """Return whether ``node`` is visible on PATH."""
        return shutil.which("node") is not None

    @staticmethod
    def npm_available() -> bool:
        """Return whether ``npm`` is visible on PATH."""
        return shutil.which("npm") is not None

    @property
    def installed(self) -> bool:
        """Whether the pinned Wechaty dependency tree is present."""
        return (
            (self.runtime_path / "node_modules" / "wechaty").exists()
            and (self.runtime_path / "node_modules" / "wechaty-puppet-wechat4u").exists()
        )

    @property
    def profile_file(self) -> Path:
        """Return the Wechaty memory-card path inside the profile directory."""
        return self.profile_path / "MaidChanWechaty.memory-card.json"

    def quarantine_corrupt_profile(self, *, output=print) -> Path | None:
        """Move an unreadable login profile aside before bridge startup."""
        path = self.profile_file
        if not path.exists():
            return None
        try:
            json.loads(path.read_text(encoding="utf-8"))
            return None
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
            backup = path.with_name(f"{path.name}.{timestamp}.corrupt.bak")
            try:
                os.replace(path, backup)
            except OSError as move_error:
                raise WeChatConfigError(
                    f"could not quarantine corrupt Wechaty profile {path}: "
                    f"{move_error}"
                ) from move_error
            output(
                f"[Wechaty] 登录 profile 损坏，已保留为：{backup}；"
                f"原错误：{exc}"
            )
            return backup

    def prepare_files(self) -> None:
        """Copy bundled bridge assets into the mutable runtime directory."""
        self.runtime_path.mkdir(parents=True, exist_ok=True)
        assets = files("maid_chan.wechaty_runtime")
        for name in RUNTIME_FILES:
            source = assets.joinpath(name).read_bytes()
            destination = self.runtime_path / name
            if not destination.exists() or destination.read_bytes() != source:
                destination.write_bytes(source)

    def install(self, *, output=print) -> None:
        """Install pinned Node dependencies with ``npm ci``."""
        if not self.node_available() or not self.npm_available():
            raise WeChatConfigError("Node.js and npm are required for Wechaty")
        self.prepare_files()
        output(f"[Wechaty] 正在安装运行时依赖：{self.runtime_path}")
        npm_command = shutil.which("npm")
        if not npm_command:
            raise WeChatConfigError("npm is not installed or not on PATH")
        try:
            completed = subprocess.run(
                [npm_command, "ci", "--omit=dev", "--no-audit", "--no-fund"],
                cwd=self.runtime_path,
                check=False,
            )
        except OSError as exc:
            raise WeChatError(f"could not start npm: {exc}") from exc
        if completed.returncode != 0:
            raise WeChatError(f"npm install failed with exit code {completed.returncode}")
        output("[Wechaty] 运行时依赖安装完成")


class WechatyBridge:
    """Line-oriented subprocess bridge to the Node Wechaty runtime."""

    def __init__(
        self,
        runtime: WechatyRuntime,
        *,
        output=print,
        render_qr: bool = True,
    ):
        """Create a bridge controller without starting the process."""
        self.runtime = runtime
        self.output = output
        self.render_qr = render_qr
        self.process: subprocess.Popen[str] | None = None
        self._write_lock = threading.Lock()

    def start(self) -> None:
        """Start the Node bridge process after dependency checks."""
        if not self.runtime.node_available():
            raise WeChatConfigError("Node.js is not installed or not on PATH")
        self.runtime.prepare_files()
        if not self.runtime.installed:
            raise WeChatConfigError(
                "Wechaty runtime is not installed; run `maid-chan wechat install`"
            )
        self.runtime.profile_path.mkdir(parents=True, exist_ok=True)
        self.runtime.quarantine_corrupt_profile(output=self.output)
        node_command = shutil.which("node")
        if not node_command:
            raise WeChatConfigError("Node.js is not installed or not on PATH")
        try:
            self.process = subprocess.Popen(
                [
                    node_command,
                    str((self.runtime.runtime_path / "bridge.mjs").resolve()),
                ],
                cwd=self.runtime.profile_path,
                env={
                    **os.environ,
                    "MAID_CHAN_RENDER_QR": "true" if self.render_qr else "false",
                },
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            raise WeChatError(f"could not start the Wechaty bridge: {exc}") from exc

    def events(self) -> Iterator[dict[str, Any]]:
        """Yield JSON events from the bridge, forwarding plain logs to output."""
        if self.process is None or self.process.stdout is None:
            raise WeChatError("Wechaty bridge is not running")
        for raw_line in self.process.stdout:
            line = raw_line.rstrip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                self.output(line)
                continue
            if isinstance(event, dict):
                yield event
        return_code = self.process.wait()
        if return_code:
            raise WeChatError(f"Wechaty bridge exited with code {return_code}")

    def command(self, command_type: str, **payload: object) -> str:
        """Send one command to the bridge and return its request ID."""
        if self.process is None or self.process.stdin is None:
            raise WeChatError("Wechaty bridge is not running")
        request_id = uuid.uuid4().hex
        command = {"type": command_type, "requestId": request_id, **payload}
        try:
            with self._write_lock:
                self.process.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
                self.process.stdin.flush()
        except OSError as exc:
            raise WeChatError(f"could not write to Wechaty bridge: {exc}") from exc
        return request_id

    def stop(self) -> None:
        """Ask the bridge to stop, escalating to terminate/kill if needed."""
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            self.command("stop")
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired, WeChatError):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


class WechatyAutoReplyRunner:
    """Event-driven auto-reply worker for the Wechaty backend."""

    def __init__(
        self,
        store: WeChatConfigStore,
        bridge: WechatyBridge,
        engine: MaidChanEngine,
        *,
        output=print,
    ):
        """Create a worker bound to a config store, bridge, and reply engine."""
        self.store = store
        self.bridge = bridge
        self.engine = engine
        self.output = output
        self._seen_ids: set[str] = set()
        self._seen_order: deque[str] = deque()

    def _remember(self, message_id: str) -> bool:
        """Return ``True`` only the first time a message ID is observed."""
        if message_id in self._seen_ids:
            return False
        self._seen_ids.add(message_id)
        self._seen_order.append(message_id)
        while len(self._seen_order) > 500:
            self._seen_ids.discard(self._seen_order.popleft())
        return True

    def handle_event(self, event: dict[str, Any]) -> int:
        """Handle one Wechaty bridge event and return replies submitted."""
        event_type = event.get("type")
        if event_type == "scan":
            self.output(
                f"[Wechaty] 请扫描终端二维码：{event.get('statusName', 'Waiting')}"
            )
            return 0
        if event_type == "login":
            user = event.get("user") or {}
            self.output(f"[Wechaty] 已登录：{user.get('name') or user.get('id')}")
            return 0
        if event_type == "logout":
            self.output("[Wechaty] 微信会话已退出")
            return 0
        if event_type in {"error", "fatal"}:
            self.output(
                f"[Wechaty] {event.get('operation', event_type)}："
                f"{event.get('message', 'unknown error')}"
            )
            return 0
        if event_type == "result":
            if not event.get("ok"):
                self.output(f"[Wechaty] 发送失败：{event.get('error', 'unknown error')}")
            return 0
        if event_type != "message":
            return 0

        message_id = str(event.get("id") or "")
        if message_id and not self._remember(message_id):
            return 0
        if event.get("room"):
            return 0
        text = str(event.get("text") or "").strip()
        contact_data = event.get("contact")
        if not text or not isinstance(contact_data, dict):
            return 0
        contact_id = str(contact_data.get("id") or "")
        alias = str(contact_data.get("alias") or "").strip()
        name = str(contact_data.get("name") or "").strip()

        config = self.store.load()
        if not config.enabled or config.mode != "wechaty":
            return 0
        allowed = config.contact(alias) if alias else None
        if allowed is None and name:
            allowed = config.contact(name)
        if allowed is None:
            self.output(f"[Wechaty] 未授权联系人：{alias or name or contact_id}")
            return 0
        try:
            reply = self.engine.reply(
                text,
                conversation_id=f"wechaty:{allowed.name}",
                memory_privacy_level=allowed.memory_privacy_level,
            )
            self.bridge.command("send", contactId=contact_id, text=reply)
        except (APIError, WeChatError) as exc:
            self.output(f"[Wechaty] {allowed.name}: 回复失败：{exc}")
            return 0
        self.output(f"[Wechaty] {allowed.name}: 已提交回复")
        return 1

    def run_forever(self) -> None:
        """Run the event loop until the bridge exits or the operator stops it."""
        self.bridge.start()
        self.output("[Wechaty] 工作进程已启动；登录资料保存在本地 profile 目录")
        try:
            for event in self.bridge.events():
                self.handle_event(event)
        finally:
            self.bridge.stop()


def authenticate(runtime: WechatyRuntime, *, output=print) -> None:
    """Start the bridge long enough to complete QR-code authentication."""
    bridge = WechatyBridge(runtime, output=output)
    bridge.start()
    try:
        for event in bridge.events():
            event_type = event.get("type")
            if event_type == "scan":
                output("[Wechaty] 请扫描终端二维码并在手机确认")
            elif event_type == "login":
                user = event.get("user") or {}
                output(f"[Wechaty] 授权成功：{user.get('name') or user.get('id')}")
                return
            elif event_type == "fatal":
                raise WeChatError(str(event.get("message") or "Wechaty login failed"))
    finally:
        bridge.stop()


def logout_session(
    runtime: WechatyRuntime,
    *,
    output=print,
    bridge_factory=WechatyBridge,
) -> None:
    """Revoke the persisted Wechaty Web session when one exists."""
    bridge = bridge_factory(runtime, output=output, render_qr=False)
    bridge.start()
    request_id = ""
    try:
        for event in bridge.events():
            event_type = event.get("type")
            if event_type in {"started", "scan", "login"} and not request_id:
                request_id = bridge.command("logout")
            elif event_type == "result" and event.get("requestId") == request_id:
                if not event.get("ok"):
                    raise WeChatError(str(event.get("error") or "logout failed"))
                if event.get("remoteAttempted"):
                    output("[Wechaty] 已请求服务端注销当前 Web 会话")
                else:
                    output("[Wechaty] 当前 profile 没有已登录的 Web 会话")
                if event.get("credentialsCleared"):
                    output("[Wechaty] 本地自动登录凭据已清除")
                return
            elif event_type == "fatal":
                raise WeChatError(str(event.get("message") or "Wechaty logout failed"))
    finally:
        bridge.stop()


def probe(runtime: WechatyRuntime, *, timeout: float = 30, output=print) -> str:
    """Check that Wechaty can start and reach login or QR-scan state."""
    bridge = WechatyBridge(runtime, output=output, render_qr=False)
    events: Queue[dict[str, Any] | BaseException] = Queue()

    def read_events() -> None:
        """Copy bridge events into a queue so the probe can time out."""
        try:
            for event in bridge.events():
                events.put(event)
        except BaseException as exc:
            events.put(exc)

    bridge.start()
    reader = threading.Thread(target=read_events, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WeChatError("Wechaty startup probe timed out")
            try:
                item = events.get(timeout=remaining)
            except Empty as exc:
                raise WeChatError("Wechaty startup probe timed out") from exc
            if isinstance(item, BaseException):
                raise WeChatError(str(item)) from item
            event_type = item.get("type")
            if event_type == "scan":
                output("[Wechaty] 协议启动成功，服务端已返回登录二维码")
                return "scan"
            if event_type == "login":
                output("[Wechaty] 协议启动成功，已有登录 profile 可用")
                return "login"
            if event_type == "fatal":
                raise WeChatError(str(item.get("message") or "Wechaty startup failed"))
    finally:
        bridge.stop()
        reader.join(timeout=5)


def send_to_name(
    runtime: WechatyRuntime,
    name: str,
    text: str,
    *,
    media_paths: Sequence[Path] = (),
    output=print,
) -> None:
    """Send one Wechaty message by display name or alias."""
    send_many_to_names(
        runtime,
        [(name, text, tuple(media_paths))],
        output=output,
    )


def send_many_to_names(
    runtime: WechatyRuntime,
    messages: Sequence[tuple[str, str, Sequence[Path]]],
    *,
    output=print,
    bridge_factory=WechatyBridge,
) -> None:
    """Send a sequence of messages through the Wechaty bridge."""
    if not messages:
        raise WeChatConfigError("at least one outbound message is required")
    bridge = bridge_factory(runtime, output=output)
    bridge.start()
    pending: dict[str, str] = {}
    submitted = False
    queue = list(messages)

    def submit_next() -> None:
        """Submit the next queued send after login or previous completion."""
        if not queue:
            return
        name, text, paths = queue.pop(0)
        request_id = bridge.command(
            "sendName",
            name=name,
            text=text,
            files=[str(path.resolve()) for path in paths],
        )
        pending[request_id] = name

    try:
        for event in bridge.events():
            if event.get("type") == "scan":
                output("[Wechaty] 请扫描终端二维码并在手机确认")
            elif event.get("type") == "login":
                if submitted:
                    continue
                submitted = True
                submit_next()
            elif event.get("type") == "result" and event.get("requestId") in pending:
                request_id = str(event.get("requestId"))
                name = pending.pop(request_id)
                if not event.get("ok"):
                    raise WeChatError(
                        f"send to {name!r} failed: "
                        f"{event.get('error') or 'unknown error'}"
                    )
                output(f"[Wechaty] 已发送给：{name}")
                if queue:
                    submit_next()
                elif not pending:
                    return
            elif event.get("type") == "fatal":
                raise WeChatError(str(event.get("message") or "Wechaty failed"))
    finally:
        bridge.stop()
