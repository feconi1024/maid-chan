"""Transport-neutral conversation engine for Maid-chan replies."""

from __future__ import annotations

from collections.abc import Sequence

from .client import ChatClient
from .config import Settings
from .memory import Memory
from .prompt import Example, build_messages


class MaidChanEngine:
    """Transport-neutral conversational reply engine."""

    def __init__(
        self,
        client: ChatClient,
        settings: Settings,
        examples: Sequence[Example],
        memories: Sequence[Memory] = (),
    ):
        """Create an engine with shared examples and optional profile memories."""
        self.client = client
        self.settings = settings
        self.examples = examples
        self.memories = memories
        self._histories: dict[str, list[dict[str, str]]] = {}

    def reply(
        self,
        message: str,
        *,
        conversation_id: str = "default",
        memory_privacy_level: int | None = None,
    ) -> str:
        """Generate a reply and append the exchange to per-conversation history."""
        history = self._histories.setdefault(conversation_id, [])
        messages = build_messages(
            self.examples,
            history,
            message,
            few_shot_count=self.settings.few_shot_count,
            history_turns=self.settings.history_turns,
            memories=self.memories,
            memory_max_chars=self.settings.memory_max_chars,
            memory_privacy_level=(
                self.settings.memory_privacy_level
                if memory_privacy_level is None
                else memory_privacy_level
            ),
            memory_include_restricted=False,
        )
        reply = self.client.complete(messages)
        history.extend(
            (
                {"role": "user", "content": message},
                {"role": "assistant", "content": reply},
            )
        )
        del history[: max(0, len(history) - self.settings.history_turns * 2)]
        return reply

    def reset(self, conversation_id: str | None = None) -> None:
        """Clear all histories, or only the named conversation history."""
        if conversation_id is None:
            self._histories.clear()
        else:
            self._histories.pop(conversation_id, None)
