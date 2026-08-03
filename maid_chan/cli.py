"""Terminal entry point for chatting with Maid-chan and routing commands."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .client import APIError, ChatClient
from .config import (
    DEFAULT_BASE_URL,
    DEFAULT_FEW_SHOT_PATH,
    DEFAULT_MEMORY_MAX_CHARS,
    DEFAULT_MEMORY_PRIVACY_LEVEL,
    DEFAULT_MODEL,
    Settings,
)
from .memory import Memory, MemoryValidationError, load_memories
from .prompt import build_messages, load_examples
from .shell import MaidChanShell, ShellAction


def create_parser() -> argparse.ArgumentParser:
    """Create the top-level CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="maid-chan",
        description="Chat with Maid-chan through an OpenAI-compatible API.",
    )
    parser.add_argument("message", nargs="*", help="send one message and exit")
    parser.add_argument("--api-key", help="API key (prefer the environment variables)")
    parser.add_argument("--base-url", help=f"API base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--model", help=f"model ID (default: {DEFAULT_MODEL})")
    parser.add_argument("--few-shot-file", type=Path, default=DEFAULT_FEW_SHOT_PATH)
    parser.add_argument("--few-shots", type=int, default=8)
    parser.add_argument("--history-turns", type=int, default=12)
    parser.add_argument(
        "--memory-file",
        type=Path,
        action="append",
        dest="memory_files",
        help="external memory JSON file; may be passed more than once",
    )
    parser.add_argument(
        "--memory-max-chars",
        type=int,
        default=DEFAULT_MEMORY_MAX_CHARS,
        help="maximum imported-memory context per request",
    )
    parser.add_argument(
        "--memory-privacy-level",
        type=int,
        choices=range(1, 6),
        default=None,
        help=(
            "maximum privacy rating visible to this viewer "
            f"(default: {DEFAULT_MEMORY_PRIVACY_LEVEL})"
        ),
    )
    parser.add_argument(
        "--include-restricted-memory",
        action="store_true",
        help="deprecated alias for --memory-privacy-level 5",
    )
    parser.add_argument("--temperature", type=float, default=0.9)
    parser.add_argument("--max-tokens", type=int, default=500)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--no-stream", action="store_true", help="wait for the full reply")
    parser.add_argument(
        "--thinking",
        action="store_true",
        help="enable DeepSeek thinking mode (off by default for faster replies)",
    )
    return parser


