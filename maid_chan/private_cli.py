"""Operator CLI for importing, annotating, and chatting in private spaces."""

from __future__ import annotations

import argparse
import ipaddress
import sys
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlparse

from .client import APIError, ChatClient
from .config import DEFAULT_BASE_URL, DEFAULT_MODEL, Settings
from .private_space import (
    DEFAULT_PRIVATE_SPACES_PATH,
    ContactProfile,
    PrivateSpaceError,
    PrivateSpaceStore,
)
from .prompt import build_messages, load_examples


def _configure_utf8_console() -> None:
    """Prefer UTF-8 output so WeChat emoji names cannot crash Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (LookupError, OSError, ValueError):
            # Redirected or test streams may reject runtime reconfiguration.
            pass


def _add_chat_settings(parser: argparse.ArgumentParser) -> None:
    """Add model and retrieval controls shared by private chat invocations."""
    parser.add_argument("--api-key", help="provider API key")
    parser.add_argument("--base-url", default=None, help=f"default: {DEFAULT_BASE_URL}")
    parser.add_argument("--model", default=None, help=f"default: {DEFAULT_MODEL}")
    parser.add_argument("--few-shots", type=int, default=8)
    parser.add_argument("--history-turns", type=int, default=12)
    parser.add_argument("--temperature", type=float, default=0.9)
    parser.add_argument("--max-tokens", type=int, default=500)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--no-stream", action="store_true")
    parser.add_argument(
        "--private-context-chars",
        type=int,
        default=12_000,
        help="maximum contact profile and transcript context per request",
    )
    parser.add_argument(
        "--allow-remote-context",
        action="store_true",
        help=(
            "explicitly allow selected private-space text to be sent to a "
            "non-loopback model endpoint"
        ),
    )


def create_parser() -> argparse.ArgumentParser:
    """Create the private-space command parser."""
    parser = argparse.ArgumentParser(
        prog="maid-chan private",
        description=(
            "Import isolated correspondent histories and chat as one exact contact."
        ),
    )
    parser.add_argument(
        "--spaces-dir",
        type=Path,
        default=DEFAULT_PRIVATE_SPACES_PATH,
        help=f"local private-space store (default: {DEFAULT_PRIVATE_SPACES_PATH})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    importer = subparsers.add_parser(
        "import-wechat", help="import WeFlow contact folders into isolated spaces"
    )
    importer.add_argument("export_root", type=Path)
    importer.add_argument(
        "--include-groups",
        action="store_true",
        help="import each group as its own group space; never merge it into contacts",
    )

    subparsers.add_parser("list", help="list profiles without opening transcripts")
    show = subparsers.add_parser("show", help="show one contact profile summary")
    show.add_argument("contact")

    identity = subparsers.add_parser(
        "set-identity", help="set operator-reviewed relationship information"
    )
    identity.add_argument("contact")
    identity.add_argument("--relationship")
    identity.add_argument("--notes")

    relation = subparsers.add_parser(
        "relation", help="manage explicit context shared by two contacts"
    )
    relation_subparsers = relation.add_subparsers(
        dest="relation_command", required=True
    )
    relation_add = relation_subparsers.add_parser(
        "add", help="create or update a bilateral relation record"
    )
    relation_add.add_argument("left_contact")
    relation_add.add_argument("right_contact")
    relation_add.add_argument("--label", required=True)
    relation_add.add_argument("--note", default="")
    relation_remove = relation_subparsers.add_parser(
        "remove", help="remove a bilateral relation record"
    )
    relation_remove.add_argument("left_contact")
    relation_remove.add_argument("right_contact")
    relation_list = relation_subparsers.add_parser(
        "list", help="list explicit relations visible to one contact"
    )
    relation_list.add_argument("contact")

    chat = subparsers.add_parser(
        "chat", help="chat with Maid-chan as one exact correspondent"
    )
    chat.add_argument("contact")
    chat.add_argument("message", nargs="*", help="send one message and exit")
    _add_chat_settings(chat)
    return parser


def _is_loopback_endpoint(base_url: str) -> bool:
    """Return whether a model endpoint is confined to the local machine."""
    host = urlparse(base_url).hostname
    if not host:
        return False
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _profile_summary(profile: ContactProfile) -> str:
    """Render profile metadata without exposing its platform identifier or paths."""
    relationship = profile.relationship or "未由操作者指定"
    notes = profile.notes or "无"
    return (
        f"联系人：{profile.display_name}\n"
        f"空间 ID：{profile.space_id}\n"
        f"会话类型：{profile.session_type}\n"
        f"关系：{relationship}\n"
        f"备注：{notes}\n"
        f"历史消息：{profile.message_count} 条"
    )


def _chat_settings(args: argparse.Namespace) -> Settings:
    """Resolve provider settings while deliberately excluding shared memories."""
    return Settings.from_environment(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        few_shot_count=args.few_shots,
        history_turns=args.history_turns,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
        stream=not args.no_stream,
        thinking=args.thinking,
        memory_paths=(),
    )


def _one_reply(
    client: ChatClient,
    settings: Settings,
    examples,
    store: PrivateSpaceStore,
    profile: ContactProfile,
    history: list[dict[str, str]],
    message: str,
    *,
    private_context_chars: int,
) -> str:
    """Generate one private-space reply and return its complete text."""
    private_context = store.build_prompt_context(
        profile.space_id,
        message,
        max_chars=private_context_chars,
    )
    messages = build_messages(
        examples,
        history,
        message,
        few_shot_count=settings.few_shot_count,
        history_turns=settings.history_turns,
        memories=(),
        private_space_context=private_context,
    )
    if not settings.stream:
        reply = client.complete(messages)
        print(f"女仆酱 > {reply}")
        return reply
    print("女仆酱 > ", end="", flush=True)
    chunks: list[str] = []
    try:
        for chunk in client.stream(messages):
            chunks.append(chunk)
            print(chunk, end="", flush=True)
    finally:
        print()
    return "".join(chunks).strip()


def _run_chat(
    args: argparse.Namespace, store: PrivateSpaceStore, profile: ContactProfile
) -> int:
    """Run a one-shot or interactive contact-impersonation chat session."""
    settings = _chat_settings(args)
    if not _is_loopback_endpoint(settings.base_url) and not args.allow_remote_context:
        raise PrivateSpaceError(
            "private context is blocked from remote model providers by default; "
            "use a loopback endpoint or pass --allow-remote-context after reviewing "
            "the provider's data handling"
        )
    if not settings.api_key:
        raise PrivateSpaceError(
            "missing API key; configure DEEPSEEK_API_KEY or OPENAI_API_KEY"
        )
    if args.private_context_chars < 2_000:
        raise PrivateSpaceError("--private-context-chars must be at least 2000")
    examples = load_examples(settings.few_shot_path)
    client = ChatClient(settings)
    history: list[dict[str, str]] = []
    one_shot_message = " ".join(args.message).strip()
    if one_shot_message:
        _one_reply(
            client,
            settings,
            examples,
            store,
            profile,
            history,
            one_shot_message,
            private_context_chars=args.private_context_chars,
        )
        return 0

    print(
        f"Maid-chan 私密空间 · 当前身份：{profile.display_name}\n"
        f"关系：{profile.relationship or '未由操作者指定'}；"
        f"历史消息：{profile.message_count} 条\n"
        "此会话只读取该空间和显式双边关系；/reset 清空本次会话，/quit 退出。"
    )
    while True:
        try:
            message = input(f"{profile.display_name} > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n女仆酱 > 私密会话已结束。女仆敬上")
            return 0
        if not message:
            continue
        if message == "/quit":
            print("女仆酱 > 私密会话已结束。女仆敬上")
            return 0
        if message == "/reset":
            history.clear()
            print("女仆酱 > 本次会话记录已清空，历史私密空间保持不变。")
            continue
        reply = _one_reply(
            client,
            settings,
            examples,
            store,
            profile,
            history,
            message,
            private_context_chars=args.private_context_chars,
        )
        history.extend(
            (
                {"role": "user", "content": message},
                {"role": "assistant", "content": reply},
            )
        )
        del history[: max(0, len(history) - settings.history_turns * 2)]


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch private-space commands and return a process status code."""
    _configure_utf8_console()
    args = create_parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    store = PrivateSpaceStore(args.spaces_dir)
    try:
        if args.command == "import-wechat":
            report = store.import_weflow(
                args.export_root, include_groups=args.include_groups
            )
            print(
                f"已导入 {report.imported_spaces} 个独立空间、"
                f"{report.imported_messages} 条消息；"
                f"跳过群聊 {report.skipped_groups} 个、"
                f"非会话目录 {report.skipped_directories} 个。"
            )
        elif args.command == "list":
            profiles = store.list_profiles()
            if not profiles:
                print("尚无私密空间。请先运行 import-wechat。")
            for profile in sorted(
                profiles, key=lambda item: item.display_name.casefold()
            ):
                relationship = profile.relationship or "关系未指定"
                print(
                    f"{profile.display_name}\t{profile.space_id}\t"
                    f"{relationship}\t{profile.message_count} 条"
                )
        elif args.command == "show":
            print(_profile_summary(store.resolve(args.contact)))
        elif args.command == "set-identity":
            profile = store.set_identity(
                args.contact,
                relationship=args.relationship,
                notes=args.notes,
            )
            print(f"已更新 {profile.display_name} 的私密身份资料。")
        elif args.command == "relation":
            if args.relation_command == "add":
                relation = store.add_relation(
                    args.left_contact,
                    args.right_contact,
                    label=args.label,
                    note=args.note,
                )
                print(f"已保存双边关系：{relation.label}")
            elif args.relation_command == "remove":
                removed = store.remove_relation(
                    args.left_contact, args.right_contact
                )
                print("已删除双边关系。" if removed else "未找到该双边关系。")
            elif args.relation_command == "list":
                profile = store.resolve(args.contact)
                relations = store.relations_for(profile)
                if not relations:
                    print(f"{profile.display_name} 没有显式双边关系。")
                for relation, other in relations:
                    detail = f"：{relation.note}" if relation.note else ""
                    print(f"{other.display_name}\t{relation.label}{detail}")
        elif args.command == "chat":
            return _run_chat(args, store, store.resolve(args.contact))
    except (APIError, OSError, PrivateSpaceError, ValueError) as exc:
        print(f"私密空间错误：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
