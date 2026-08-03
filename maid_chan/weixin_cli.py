"""Deprecated command-line interface for the Tencent Weixin iLink transport."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from .client import ChatClient
from .config import Settings
from .engine import MaidChanEngine
from .memory import MemoryValidationError, load_memories
from .prompt import load_examples
from .weixin import (
    DEFAULT_API_BASE_URL,
    DEFAULT_STATE_PATH,
    WeixinAutoReplyRunner,
    WeixinConfigError,
    WeixinError,
    WeixinIlinkAPI,
    WeixinSessionExpired,
    WeixinStateStore,
    display_qr,
)


def create_parser() -> argparse.ArgumentParser:
    """Create the deprecated iLink subcommand parser."""
    parser = argparse.ArgumentParser(
        prog="maid-chan weixin",
        description="Control the headless Tencent Weixin iLink API transport.",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=None,
        help=f"credential/control state (default: {DEFAULT_STATE_PATH})",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("login", help="authorize once using a terminal QR code")
    commands.add_parser("logout", help="remove the locally stored bot token")
    commands.add_parser("observed", help="list stable sender IDs seen by the worker")
    commands.add_parser("on")
    commands.add_parser("off")

    allow = commands.add_parser("allow")
    allow_commands = allow.add_subparsers(dest="allow_command", required=True)
    allow_commands.add_parser("list")
    add = allow_commands.add_parser("add")
    add.add_argument("user_id")
    add.add_argument("--label", default="")
    add.add_argument(
        "--memory-privacy-level", type=int, choices=range(1, 6), default=1
    )
    remove = allow_commands.add_parser("remove")
    remove.add_argument("user_id")

    send = commands.add_parser("send")
    send.add_argument("user_id")
    send.add_argument("message", nargs="+")

    run = commands.add_parser("run")
    run.add_argument("--api-key")
    run.add_argument("--base-url")
    run.add_argument("--model")
    run.add_argument("--memory-file", type=Path, action="append")
    run.add_argument("--few-shots", type=int, default=8)
    run.add_argument("--history-turns", type=int, default=12)
    run.add_argument("--temperature", type=float, default=0.9)
    run.add_argument("--max-tokens", type=int, default=500)
    run.add_argument("--timeout", type=float, default=60)
    run.add_argument("--thinking", action="store_true")
    return parser


def _status(store: WeixinStateStore) -> None:
    """Print local iLink authentication, cursor, and allowlist state."""
    state = store.load()
    print(f"状态文件：{store.path}")
    print(f"API 授权：{'已授权' if state.authenticated else '未授权'}")
    print(f"自动回复：{'开启' if state.enabled else '关闭'}")
    print(f"账号 ID：{state.account_id or '无'}")
    print(f"允许用户：{len(state.contacts)}")
    print(f"已观察用户：{len(state.observed_users or {})}")
    print(f"服务端游标：{'已建立' if state.sync_cursor else '未建立'}")


def _login(store: WeixinStateStore) -> None:
    """Authorize an iLink bot identity through a terminal QR workflow."""
    existing = store.load()
    api = WeixinIlinkAPI(base_url=DEFAULT_API_BASE_URL)
    qr = api.get_login_qr([existing.token] if existing.token else [])
    qrcode = qr.get("qrcode")
    qr_value = qr.get("qrcode_img_content")
    if not isinstance(qrcode, str) or not isinstance(qr_value, str):
        raise WeixinError("iLink did not return a usable QR code")
    print("请用手机微信扫描并确认授权：")
    display_qr(qr_value)
    verify_code = ""
    current_api = api
    deadline = time.monotonic() + 480
    while time.monotonic() < deadline:
        status = current_api.get_login_status(qrcode, verify_code)
        status_name = status.get("status")
        if status_name == "need_verifycode":
            verify_code = input("请输入手机微信显示的数字：").strip()
            continue
        if status_name == "verify_code_blocked":
            raise WeixinError("verification code was blocked after repeated failures")
        if status_name == "expired":
            raise WeixinError("QR code expired; run login again")
        if status_name == "scaned_but_redirect":
            host = status.get("redirect_host")
            if isinstance(host, str) and host:
                current_api = WeixinIlinkAPI(base_url=f"https://{host}")
            continue
        if status_name == "binded_redirect":
            raise WeixinError(
                "this account is already bound; use the existing state or log out first"
            )
        if status_name == "confirmed":
            token = status.get("bot_token")
            account_id = status.get("ilink_bot_id")
            if not isinstance(token, str) or not isinstance(account_id, str):
                raise WeixinError("login confirmation omitted credentials")
            base_url = status.get("baseurl")
            if isinstance(base_url, str) and base_url and not base_url.startswith(
                ("https://", "http://")
            ):
                base_url = f"https://{base_url}"
            owner = status.get("ilink_user_id")
            state = store.save_login(
                account_id=account_id,
                token=token,
                base_url=base_url if isinstance(base_url, str) else current_api.base_url,
                owner_user_id=owner if isinstance(owner, str) else "",
            )
            print("授权成功。凭据已保存到本地状态文件。")
            if state.owner_user_id:
                print(f"扫码用户稳定 ID：{state.owner_user_id}")
            return
        time.sleep(1)
    raise WeixinError("login timed out")


def _runner(args, store: WeixinStateStore) -> WeixinAutoReplyRunner:
    """Build an iLink auto-reply runner from CLI model options."""
    settings = Settings.from_environment(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        memory_paths=tuple(args.memory_file) if args.memory_file else None,
        few_shot_count=args.few_shots,
        history_turns=args.history_turns,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
        stream=False,
        thinking=args.thinking,
    )
    if not settings.api_key:
        raise WeixinConfigError("set DEEPSEEK_API_KEY or OPENAI_API_KEY")
    examples = load_examples(settings.few_shot_path)
    memories = load_memories(settings.memory_paths)
    engine = MaidChanEngine(ChatClient(settings), settings, examples, memories)
    return WeixinAutoReplyRunner(store, engine)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the deprecated iLink CLI and return a process status code."""
    print(
        "警告：iLink 传输已弃用；它只能操作独立机器人身份，"
        "请改用 `maid-chan wechat ...`。",
        file=sys.stderr,
    )
    args = create_parser().parse_args(argv)
    store = WeixinStateStore(args.state)
    try:
        if args.command == "status":
            _status(store)
        elif args.command == "login":
            _login(store)
        elif args.command == "logout":
            store.clear_login()
            print("本地 iLink 凭据和服务端游标已删除。")
        elif args.command == "observed":
            state = store.load()
            if not state.observed_users:
                print("尚未观察到用户。先运行 `maid-chan weixin run`。")
            else:
                for user_id, seen_at in sorted(state.observed_users.items()):
                    allowed = "已允许" if state.contact(user_id) else "未允许"
                    print(f"{user_id}\t{seen_at}\t{allowed}")
        elif args.command == "on":
            store.set_enabled(True)
            print("无 UI 微信自动回复已开启。")
        elif args.command == "off":
            store.set_enabled(False)
            print("无 UI 微信自动回复已关闭。")
        elif args.command == "allow":
            if args.allow_command == "list":
                state = store.load()
                for item in state.contacts:
                    print(
                        f"{item.user_id}\t{item.label or '-'}\t"
                        f"记忆隐私级别≤{item.memory_privacy_level}"
                    )
            elif args.allow_command == "add":
                store.add_contact(
                    args.user_id, args.label, args.memory_privacy_level
                )
                print(f"已允许稳定用户 ID：{args.user_id}")
            elif args.allow_command == "remove":
                store.remove_contact(args.user_id)
                print(f"已移除稳定用户 ID：{args.user_id}")
        elif args.command == "send":
            state = store.load()
            if not state.authenticated:
                raise WeixinConfigError("authorize with `weixin login` first")
            if state.contact(args.user_id) is None:
                raise WeixinConfigError("manual sends are restricted to allowed users")
            context = (state.context_tokens or {}).get(args.user_id)
            if not context:
                raise WeixinConfigError(
                    "no context token for this user; they must message the bot first"
                )
            WeixinIlinkAPI(
                base_url=state.base_url, token=state.token
            ).send_text(args.user_id, context, " ".join(args.message))
            print("消息已发送。")
        elif args.command == "run":
            _runner(args, store).run_forever()
    except KeyboardInterrupt:
        print("\n无 UI 微信工作进程已停止。")
    except (
        WeixinConfigError,
        WeixinError,
        WeixinSessionExpired,
        MemoryValidationError,
        OSError,
        ValueError,
    ) as exc:
        print(f"微信 API 错误：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
