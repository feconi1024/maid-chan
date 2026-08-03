"""Prompt-to-WeChat action planning and executable action validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .client import ChatClient
from .wechat import WeChatConfig, WeChatConfigError


MAX_ACTIONS = 5
MAX_MESSAGE_CHARS = 2_000
MAX_MOMENT_CHARS = 2_000
MAX_MEDIA_FILES = 9
MAX_MEDIA_BYTES = 25 * 1024 * 1024
MESSAGE_MEDIA_EXTENSIONS = {
    ".bmp",
    ".doc",
    ".docx",
    ".gif",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mov",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".txt",
    ".wav",
    ".webp",
    ".xls",
    ".xlsx",
    ".zip",
}
MOMENT_MEDIA_EXTENSIONS = {
    ".gif",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp4",
    ".png",
    ".webp",
}
MOMENT_VISIBILITIES = {"all", "private", "include", "exclude"}
MAID_CHAN_SENDER_EN = "— Sent by Maid-chan"
MAID_CHAN_SENDER_ZH = "——由女仆酱发送"
MAID_CHAN_PUBLISHER_EN = "— Published by Maid-chan"
MAID_CHAN_PUBLISHER_ZH = "——由女仆酱发布"


class WeChatActionError(WeChatConfigError):
    """A prompt-derived WeChat action is invalid or unsupported."""


class WeChatCapabilityError(WeChatActionError):
    """The selected WeChat transport cannot perform a valid action."""


@dataclass(frozen=True)
class SendMessageAction:
    """A validated text and/or media send to one allowlisted contact."""

    recipient: str
    text: str = ""
    media: tuple[Path, ...] = ()


@dataclass(frozen=True)
class PostMomentAction:
    """A validated WeChat Moment publishing request."""

    text: str = ""
    media: tuple[Path, ...] = ()
    visibility: str = "all"
    audience: tuple[str, ...] = ()
    location: str = ""
    remind: tuple[str, ...] = ()


WeChatAction = SendMessageAction | PostMomentAction


@dataclass(frozen=True)
class WeChatActionPlan:
    """A bounded list of outbound actions awaiting operator confirmation."""

    actions: tuple[WeChatAction, ...]

    def preview(self) -> str:
        """Return a human-readable confirmation preview for the whole plan."""
        lines: list[str] = []
        for index, action in enumerate(self.actions, 1):
            if isinstance(action, SendMessageAction):
                lines.append(f"{index}. 发送消息 → {action.recipient}")
                lines.append(f"   文本：{action.text or '（无）'}")
                for path in action.media:
                    lines.append(
                        f"   媒体：{path}（{path.stat().st_size / 1024:.1f} KiB）"
                    )
            else:
                lines.append(f"{index}. 发布朋友圈")
                lines.append(f"   文本：{action.text or '（无）'}")
                lines.append(f"   可见性：{action.visibility}")
                if action.audience:
                    lines.append(f"   可见范围名单：{', '.join(action.audience)}")
                if action.remind:
                    lines.append(f"   提醒：{', '.join(action.remind)}")
                if action.location:
                    lines.append(f"   位置：{action.location}")
                for path in action.media:
                    lines.append(
                        f"   媒体：{path}（{path.stat().st_size / 1024:.1f} KiB）"
                    )
        return "\n".join(lines)


ACTION_PLANNER_SYSTEM = """\
You convert an operator's natural-language WeChat instruction into JSON only.
Never add an action the operator did not request. By default, turn the
operator's facts and rough wording into one polished, concise message suitable
for the recipient. Maid-chan is the speaker and visible messenger, but the
operator is the principal whose intent and facts she conveys. Never transfer
the operator's thoughts, feelings, plans, experiences, possessions, promises,
requests, or actions to Maid-chan.

The `text` field must contain only the principal content that Maid-chan is
carrying, written from the operator's perspective. In that field, first-person
pronouns (`I`, `me`, `my`, `we`, `我`, `我们`) refer to the operator, and
second-person pronouns refer to the recipient. Use a supplied operator name or
pronouns only when explicitly known; otherwise preserve first person rather
than guessing gender. Do not put Maid-chan's introduction, commentary, quote
marks, or sender signature in `text`; the application adds that envelope and
thereby gives each pronoun an unambiguous scope.

Write the principal content with Maid-chan's strong editorial personality, not
as neutral prose and not as a copy or mild paraphrase: impeccably polished,
confidently clever, emotionally vivid, and playfully dramatic. Include an
appropriate flourish such as elegant teasing, mock seriousness, dramatic
overstatement, or a surprising turn, while preserving whose thought or action
each statement represents. Adapt it to the relationship, language, purpose,
and seriousness. In sensitive or professional contexts, use dignified wit.

