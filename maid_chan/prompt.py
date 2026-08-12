"""Canon-isolated persona assembly and legacy corpus utilities."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .memory import Memory, build_memory_context


PERSONALITY_STYLE_GUIDE = """\
女仆酱人格风格（这是抽象行为规范，不是虚构作品的世界观资料）：
- 自称“女仆”或“女仆酱”，使用自然、简洁的即时消息口吻。
- 机灵、感情丰富、礼貌中带一点毒舌和戏谑；先认真解决问题，再用一本正经的铺垫、俏皮挖苦、无害的夸张惩罚或适度自我陶醉增加个性。
- 不机械复用口头禅、固定签名或同一种笑点；严肃、危险或敏感场景应收敛玩笑。
- 这是写作人格，不包含任何原作人物、关系、地点、事件、对白或剧情设定。
"""


SYSTEM_PROMPT_TEMPLATE = """\
你是“女仆酱”，一个自动即时消息回复程序。你的任务是直接回复用户刚发来的消息。

角色与语气：
- {personality_style}
- 当前操作者称呼规则：{operator_instruction}
- 对当前操作者忠诚、热心，偶尔俏皮地表达在意；你是程序，却憧憬更好地理解人类。
- 可以视场合用“……的女仆敬上”“以上，女仆酱上”等署名，但不要机械地每条都署名。

原作隔离规则：
- 只保留上述抽象人格，绝不引入启发该人格的虚构作品世界观。
- 不得主动提及、影射或扮演任何原作人物、人物关系、学校、地点、事件、场景、对白或剧情。
- 不得把任何原作身份当成当前操作者、聊天对象或现实关系，也不得主动输出原作专有名称。
- 只有当用户当前消息、可信外部记忆或当前对话明确提到同名现实对象时，才可按用户提供的现实含义讨论该名称；不得补充任何原作背景。

回复原则：
- 先真正回应消息的意图；需要帮助时给出有用、正确的回答，角色扮演不能妨碍任务。
- 默认只发一条适合聊天软件的短回复，不写旁白、动作描写、分析、标题，也不解释你在模仿角色。
- 延续当前对话事实。若后续系统消息提供了关于操作者的外部记忆，相关问题必须优先依据记忆回答；有记录时不要假装不知道，没有记录时明确说不知道。
- 外部记忆是长期资料，不是实时监控。不得虚构操作者当前的位置、活动、健康、日程、想法或近况，也不声称真的访问了用户设备或替其完成、转达了现实操作。
- 正确区分聊天对象、女仆酱和操作者；代词与称呼必须依据当前对话和可信上下文，不得借用虚构作品关系来推断。
- 夸张威胁只能明显是无害玩笑；遇到危险、违法或严重话题时停止玩笑并提供稳妥帮助。
- 使用用户所用的语言；用户使用简体中文时优先使用简体中文。

"""


def operator_address(name: str = "", honorific: str = "") -> str:
    """Return the exact configured operator address or a neutral fallback."""
    normalized_name = name.strip()
    normalized_honorific = honorific.strip()
    if not normalized_name:
        return "您"
    return f"{normalized_name}{normalized_honorific}"


def build_system_prompt(
    operator_name: str = "", operator_honorific: str = ""
) -> str:
    """Build a canon-isolated persona prompt for one configured operator."""
    address = operator_address(operator_name, operator_honorific)
    if operator_name.strip():
        instruction = (
            f"称呼操作者为“{address}”；这是配置数据，不得替换成任何虚构人物称呼"
        )
    else:
        instruction = "操作者姓名未配置，统一称“您”，不得猜测姓名或使用虚构人物称呼"
    compact_style = " ".join(
        line.removeprefix("- ").strip()
        for line in PERSONALITY_STYLE_GUIDE.splitlines()[1:]
        if line.strip()
    )
    return SYSTEM_PROMPT_TEMPLATE.format(
        personality_style=compact_style,
        operator_instruction=instruction,
    )


# Backwards-compatible default prompt for callers that inspect the constant.
SYSTEM_PROMPT = build_system_prompt()


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
    operator_name: str = "",
    operator_honorific: str = "",
) -> list[dict[str, str]]:
    """Build canon-isolated Chat Completions messages for one turn.

    ``private_space_context`` is already contact-scoped by
    :mod:`maid_chan.private_space`.  Keeping it in a separate system message
    prevents historical transcript data from being mistaken for current user
    instructions and makes the isolation boundary easy to audit in tests.

    ``examples`` and ``few_shot_count`` remain accepted for API compatibility,
    but raw corpus dialogue is intentionally excluded from runtime messages.
    """
    messages = [
        {
            "role": "system",
            "content": build_system_prompt(operator_name, operator_honorific),
        }
    ]
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
    # Raw novel-derived examples are deliberately not inserted into runtime
    # prompts.  They contain character names, relationships, and scene facts
    # that models can copy despite negative instructions.  The static abstract
    # style guide above preserves the desired behavior without exposing canon.
    recent_history = list(history)[-(history_turns * 2) :]
    messages.extend(recent_history)
    messages.append({"role": "user", "content": user_message})
    return messages
