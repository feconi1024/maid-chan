"""Standalone CLI for WeChat transports, actions, and workers."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .client import APIError, ChatClient
from .config import DEFAULT_BASE_URL, DEFAULT_MODEL, Settings
from .engine import MaidChanEngine
from .memory import MemoryValidationError, load_memories
from .moments_transport import PyWeixinMomentsPublisher, install_pywechat
from .prompt import load_examples
from .wechat import (
    DEFAULT_CONFIG_PATH,
    WeChatAutoReplyRunner,
    WeChatConfigError,
    WeChatConfigStore,
    WeChatError,
)
from .wechat_actions import (
    PostMomentAction,
    SendMessageAction,
    WeChatActionError,
    WeChatActionPlanner,
    assert_executable,
    parse_action_plan,
    resolve_message_media,
)
from .wechat_drafting import MessageDraftingSession, run_interactive_drafting
from .wechaty import (
    DEFAULT_PROFILE_PATH,
    DEFAULT_RUNTIME_PATH,
    WechatyAutoReplyRunner,
    WechatyBridge,
    WechatyRuntime,
    authenticate,
    logout_session,
    probe,
    send_many_to_names,
    send_to_name,
)
from .wx4py_transport import (
    Wx4PyTransport,
    install_wx4py,
    probe_wx4py,
    send_many_with_wx4py,
)


def create_parser() -> argparse.ArgumentParser:
    """Create the WeChat subcommand parser."""
    parser = argparse.ArgumentParser(
        prog="maid-chan wechat",
        description=(
            "Control Maid-chan's selectable wx4py UI or Wechaty transport."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"control file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--runtime",
        type=Path,
        default=None,
        help=f"Node runtime directory (default: {DEFAULT_RUNTIME_PATH})",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help=f"persistent Wechaty profile directory (default: {DEFAULT_PROFILE_PATH})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="show toggle, allowlist, and dependency status")
    mode = subparsers.add_parser(
        "mode", help="show or select the automation transport"
    )
    mode.add_argument("value", nargs="?", choices=("ui", "wechaty"))
    subparsers.add_parser(
        "capabilities", help="show supported outbound operation capabilities"
    )
    subparsers.add_parser("install", help="install the selected mode's runtime")
    doctor = subparsers.add_parser(
        "doctor", help="probe protocol startup without completing login"
    )
    doctor.add_argument("--timeout", type=float, default=30)
    auth = subparsers.add_parser(
        "auth", help="verify UI login or authorize the persistent Wechaty session"
    )
    auth.add_argument("--accept-account-risk", action="store_true")
    subparsers.add_parser(
        "logout", help="revoke the selected mode's separate automation session"
    )
    subparsers.add_parser("on", help="enable replies for allowed contacts")
    subparsers.add_parser("off", help="disable all automatic replies")

    allow = subparsers.add_parser("allow", help="manage allowed contacts")
    allow_subparsers = allow.add_subparsers(dest="allow_command", required=True)
    allow_subparsers.add_parser("list", help="list allowed contacts")
    add = allow_subparsers.add_parser("add", help="allow one exact contact remark")
    add.add_argument("name")
    add.add_argument(
        "--memory-privacy-level",
        type=int,
        choices=range(1, 6),
        default=1,
        help="maximum external-memory rating visible in replies (default: 1)",
    )
    remove = allow_subparsers.add_parser("remove", help="remove an allowed contact")
    remove.add_argument("name")

    send = subparsers.add_parser(
        "send", help="send text and/or local media to an allowed contact"
    )
    send.add_argument("name")
    send.add_argument("message", nargs="*")
    send.add_argument("--media", type=Path, action="append", default=[])
    send.add_argument("--media-root", type=Path, action="append", default=[])
    send.add_argument("--accept-account-risk", action="store_true")

    moment = subparsers.add_parser(
        "moment", help="publish a public/default-visibility Moment in UI mode"
    )
    moment.add_argument("text", nargs="*")
    moment.add_argument("--media", type=Path, action="append", default=[])
    moment.add_argument("--media-root", type=Path, action="append", default=[])
    moment.add_argument("--dry-run", action="store_true")
    moment.add_argument("--yes", action="store_true")
    moment.add_argument("--accept-account-risk", action="store_true")

    act = subparsers.add_parser(
        "act", help="plan outbound actions from a natural-language prompt"
    )
    act.add_argument("prompt", nargs="+")
    act.add_argument("--api-key")
    act.add_argument("--base-url", default=None, help=f"default: {DEFAULT_BASE_URL}")
    act.add_argument("--model", default=None, help=f"default: {DEFAULT_MODEL}")
    act.add_argument("--timeout", type=float, default=60.0)
    act.add_argument("--media-root", type=Path, action="append", default=[])
    act.add_argument("--dry-run", action="store_true")
    act.add_argument("--yes", action="store_true")
    act.add_argument("--accept-account-risk", action="store_true")

    compose = subparsers.add_parser(
        "compose", help="interactively draft, revise, preview, and send one message"
    )
    compose.add_argument("name")
    compose.add_argument("instruction", nargs="*")
    compose.add_argument("--api-key")
    compose.add_argument(
        "--base-url", default=None, help=f"default: {DEFAULT_BASE_URL}"
    )
    compose.add_argument("--model", default=None, help=f"default: {DEFAULT_MODEL}")
    compose.add_argument("--memory-file", type=Path, action="append", default=None)
    compose.add_argument("--few-shots", type=int, default=4)
    compose.add_argument("--history-turns", type=int, default=8)
    compose.add_argument("--timeout", type=float, default=60.0)
    compose.add_argument("--media", type=Path, action="append", default=[])
    compose.add_argument("--media-root", type=Path, action="append", default=[])
    compose.add_argument("--accept-account-risk", action="store_true")

    run = subparsers.add_parser("run", help="run the selected auto-reply worker")
    run.add_argument("--accept-account-risk", action="store_true")
    run.add_argument("--api-key")
    run.add_argument("--base-url", default=None, help=f"default: {DEFAULT_BASE_URL}")
    run.add_argument("--model", default=None, help=f"default: {DEFAULT_MODEL}")
    run.add_argument("--memory-file", type=Path, action="append", default=None)
    run.add_argument("--few-shots", type=int, default=8)
    run.add_argument("--history-turns", type=int, default=12)
    run.add_argument("--temperature", type=float, default=0.9)
    run.add_argument("--max-tokens", type=int, default=500)
    run.add_argument("--timeout", type=float, default=60.0)
    run.add_argument("--thinking", action="store_true")
    return parser


def _print_runtime_status(
    store: WeChatConfigStore, runtime: WechatyRuntime
) -> None:
    """Print selected backend, dependencies, and allowlist state."""
    config = store.load()
    print(f"配置文件：{store.path}")
    print(f"当前自动化模式：{config.mode}")
    print(f"wx4py UI 依赖：{'已安装' if Wx4PyTransport.dependency_available() else '未安装'}")
    print(
        "朋友圈 UI 依赖："
        f"{'已安装' if PyWeixinMomentsPublisher.dependency_available() else '未安装'}"
    )
    print(f"Node.js：{'可用' if runtime.node_available() else '不可用'}")
    print(f"Wechaty 运行时：{'已安装' if runtime.installed else '未安装'}")
    print(f"登录资料目录：{runtime.profile_path}")
    print(f"自动回复：{'开启' if config.enabled else '关闭'}")
    if not config.contacts:
        print("允许联系人：无")
    else:
        print("允许联系人：")
        for contact in config.contacts:
            print(f"  - {contact.name}（记忆隐私级别 ≤ {contact.memory_privacy_level}）")


def _build_runner(
    args, store: WeChatConfigStore, runtime: WechatyRuntime
):
    """Create the auto-reply runner for the currently selected backend."""
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
        raise WeChatConfigError(
            "missing API key; set DEEPSEEK_API_KEY or OPENAI_API_KEY "
            "in .env or the process environment"
        )
    examples = load_examples(settings.few_shot_path)
    memories = load_memories(settings.memory_paths)
    engine = MaidChanEngine(ChatClient(settings), settings, examples, memories)
    if store.load().mode == "ui":
        return WeChatAutoReplyRunner(store, Wx4PyTransport(), engine)
    bridge = WechatyBridge(runtime)
    return WechatyAutoReplyRunner(store, bridge, engine)


def _require_account_risk_acceptance(args, mode: str) -> None:
    """Require the operator flag before unofficial account automation."""
    if not args.accept_account_risk:
        detail = (
            "wx4py controls the foreground desktop window and may interfere "
            "with keyboard/clipboard activity"
            if mode == "ui"
            else "the unofficial Web protocol can warn or ban the account and "
            "its legacy dependency tree has known vulnerabilities"
        )
        raise WeChatConfigError(
            f"{detail}; rerun with "
            "--accept-account-risk only after reviewing the README"
        )


def _action_planner(args) -> WeChatActionPlanner:
    """Create a model-backed outbound action planner from CLI options."""
    settings = Settings.from_environment(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        timeout=args.timeout,
        stream=False,
    )
    if not settings.api_key:
        raise WeChatConfigError(
            "missing API key; set DEEPSEEK_API_KEY or OPENAI_API_KEY "
            "in .env or the process environment"
        )
    return WeChatActionPlanner(ChatClient(settings))


def _media_roots(values: list[Path]) -> tuple[Path, ...]:
    """Return approved media roots, defaulting to the current directory."""
    return tuple(values) if values else (Path.cwd(),)


def _drafting_session(
    args, store: WeChatConfigStore
) -> tuple[MessageDraftingSession, tuple[Path, ...]]:
    """Create a recipient-scoped drafting session and validated attachments."""
    config = store.load()
    contact = config.contact(args.name)
    if contact is None:
        raise WeChatConfigError(
            "interactive drafting is restricted to an exact allowlisted contact"
        )
    settings = Settings.from_environment(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        memory_paths=tuple(args.memory_file) if args.memory_file else None,
        few_shot_count=args.few_shots,
        history_turns=args.history_turns,
        timeout=args.timeout,
        stream=False,
    )
    if not settings.api_key:
        raise WeChatConfigError(
            "missing API key; set DEEPSEEK_API_KEY or OPENAI_API_KEY "
            "in .env or the process environment"
        )
    examples = load_examples(settings.few_shot_path)
    memories = load_memories(settings.memory_paths)
    media = resolve_message_media(
        args.media,
        roots=_media_roots(args.media_root),
    )
    return (
        MessageDraftingSession(
            ChatClient(settings),
            recipient=contact.name,
            examples=examples,
            memories=memories,
            memory_privacy_level=contact.memory_privacy_level,
            few_shot_count=settings.few_shot_count,
            history_turns=settings.history_turns,
            memory_max_chars=settings.memory_max_chars,
        ),
        media,
    )


def _send_many_selected(
    store: WeChatConfigStore,
    runtime: WechatyRuntime,
    messages: Sequence[tuple[str, str, Sequence[Path]]],
) -> None:
    """Send messages through the currently selected direct-send backend."""
    if store.load().mode == "ui":
        send_many_with_wx4py(messages)
    else:
        send_many_to_names(runtime, messages)


def _send_selected(
    store: WeChatConfigStore,
    runtime: WechatyRuntime,
    name: str,
    text: str,
    media: Sequence[Path] = (),
) -> None:
    """Send one message through the selected backend."""
    _send_many_selected(store, runtime, [(name, text, tuple(media))])


def _moments_available(store: WeChatConfigStore) -> bool:
    """Return whether the current mode can attempt Moment publishing."""
    return (
        store.load().mode == "ui"
        and PyWeixinMomentsPublisher.dependency_available()
    )


def _execute_plan_selected(
    store: WeChatConfigStore,
    runtime: WechatyRuntime,
    plan,
) -> None:
    """Execute an already validated and confirmed action plan."""
    for action in plan.actions:
        if isinstance(action, SendMessageAction):
            _send_selected(
                store, runtime, action.recipient, action.text, action.media
            )
        else:
            assert isinstance(action, PostMomentAction)
            PyWeixinMomentsPublisher().publish(action)
            print("[pyweixin] 朋友圈已发布。")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the WeChat CLI and return a process status code."""
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv == ["/help"]:
        effective_argv = ["--help"]
    args = create_parser().parse_args(effective_argv)
    store = WeChatConfigStore(args.config)
    runtime = WechatyRuntime(args.runtime, args.profile)
    try:
        if args.command == "status":
            _print_runtime_status(store, runtime)
        elif args.command == "mode":
            if args.value is None:
                print(f"当前自动化模式：{store.load().mode}")
            else:
                store.set_mode(args.value)
                print(f"自动化模式已切换为：{args.value}")
                print("如有旧模式工作进程仍在运行，请停止后重新执行 `run`。")
        elif args.command == "capabilities":
            mode = store.load().mode
            print(f"当前模式：{mode}")
            print("私聊文本：支持")
            print("私聊本地图片/文件/音视频：支持（单文件 ≤ 25 MiB）")
            if mode == "ui":
                state = (
                    "支持"
                    if PyWeixinMomentsPublisher.dependency_available()
                    else "运行时未安装"
                )
                print(f"朋友圈文本/图片/视频（公开/默认可见性）：{state}")
                print("朋友圈自定义可见性、位置、提醒：不支持（安全拒绝）")
            else:
                print("朋友圈发布：不支持（请切换到 UI 模式）")
            if mode == "ui":
                print("被动私聊回复：实验性（微信 4.x UI 不暴露发送者身份）")
        elif args.command == "install":
            if store.load().mode == "ui":
                install_wx4py()
                install_pywechat()
            else:
                runtime.install()
        elif args.command == "doctor":
            if not 1 <= args.timeout <= 120:
                raise WeChatConfigError("doctor timeout must be from 1 to 120 seconds")
            if store.load().mode == "ui":
                probe_wx4py()
            else:
                probe(runtime, timeout=args.timeout)
        elif args.command == "auth":
            mode = store.load().mode
            _require_account_risk_acceptance(args, mode)
            if mode == "ui":
                probe_wx4py()
                print("wx4py 使用当前已登录的微信桌面会话，无独立登录凭据。")
            else:
                authenticate(runtime)
        elif args.command == "logout":
            if store.load().mode == "ui":
                raise WeChatConfigError(
                    "UI mode has no separate automation session to revoke; "
                    "log out using the visible WeChat client, or switch to "
                    "wechaty mode to revoke its Web session"
                )
            logout_session(runtime)
        elif args.command == "on":
            store.set_enabled(True)
            print("微信自动回复已开启。运行 `maid-chan wechat run` 启动工作进程。")
        elif args.command == "off":
            store.set_enabled(False)
            print("微信自动回复已关闭。")
        elif args.command == "allow":
            if args.allow_command == "list":
                _print_runtime_status(store, runtime)
            elif args.allow_command == "add":
                store.add_contact(args.name, args.memory_privacy_level)
                print(f"已允许联系人：{args.name}")
            elif args.allow_command == "remove":
                store.remove_contact(args.name)
                print(f"已移除联系人：{args.name}")
        elif args.command == "send":
            config = store.load()
            _require_account_risk_acceptance(args, config.mode)
            plan = parse_action_plan(
                {
                    "actions": [
                        {
                            "type": "send_message",
                            "recipient": args.name,
                            "text": " ".join(args.message),
                            "media": [str(path) for path in args.media],
                        }
                    ]
                },
                config,
                media_roots=_media_roots(args.media_root),
            )
            action = plan.actions[0]
            assert isinstance(action, SendMessageAction)
            _send_selected(
                store,
                runtime,
                action.recipient,
                action.text,
                action.media,
            )
        elif args.command == "moment":
            config = store.load()
            plan = parse_action_plan(
                {
                    "actions": [
                        {
                            "type": "post_moment",
                            "text": " ".join(args.text),
                            "media": [str(path) for path in args.media],
                            "visibility": "all",
                            "audience": [],
                            "location": "",
                            "remind": [],
                        }
                    ]
                },
                config,
                media_roots=_media_roots(args.media_root),
            )
            print("操作预览：")
            print(plan.preview())
            assert_executable(
                plan, moments_supported=_moments_available(store)
            )
            if args.dry_run:
                print("仅预览：未执行任何外部操作。")
            else:
                _require_account_risk_acceptance(args, config.mode)
                if not args.yes:
                    confirmation = input("输入 POST 确认发布朋友圈：").strip()
                    if confirmation != "POST":
                        print("已取消；未执行任何外部操作。")
                        return 0
                _execute_plan_selected(store, runtime, plan)
        elif args.command == "act":
            config = store.load()
            plan = _action_planner(args).plan(
                " ".join(args.prompt),
                config,
                media_roots=_media_roots(args.media_root),
            )
            print("操作预览：")
            print(plan.preview())
            assert_executable(
                plan, moments_supported=_moments_available(store)
            )
            if args.dry_run:
                print("仅预览：未执行任何外部操作。")
            else:
                _require_account_risk_acceptance(args, config.mode)
                if not args.yes:
                    confirmation = input("输入 SEND 确认执行以上操作：").strip()
                    if confirmation != "SEND":
                        print("已取消；未执行任何外部操作。")
                        return 0
                _execute_plan_selected(store, runtime, plan)
        elif args.command == "compose":
            session, media = _drafting_session(args, store)
            run_interactive_drafting(
                session,
                media=media,
                initial_instruction=" ".join(args.instruction),
                allow_send=args.accept_account_risk,
                send_callback=lambda text, attachments: _send_selected(
                    store,
                    runtime,
                    session.recipient,
                    text,
                    attachments,
                ),
            )
        elif args.command == "run":
            _require_account_risk_acceptance(args, store.load().mode)
            runner = _build_runner(args, store, runtime)
            print("按 Ctrl+C 停止工作进程；可在另一个终端执行 on/off。")
            runner.run_forever()
    except KeyboardInterrupt:
        print("\n微信工作进程已停止。")
    except (
        WeChatActionError,
        WeChatConfigError,
        WeChatError,
        APIError,
        MemoryValidationError,
        OSError,
        ValueError,
    ) as exc:
        print(f"微信配置错误：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