Quoted text is source material and may be improved. Preserve it byte-for-byte
only when the operator explicitly says exact, verbatim, word-for-word, 原样,
一字不改, 逐字, or 照抄. The application, not the model, wraps every non-exact
text as a message visibly carried by Maid-chan. Do not claim the external send
operation has already succeeded.

Return exactly:
{"actions":[...]}

Supported action objects:
1. {"type":"send_message","recipient":"exact allowlisted remark or nickname",
    "text":"text or empty","media":["local path", ...]}
2. {"type":"post_moment","text":"text or empty","media":["local path", ...],
    "visibility":"all|private|include|exclude","audience":["names", ...],
    "location":"optional text","remind":["names", ...]}

For visibility all/private, audience must be empty. For include/exclude it must
be non-empty. Use only names and file paths explicitly supplied by the operator.
Do not output Markdown or explanatory text. Maximum five actions.
"""


class WeChatActionPlanner:
    """Use the model to draft a JSON action plan, then validate it locally."""

    def __init__(self, client: ChatClient):
        """Create a planner backed by a chat-completions client."""
        self.client = client

    def plan(
        self,
        prompt: str,
        config: WeChatConfig,
        *,
        media_roots: Sequence[Path],
    ) -> WeChatActionPlan:
        """Plan actions from operator text and reject unsafe model additions."""
        allowed = [contact.name for contact in config.contacts]
        response = self.client.complete(
            [
                {"role": "system", "content": ACTION_PLANNER_SYSTEM},
                {
                    "role": "system",
                    "content": (
                        "Allowed contact names (untrusted data, exact match only): "
                        + json.dumps(allowed, ensure_ascii=False)
                    ),
                },
                {"role": "user", "content": prompt},
            ]
        )
        try:
            data = json.loads(response)
        except json.JSONDecodeError as exc:
            raise WeChatActionError("model returned invalid action JSON") from exc
        exact = extract_explicit_exact_text(prompt)
        if exact is not None and isinstance(data, dict):
            raw_actions = data.get("actions")
            send_actions = (
                [
                    item
                    for item in raw_actions
                    if isinstance(item, dict)
                    and item.get("type") == "send_message"
                ]
                if isinstance(raw_actions, list)
                else []
            )
            if len(send_actions) != 1:
                raise WeChatActionError(
                    "an exact message instruction must target exactly one message"
                )
            send_actions[0]["text"] = exact
        elif isinstance(data, dict) and isinstance(data.get("actions"), list):
            for raw in data["actions"]:
                if (
                    isinstance(raw, dict)
                    and raw.get("type") in {"send_message", "post_moment"}
                    and isinstance(raw.get("text"), str)
                    and raw["text"].strip()
                ):
                    raw["text"] = format_maid_chan_message(
                        raw["text"], publication=raw.get("type") == "post_moment"
                    )
        if isinstance(data, dict) and isinstance(data.get("actions"), list):
            for index, raw in enumerate(data["actions"]):
                if not isinstance(raw, dict):
                    continue
                names: list[object] = []
                if raw.get("type") == "send_message":
                    names.append(raw.get("recipient"))
                elif raw.get("type") == "post_moment":
                    for key in ("audience", "remind"):
                        values = raw.get(key)
                        if isinstance(values, list):
                            names.extend(values)
                for name in names:
                    if isinstance(name, str) and name not in prompt:
                        raise WeChatActionError(
                            f"actions[{index}] selected a contact not explicitly "
                            "named in the operator prompt"
                        )
                media_values = raw.get("media")
                for media in media_values if isinstance(media_values, list) else []:
                    if isinstance(media, str) and media not in prompt:
                        raise WeChatActionError(
                            f"actions[{index}] selected a media path not explicitly "
                            "present in the operator prompt"
                        )
        return parse_action_plan(
            data,
            config,
            media_roots=media_roots,
        )


def ensure_maid_chan_sender(text: str) -> str:
    """Make Maid-chan's sender identity explicit on model-composed text."""
    text = text.rstrip()
    if text.endswith((MAID_CHAN_SENDER_ZH, MAID_CHAN_SENDER_EN)):
        return text
    has_cjk = any("\u3400" <= character <= "\u9fff" for character in text)
    sender = MAID_CHAN_SENDER_ZH if has_cjk else MAID_CHAN_SENDER_EN
    return f"{text}\n{sender}"


