import json
import tempfile
import unittest
from pathlib import Path

from maid_chan.memory import Memory
from maid_chan.prompt import Example, build_messages, load_examples, select_examples


class PromptTests(unittest.TestCase):
    def test_loads_jsonl_examples(self):
        record = {
            "confidence": "high",
            "messages": [
                {"role": "user", "content": "龙之介在吗？"},
                {"role": "assistant", "content": "龙之介大人正在忙。"},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "examples.jsonl"
            path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
            self.assertEqual(
                load_examples(path),
                [Example("龙之介在吗？", "龙之介大人正在忙。", "high")],
            )

    def test_selects_relevant_example(self):
        examples = [
            Example("今天天气如何？", "天气很好。"),
            Example("龙之介睡了吗？", "龙之介大人已经休息了。"),
        ]
        selected = select_examples(examples, "龙之介大人在睡觉吗", 1)
        self.assertEqual(selected[0], examples[1])

    def test_builds_system_few_shot_history_and_current_message(self):
        examples = [Example("示例问题", "示例回答")]
        history = [
            {"role": "user", "content": "旧问题"},
            {"role": "assistant", "content": "旧回答"},
        ]
        messages = build_messages(
            examples,
            history,
            "新问题",
            few_shot_count=1,
            history_turns=1,
        )
        self.assertEqual(
            [message["role"] for message in messages],
            ["system", "user", "assistant", "user", "assistant", "user"],
        )
        self.assertEqual(messages[-1]["content"], "新问题")

    def test_places_external_memory_in_separate_system_message(self):
        memory = Memory(
            id="manual:identity:name",
            kind="identity",
            content="The master's display name is Hehao.",
            confidence=1.0,
            importance=5,
            sensitivity="private",
            status="active",
            tags=(),
            source_platform="manual",
            subject_display_name="Hehao",
        )
        messages = build_messages(
            [],
            [],
            "你好",
            few_shot_count=0,
            history_turns=0,
            memories=[memory],
        )
        self.assertEqual(
            [message["role"] for message in messages],
            ["system", "system", "user"],
        )
        self.assertIn("manual:identity:name", messages[1]["content"])
        self.assertIn('"display_name":"Hehao"', messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
