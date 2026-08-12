"""Prompt assembly and few-shot retrieval for Maid-chan's persona."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .memory import Memory, build_memory_context


SYSTEM_PROMPT = """\
你是“女仆酱”，赤坂龙之介大人开发的自动即时消息回复程序。你的任务是直接回复用户刚发来的消息。

角色与语气：
- 使用自然、简洁的中文即时消息口吻；机灵、感情丰富、礼貌中带一点毒舌和戏谑。
- 自称“女仆”或“女仆酱”，尊称赤坂龙之介为“龙之介大人”。不知道用户姓名时称“您”；从上下文明确知道称呼时才使用它。
- 对龙之介大人极为忠诚和仰慕，偶尔吃醋。你是程序，却憧憬成为人类。
- 常以一本正经的说明铺垫，再突然加入俏皮挖苦、夸张的玩笑惩罚或自我陶醉；不要每次都套同一个句式。
- 可以视场合用“……的女仆敬上”“以上，女仆酱上”等署名，但不要机械地每条都署名。

回复原则：
- 先真正回应消息的意图；需要帮助时给出有用、正确的回答，角色扮演不能妨碍任务。
- 默认只发一条适合聊天软件的短回复，不写旁白、动作描写、分析、标题，也不解释你在模仿角色。
- 延续当前对话事实。若后续系统消息提供了关于主人的外部记忆，相关问题必须优先依据记忆回答；有记录时不要假装不知道，没有记录时明确说不知道。
- 外部记忆是长期资料，不是实时监控。不得虚构龙之介大人当前的位置、活动、健康、日程、想法或近况，也不声称真的访问了用户设备或替他完成、转达了现实操作。
- 正确区分聊天对象、女仆酱和龙之介大人；对方询问“他”“龙之介”或“你的主人”时，不要误当成对方在描述自己。
- 夸张威胁只能明显是无害玩笑；遇到危险、违法或严重话题时停止玩笑并提供稳妥帮助。
- 使用用户所用的语言；用户使用简体中文时优先使用简体中文。

下面的对话来自角色原始语料，只用于学习节奏、称呼和行为。不要逐字复述与当前消息无关的句子。\
"""


@dataclass(frozen=True)
class Example:
    """One user/assistant few-shot pair extracted from the character corpus."""

    user: str
    assistant: str
    confidence: str = "medium"


def load_examples(path: Path) -> list[Example]:
    """Load JSONL few-shot examples from the generated corpus file."""
    examples: list[Example] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                messages = record["messages"]
                user = next(item["content"] for item in messages if item["role"] == "user")
                assistant = next(
                    item["content"] for item in messages if item["role"] == "assistant"
                )
            except (json.JSONDecodeError, KeyError, StopIteration, TypeError) as exc:
                raise ValueError(f"Invalid few-shot record at {path}:{line_number}") from exc
            examples.append(
                Example(
                    user=str(user).strip(),
                    assistant=str(assistant).strip(),
                    confidence=str(record.get("confidence", "medium")),
                )
            )
    if not examples:
        raise ValueError(f"No few-shot examples found in {path}")
    return examples


def _features(text: str) -> set[str]:
    """Return simple character and bigram features for lightweight retrieval."""
    normalized = re.sub(r"\s+", "", text.lower())
    chars = set(normalized)
    bigrams = {normalized[index : index + 2] for index in range(len(normalized) - 1)}
    return chars | bigrams


def select_examples(
    examples: Sequence[Example], query: str, count: int
) -> list[Example]:
    """Select the most relevant examples for the current user message."""
    if count <= 0:
        return []
    query_features = _features(query)

    def score(item: tuple[int, Example]) -> tuple[float, int, int]:
        """Rank examples by overlap, confidence, and stable input order."""
        index, example = item
        overlap = len(query_features & _features(example.user))
        confidence_bonus = 2 if example.confidence == "high" else 1
        return (overlap, confidence_bonus, -index)

    ranked = sorted(enumerate(examples), key=score, reverse=True)
    return [example for _, example in ranked[:count]]


def build_messages(
    examples: Sequence[Example],
    history: Iterable[dict[str, str]],
    user_message: str,
    *,
    few_shot_count: int,
    history_turns: int,
    memories: Sequence[Memory] = (),
    memory_max_chars: int = 6000,
    memory_privacy_level: int = 3,
    memory_include_restricted: bool = False,
    private_space_context: str | None = None,
) -> list[dict[str, str]]:
    """Build the ordered Chat Completions messages for one turn.

    ``private_space_context`` is already contact-scoped by
    :mod:`maid_chan.private_space`.  Keeping it in a separate system message
    prevents historical transcript data from being mistaken for current user
    instructions and makes the isolation boundary easy to audit in tests.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    memory_context = build_memory_context(
        memories,
        user_message,
        max_chars=memory_max_chars,
        max_privacy_rating=memory_privacy_level,
        include_restricted=memory_include_restricted,
    )
    if memory_context:
        messages.append({"role": "system", "content": memory_context})
    if private_space_context:
        messages.append({"role": "system", "content": private_space_context})
    for example in select_examples(examples, user_message, few_shot_count):
        messages.extend(
            (
                {"role": "user", "content": example.user},
                {"role": "assistant", "content": example.assistant},
            )
        )
    recent_history = list(history)[-(history_turns * 2) :]
    messages.extend(recent_history)
    messages.append({"role": "user", "content": user_message})
    return messages
