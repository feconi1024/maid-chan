import json
import tempfile
import unittest
from pathlib import Path

from maid_chan.wechat import WeChatConfigStore
from maid_chan.wechat_actions import (
    ACTION_PLANNER_SYSTEM,
    PostMomentAction,
    SendMessageAction,
    WeChatActionError,
    WeChatActionPlanner,
    WeChatCapabilityError,
    assert_executable,
    ensure_maid_chan_sender,
    format_maid_chan_message,
    parse_action_plan,
)


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.messages = None

    def complete(self, messages):
        self.messages = messages
        return self.response


class WeChatActionTests(unittest.TestCase):
    def test_planner_prompt_applies_maid_chan_voice_to_composed_text(self):
        self.assertIn("operator is the principal", ACTION_PLANNER_SYSTEM)
        self.assertIn("refer to the operator", ACTION_PLANNER_SYSTEM)
        self.assertIn("second-person pronouns", ACTION_PLANNER_SYSTEM)
        self.assertIn("application adds that envelope", ACTION_PLANNER_SYSTEM)
        self.assertIn("strong editorial personality", ACTION_PLANNER_SYSTEM)

    def test_sender_attribution_is_enforced_by_text_language(self):
        self.assertEqual(
            ensure_maid_chan_sender("Good morning"),
            "Good morning\n— Sent by Maid-chan",
        )
        self.assertEqual(
            ensure_maid_chan_sender("早上好"),
            "早上好\n——由女仆酱发送",
        )
        attributed = "任务完成。\n——由女仆酱发送"
        self.assertEqual(ensure_maid_chan_sender(attributed), attributed)

    def test_message_envelope_separates_operator_and_maid_chan_perspectives(self):
        self.assertEqual(
            format_maid_chan_message("I will arrive tomorrow."),
            "Maid-chan was entrusted to pass this along—do read carefully:\n"
            "“I will arrive tomorrow.”\n— Sent by Maid-chan",
        )
        self.assertEqual(
            format_maid_chan_message("我明天下午会到。"),
            "女仆已接过传话任务，还请您认真查收：\n"
            "「我明天下午会到。」\n——由女仆酱发送",
        )

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.store = WeChatConfigStore(self.root / "wechat.json")
        self.store.add_contact("Alice", 1)
        self.store.add_contact("Bob", 1)
        self.config = self.store.load()
        self.image = self.root / "photo.jpg"
        self.image.write_bytes(b"jpeg")

    def tearDown(self):
        self.directory.cleanup()

    def test_parses_allowlisted_message_with_media(self):
        plan = parse_action_plan(
            {
                "actions": [
                    {
                        "type": "send_message",
                        "recipient": "Alice",
                        "text": "hello",
                        "media": [str(self.image)],
                    }
                ]
            },
            self.config,
            media_roots=[self.root],
        )
        action = plan.actions[0]
        self.assertIsInstance(action, SendMessageAction)
        self.assertEqual(action.recipient, "Alice")
        self.assertEqual(action.media, (self.image.resolve(),))
        assert_executable(plan)

    def test_rejects_unknown_recipient_and_media_outside_root(self):
        payload = {
            "actions": [
                {
                    "type": "send_message",
                    "recipient": "Mallory",
                    "text": "hello",
                    "media": [],
                }
            ]
        }
        with self.assertRaisesRegex(WeChatActionError, "allowlisted"):
            parse_action_plan(payload, self.config, media_roots=[self.root])

        payload["actions"][0]["recipient"] = "Alice"
        outside = Path(tempfile.gettempdir()) / "maid-chan-outside.jpg"
        payload["actions"][0]["media"] = [str(outside)]
        with self.assertRaisesRegex(WeChatActionError, "outside"):
            parse_action_plan(payload, self.config, media_roots=[self.root])

    def test_validates_moment_attributes_but_rejects_unsupported_controls(self):
        plan = parse_action_plan(
            {
                "actions": [
                    {
                        "type": "post_moment",
                        "text": "hello",
                        "media": [str(self.image)],
                        "visibility": "include",
                        "audience": ["Alice"],
                        "location": "Shanghai",
                        "remind": ["Bob"],
                    }
                ]
            },
            self.config,
            media_roots=[self.root],
        )
        action = plan.actions[0]
        self.assertIsInstance(action, PostMomentAction)
        self.assertEqual(action.visibility, "include")
        self.assertEqual(action.audience, ("Alice",))
        with self.assertRaisesRegex(WeChatCapabilityError, "cannot publish Moments"):
            assert_executable(plan)
        with self.assertRaisesRegex(WeChatCapabilityError, "cannot reliably enforce"):
            assert_executable(plan, moments_supported=True)

    def test_allows_basic_moment_when_publisher_is_available(self):
        plan = parse_action_plan(
            {
                "actions": [
                    {
                        "type": "post_moment",
                        "text": "hello",
                        "media": [str(self.image)],
                        "visibility": "all",
                        "audience": [],
                        "location": "",
                        "remind": [],
                    }
                ]
            },
            self.config,
            media_roots=[self.root],
        )
        assert_executable(plan, moments_supported=True)

    def test_rejects_public_moment_with_audience(self):
        with self.assertRaisesRegex(WeChatActionError, "must be empty"):
            parse_action_plan(
                {
                    "actions": [
                        {
                            "type": "post_moment",
                            "text": "hello",
                            "media": [],
                            "visibility": "all",
                            "audience": ["Alice"],
                            "location": "",
                            "remind": [],
                        }
                    ]
                },
                self.config,
                media_roots=[self.root],
            )

    def test_planner_uses_strict_json_and_allowlist_validation(self):
        response = json.dumps(
            {
                "actions": [
                    {
                        "type": "send_message",
                        "recipient": "Alice",
                        "text": "Good morning",
                        "media": [],
                    }
                ]
            }
        )
        client = FakeClient(response)
        plan = WeChatActionPlanner(client).plan(
            "Tell Alice good morning",
            self.config,
            media_roots=[self.root],
        )
        self.assertEqual(
            plan.actions[0].text,
            "Maid-chan was entrusted to pass this along—do read carefully:\n"
            "“Good morning”\n— Sent by Maid-chan",
        )
        self.assertTrue(
            any("Allowed contact names" in item["content"] for item in client.messages)
        )

    def test_planner_mechanically_enforces_explicit_exact_text(self):
        client = FakeClient(
            json.dumps(
                {
                    "actions": [
                        {
                            "type": "send_message",
                            "recipient": "Alice",
                            "text": "model tried to rewrite it",
                            "media": [],
                        }
                    ]
                }
            )
        )
        plan = WeChatActionPlanner(client).plan(
            'Send Alice exactly: "Keep THIS punctuation!"',
            self.config,
            media_roots=[self.root],
        )
        self.assertEqual(plan.actions[0].text, "Keep THIS punctuation!")

    def test_planner_cannot_invent_recipient_or_media_path(self):
        invented_recipient = FakeClient(
            json.dumps(
                {
                    "actions": [
                        {
                            "type": "send_message",
                            "recipient": "Bob",
                            "text": "hello",
                            "media": [],
                        }
                    ]
                }
            )
        )
        with self.assertRaisesRegex(WeChatActionError, "not explicitly named"):
            WeChatActionPlanner(invented_recipient).plan(
                "Send Alice hello",
                self.config,
                media_roots=[self.root],
            )

        invented_media = FakeClient(
            json.dumps(
                {
                    "actions": [
                        {
                            "type": "send_message",
                            "recipient": "Alice",
                            "text": "hello",
                            "media": [str(self.image)],
                        }
                    ]
                }
            )
        )
        with self.assertRaisesRegex(WeChatActionError, "media path"):
            WeChatActionPlanner(invented_media).plan(
                "Send Alice hello",
                self.config,
                media_roots=[self.root],
            )


if __name__ == "__main__":
    unittest.main()