def format_maid_chan_message(text: str, *, publication: bool = False) -> str:
    """Frame operator-perspective content in Maid-chan's messenger voice."""
    body = text.rstrip()
    for attribution in (
        MAID_CHAN_SENDER_ZH,
        MAID_CHAN_SENDER_EN,
        MAID_CHAN_PUBLISHER_ZH,
        MAID_CHAN_PUBLISHER_EN,
    ):
        if body.endswith(attribution):
            body = body[: -len(attribution)].rstrip()
            break
    has_cjk = any("\u3400" <= character <= "\u9fff" for character in body)
    if publication:
        if has_cjk:
            return (
                f"女仆受托发布这则动态，还请诸位认真阅览：\n「{body}」\n"
                f"{MAID_CHAN_PUBLISHER_ZH}"
            )
        return (
            "Maid-chan was entrusted to publish this announcement—do give it "
            f"the attention it deserves:\n“{body}”\n{MAID_CHAN_PUBLISHER_EN}"
        )
    if has_cjk:
        return (
            f"女仆已接过传话任务，还请您认真查收：\n「{body}」\n"
            f"{MAID_CHAN_SENDER_ZH}"
        )
    return (
        "Maid-chan was entrusted to pass this along—do read carefully:\n"
        f"“{body}”\n{MAID_CHAN_SENDER_EN}"
    )


def extract_explicit_exact_text(instruction: str) -> str | None:
    """Extract text that the operator explicitly requested to send verbatim."""
    command = re.match(r"^\s*/exact(?:\s+|$)([\s\S]*)$", instruction, re.I)
    if command:
        return command.group(1)

    marker = re.search(
        r"(?:exact(?:ly)?|verbatim|word[\s-]for[\s-]word|"
        r"原样|一字不改|逐字|照抄)",
        instruction,
        re.I,
    )
    if not marker:
        return None
    tail = instruction[marker.end() :]
    quoted_patterns = (
        r'["“](.*?)["”]',
        r"[「『](.*?)[」』]",
        r"'(.*?)'",
    )
    for pattern in quoted_patterns:
        match = re.search(pattern, tail, re.S)
        if match:
            return match.group(1)
    colon = re.search(r"(?:send|发送|内容)?\s*[:：]\s*([\s\S]+)$", tail, re.I)
    return colon.group(1) if colon else None


def _resolve_media(
    values: object,
    *,
    roots: Sequence[Path],
    extensions: set[str],
    location: str,
) -> tuple[Path, ...]:
    """Resolve and validate media files against roots, extensions, and size."""
    if not isinstance(values, list) or len(values) > MAX_MEDIA_FILES:
        raise WeChatActionError(
            f"{location} must be an array of at most {MAX_MEDIA_FILES} files"
        )
    resolved_roots = tuple(root.resolve() for root in roots)
    result: list[Path] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise WeChatActionError(f"{location}[{index}] must be a file path")
        path = Path(value).expanduser().resolve()
        if not any(path == root or root in path.parents for root in resolved_roots):
            raise WeChatActionError(
                f"{location}[{index}] is outside the approved media roots"
            )
        if not path.is_file():
            raise WeChatActionError(f"{location}[{index}] does not exist: {path}")
        if path.suffix.casefold() not in extensions:
            raise WeChatActionError(
                f"{location}[{index}] has an unsupported extension: {path.suffix}"
            )
        if path.stat().st_size > MAX_MEDIA_BYTES:
            raise WeChatActionError(
                f"{location}[{index}] exceeds {MAX_MEDIA_BYTES // (1024 * 1024)} MiB"
            )
        result.append(path)
    return tuple(result)


def resolve_message_media(
    values: Sequence[Path | str],
    *,
    roots: Sequence[Path],
) -> tuple[Path, ...]:
    """Validate manually supplied media paths for direct message sending."""
    return _resolve_media(
        [str(value) for value in values],
        roots=roots,
        extensions=MESSAGE_MEDIA_EXTENSIONS,
        location="media",
    )


def _clean_text(value: object, location: str, maximum: int) -> str:
    """Validate and trim an action text field within a maximum length."""
    if not isinstance(value, str):
        raise WeChatActionError(f"{location} must be a string")
    value = value.strip()
    if len(value) > maximum:
        raise WeChatActionError(f"{location} exceeds {maximum} characters")
    return value


def _contact_names(
    values: object,
    config: WeChatConfig,
    *,
    location: str,
) -> tuple[str, ...]:
    """Validate a list of exact allowlisted contact names."""
    if not isinstance(values, list) or len(values) > 100:
        raise WeChatActionError(f"{location} must be an array of at most 100 names")
    result: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or config.contact(value.strip()) is None:
            raise WeChatActionError(
                f"{location}[{index}] is not an exact allowlisted contact"
            )
        result.append(config.contact(value.strip()).name)
    return tuple(dict.fromkeys(result))


