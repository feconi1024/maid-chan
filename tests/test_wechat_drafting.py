import json
import unittest

from maid_chan.prompt import Example
from maid_chan.wechat_drafting import (
    DRAFTING_SYSTEM_PROMPT,
    MessageDraftingSession,
    extract_explicit_exact_text,
    run_interactive_drafting,
)


class FakeClient:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        return self.responses.pop(0)


class DraftingSessionTests(unittest.TestCase):
    def test_prompt_applies_maid_chan_voice_to_outbound_draft(self):
        self.assertIn("visible speaker and messenger", DRAFTING_SYSTEM_PROMPT)
        self.assertIn("operator owns their", DRAFTING_SYSTEM_PROMPT)
        self.assertIn("first person", DRAFTING_SYSTEM_PROMPT)
        self.assertIn("at least one recognizable flourish", DRAFTING_SYSTEM_PROMPT)

    def test_extracts_explicit_verbatim_text(self):
        self.assertEqual(extract_explicit_exact_text("/exact Hello!"), "Hello!")
        self.assertEqual(
            extract_explicit_exact_text('Send exactly: "Do not edit this."'),
            "Do not edit this.",
        )
        self.assertEqual(
            extract_explicit_exact_text("请原样发送：“下午三点见。”"),
            "下午三点见。",
        )
        self.assertIsNone(extract_explicit_exact_text("Draft a warm hello"))

    def test_drafting_uses_configured_identity_without_raw_canon_examples(self):
        client = FakeClient(
            [
                json.dumps(
                    {"draft": "Hello.", "maid_reply": "完成。", "mode": "draft"}
                )
            ]
        )
        session = MessageDraftingSession(
            client,
            recipient="Alice",
            examples=[Example("空太在哪里？", "龙之介大人正在忙。")],
            operator_name="Hehao",
            operator_honorific="大人",
        )
        session.revise("Say hello")
        payload = "\n".join(item["content"] for item in client.calls[0])
        self.assertIn("Hehao大人", payload)
        self.assertNotIn("空太在哪里", payload)
        self.assertNotIn("龙之介大人正在忙", payload)

    def test_drafts_then_revises_using_current_draft(self):
        client = FakeClient(
            [
                json.dumps(
                    {
                        "draft": "Are you free tomorrow?",
                        "maid_reply": "初稿完成。",
                        "mode": "draft",
                    }
                ),
                json.dumps(
                    {
                        "draft": "Would you happen to be free tomorrow?",
                        "maid_reply": "已经更客气了。",
                        "mode": "draft",
                    }
                ),
            ]
        )
        session = MessageDraftingSession(client, recipient="Alice")
        first = session.revise("Ask Alice whether she is free tomorrow")
        second = session.revise("Make it more polite")
        self.assertEqual(
            first.draft,
            "Maid-chan was entrusted to pass this along—do read carefully:\n"
            "“Are you free tomorrow?”\n— Sent by Maid-chan",
        )
        self.assertEqual(
            second.draft,
            "Maid-chan was entrusted to pass this along—do read carefully:\n"
            "“Would you happen to be free tomorrow?”\n— Sent by Maid-chan",
        )
        second_messages = client.calls[1]
        self.assertTrue(
            any(
                "Are you free tomorrow?" in message["content"]
                and "Sent by Maid-chan" not in message["content"]
                for message in second_messages
            )
        )

    def test_exact_mode_bypasses_model_and_preserves_text(self):
        client = FakeClient()
        session = MessageDraftingSession(client, recipient="Alice")
        revision = session.revise('Send verbatim: "Hello, Alice!"')
        self.assertEqual(revision.draft, "Hello, Alice!")
        self.assertEqual(revision.mode, "exact")
        self.assertEqual(client.calls, [])

    def test_interactive_flow_can_modify_and_confirm_send(self):
        client = FakeClient(
            [
                json.dumps(
                    {
                        "draft": "Hello Alice, are you free tomorrow?",
                        "maid_reply": "先写得自然一点。",
                        "mode": "draft",
                    }
                ),
                json.dumps(
                    {
                        "draft": "Hi Alice! Are you free tomorrow?",
                        "maid_reply": "已经更亲切了。",
                        "mode": "draft",
                    }
                ),
            ]
        )
        session = MessageDraftingSession(client, recipient="Alice")
        inputs = iter(["Make it warmer", "/send", "SEND"])
        output = []
        sent = []
        result = run_interactive_drafting(
            session,
            initial_instruction="Ask whether Alice is free tomorrow",
            allow_send=True,
            input_fn=lambda _: next(inputs),
            output=output.append,
            send_callback=lambda text, media: sent.append((text, tuple(media))),
        )
        self.assertTrue(result)
        self.assertEqual(
            sent,
            [
                (
                    "Maid-chan was entrusted to pass this along—do read "
                    "carefully:\n“Hi Alice! Are you free tomorrow?”\n"
                    "— Sent by Maid-chan",
                    (),
                )
            ],
        )
        self.assertTrue(any("发送预览" in line for line in output))

    def test_interactive_session_without_send_permission_keeps_draft(self):
        session = MessageDraftingSession(FakeClient(), recipient="Alice")
        session.set_exact("Hello")
        inputs = iter(["/send", "/cancel"])
        output = []
        result = run_interactive_drafting(
            session,
            allow_send=False,
            input_fn=lambda _: next(inputs),
            output=output.append,
        )
        self.assertFalse(result)
        self.assertEqual(session.draft, "Hello")
        self.assertTrue(any("未启用发送权限" in line for line in output))


if __name__ == "__main__":
    unittest.main()