def _reply(
    client: ChatClient,
    settings: Settings,
    examples,
    memories: Sequence[Memory],
    history: list[dict[str, str]],
    user_message: str,
) -> str:
    """Print one reply, streaming when configured, and return its text."""
    messages = build_messages(
        examples,
        history,
        user_message,
        few_shot_count=settings.few_shot_count,
        history_turns=settings.history_turns,
        memories=memories,
        memory_max_chars=settings.memory_max_chars,
        memory_privacy_level=settings.memory_privacy_level,
        memory_include_restricted=settings.memory_include_restricted,
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


def _memory_status(
    memories: Sequence[Memory], max_privacy_rating: int
) -> str:
    """Summarize loaded memories without revealing their contents."""
    if not memories:
        return "未加载（使用 --memory-file 或 MAID_CHAN_MEMORY_FILES）"
    active_memories = [item for item in memories if item.status == "active"]
    visible = sum(
        item.privacy_rating <= max_privacy_rating for item in active_memories
    )
    hidden = len(active_memories) - visible
    sources = "、".join(sorted({item.source_platform for item in memories}))
    return (
        f"{visible}/{len(active_memories)} 条对当前用户可见，"
        f"隐私级别上限：{max_privacy_rating}，来源：{sources}"
        + (f"，隐藏 {hidden} 条" if hidden else "")
    )


def _interactive(
    client: ChatClient,
    settings: Settings,
    examples,
    memories: Sequence[Memory],
) -> int:
    """Run the interactive chat and command shell loop."""
    history: list[dict[str, str]] = []
    shell = MaidChanShell(client, settings, memories)
    print(
        f"Maid-chan CLI · {settings.model}\n"
        f"外部记忆：{_memory_status(memories, settings.memory_privacy_level)}\n"
        "输入消息开始聊天或操作；/help 查看统一命令，/quit 退出。"
    )
    while True:
        try:
            user_message = input("你     > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n女仆酱 > 下次再来吧。负责礼貌送客的女仆敬上")
            return 0
        if not user_message:
            continue
        result = shell.handle(user_message)
        if result.action is ShellAction.EXIT:
            print("女仆酱 > 下次再来吧。负责礼貌送客的女仆敬上")
            return 0
        if result.action is ShellAction.RESET:
            history.clear()
            print("女仆酱 > 对话记录已经清空。连这点小事都能办好的女仆敬上")
            continue
        if result.action is ShellAction.HANDLED and result.message == "memory":
            print(
                "女仆酱 > 外部记忆："
                f"{_memory_status(memories, settings.memory_privacy_level)}"
            )
            continue
        if result.action is ShellAction.HANDLED:
            continue
        user_message = result.message
        try:
            reply = _reply(
                client, settings, examples, memories, history, user_message
            )
        except APIError as exc:
            print(f"请求失败：{exc}", file=sys.stderr)
            continue
        history.extend(
            (
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": reply},
            )
        )
        del history[: max(0, len(history) - settings.history_turns * 2)]


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch the top-level command line and return a process status code."""
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv == ["/help"]:
        print(MaidChanShell.help_text())
        print("\n启动参数")
        create_parser().print_help()
        return 0
    if effective_argv and effective_argv[0] == "wechat":
        from .wechat_cli import main as wechat_main

        return wechat_main(effective_argv[1:])
    if effective_argv and effective_argv[0] == "weixin":
        from .weixin_cli import main as weixin_main

        return weixin_main(effective_argv[1:])
    args = create_parser().parse_args(effective_argv)
    try:
        settings = Settings.from_environment(
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            timeout=args.timeout,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            few_shot_path=args.few_shot_file,
            few_shot_count=args.few_shots,
            history_turns=args.history_turns,
            memory_paths=(
                tuple(args.memory_files)
                if args.memory_files is not None
                else None
            ),
            memory_max_chars=args.memory_max_chars,
            memory_privacy_level=(
                5
                if args.include_restricted_memory
                else args.memory_privacy_level
            ),
            memory_include_restricted=args.include_restricted_memory,
            stream=not args.no_stream,
            thinking=args.thinking,
        )
    except ValueError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    if not settings.api_key:
        print(
            "缺少 API key。请在 .env 或当前环境中设置 "
            "DEEPSEEK_API_KEY（或 OPENAI_API_KEY），也可以传入 --api-key。",
            file=sys.stderr,
        )
        return 2
    if not 1 <= settings.memory_privacy_level <= 5:
        print("记忆隐私级别必须是 1 到 5 的整数。", file=sys.stderr)
        return 2
    try:
        examples = load_examples(settings.few_shot_path)
    except (OSError, ValueError) as exc:
        print(f"无法加载 few-shot 语料：{exc}", file=sys.stderr)
        return 2
    try:
        memories = load_memories(settings.memory_paths)
    except MemoryValidationError as exc:
        print(f"无法加载外部记忆：{exc}", file=sys.stderr)
        return 2

    client = ChatClient(settings)
    one_shot_message = " ".join(args.message).strip()
    if one_shot_message:
        try:
            _reply(client, settings, examples, memories, [], one_shot_message)
        except APIError as exc:
            print(f"请求失败：{exc}", file=sys.stderr)
            return 1
        return 0
    return _interactive(client, settings, examples, memories)


if __name__ == "__main__":
    raise SystemExit(main())