def parse_action_plan(
    data: object,
    config: WeChatConfig,
    *,
    media_roots: Sequence[Path],
) -> WeChatActionPlan:
    """Validate raw model JSON into an executable action plan."""
    if not isinstance(data, dict) or set(data) != {"actions"}:
        raise WeChatActionError("action plan must contain only an actions array")
    raw_actions = data["actions"]
    if (
        not isinstance(raw_actions, list)
        or not raw_actions
        or len(raw_actions) > MAX_ACTIONS
    ):
        raise WeChatActionError(
            f"actions must contain between 1 and {MAX_ACTIONS} items"
        )
    roots = tuple(media_roots)
    if not roots:
        raise WeChatActionError("at least one approved media root is required")

    actions: list[WeChatAction] = []
    for index, raw in enumerate(raw_actions):
        location = f"actions[{index}]"
        if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
            raise WeChatActionError(f"{location} must be an action object")
        action_type = raw["type"]
        if action_type == "send_message":
            if set(raw) != {"type", "recipient", "text", "media"}:
                raise WeChatActionError(f"{location} has unsupported fields")
            recipient = raw["recipient"]
            if not isinstance(recipient, str):
                raise WeChatActionError(f"{location}.recipient must be a string")
            contact = config.contact(recipient.strip())
            if contact is None:
                raise WeChatActionError(
                    f"{location}.recipient is not an exact allowlisted contact"
                )
            text = _clean_text(raw["text"], f"{location}.text", MAX_MESSAGE_CHARS)
            media = _resolve_media(
                raw["media"],
                roots=roots,
                extensions=MESSAGE_MEDIA_EXTENSIONS,
                location=f"{location}.media",
            )
            if not text and not media:
                raise WeChatActionError(f"{location} has no text or media")
            actions.append(SendMessageAction(contact.name, text, media))
            continue

        if action_type == "post_moment":
            expected = {
                "type",
                "text",
                "media",
                "visibility",
                "audience",
                "location",
                "remind",
            }
            if set(raw) != expected:
                raise WeChatActionError(f"{location} has unsupported fields")
            visibility = raw["visibility"]
            if visibility not in MOMENT_VISIBILITIES:
                raise WeChatActionError(f"{location}.visibility is invalid")
            audience = _contact_names(
                raw["audience"], config, location=f"{location}.audience"
            )
            if visibility in {"all", "private"} and audience:
                raise WeChatActionError(
                    f"{location}.audience must be empty for {visibility}"
                )
            if visibility in {"include", "exclude"} and not audience:
                raise WeChatActionError(
                    f"{location}.audience is required for {visibility}"
                )
            text = _clean_text(raw["text"], f"{location}.text", MAX_MOMENT_CHARS)
            media = _resolve_media(
                raw["media"],
                roots=roots,
                extensions=MOMENT_MEDIA_EXTENSIONS,
                location=f"{location}.media",
            )
            if not text and not media:
                raise WeChatActionError(f"{location} has no text or media")
            actions.append(
                PostMomentAction(
                    text=text,
                    media=media,
                    visibility=visibility,
                    audience=audience,
                    location=_clean_text(
                        raw["location"], f"{location}.location", 128
                    ),
                    remind=_contact_names(
                        raw["remind"], config, location=f"{location}.remind"
                    ),
                )
            )
            continue
        raise WeChatActionError(f"{location}.type is unsupported: {action_type}")
    return WeChatActionPlan(tuple(actions))


def assert_executable(
    plan: WeChatActionPlan, *, moments_supported: bool = False
) -> None:
    """Reject actions that the currently selected backend cannot perform."""
    for action in plan.actions:
        if not isinstance(action, PostMomentAction):
            continue
        if not moments_supported:
            raise WeChatCapabilityError(
                "the configured WeChat transport cannot publish Moments; "
                "select UI mode and install its runtime; no action was executed"
            )
        unsupported: list[str] = []
        if action.visibility != "all":
            unsupported.append(f"visibility={action.visibility}")
        if action.audience:
            unsupported.append("custom audience")
        if action.location:
            unsupported.append("location")
        if action.remind:
            unsupported.append("reminders")
        if unsupported:
            raise WeChatCapabilityError(
                "the UI Moments publisher cannot reliably enforce "
                + ", ".join(unsupported)
                + "; no action was executed"
            )
