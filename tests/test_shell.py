from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from maid_chan.config import Settings
from maid_chan.shell import MaidChanShell, ShellAction


class FakeClient:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        return self.responses.pop(0)


class ShellTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.output = []
        self.settings = Settings(
            api_key="secret",
            base_url="https://example.test/v1",
            model="test-model",
            stream=False,
        )

    def shell(self, client=None, inputs=()):
        answers = iter(inputs)
        return MaidChanShell(
            client or FakeClient(),
            self.settings,
            input_fn=lambda _: next(answers),
            output=self.output.append,
            wechat_main=lambda argv: self.calls.append(list(argv)) or 0,
        )

    def test_status_alias_delegates_to_existing_wechat_cli(self):
        result = self.shell().handle("/status")
        self.assertIs(result.action, ShellAction.HANDLED)
        self.assertEqual(self.calls, [["status"]])

    def test_raw_wechat_command_is_retained_as_escape_hatch(self):
        self.shell().handle("/wechat future-operation --example")
        self.assertEqual(
            self.calls,
            [["future-operation", "--example"]],
        )

    def test_allow_add_shorthand_converts_privacy_level(self):
        self.shell().handle('/allow add "Alice Smith" 3')
        self.assertEqual(
            self.calls,
            [
                [
                    "allow",
                    "add",
                    "Alice Smith",
                    "--memory-privacy-level",
                    "3",
                ]
            ],
        )

    def test_send_alias_uses_drafting_instead_of_literal_send(self):
        self.shell(inputs=[""]).handle('/send Alice "ask whether she is free"')
        argv = self.calls[0]
        self.assertEqual(argv[:3], ["compose", "Alice", "ask whether she is free"])
        self.assertIn("--api-key", argv)
        self.assertNotIn("--accept-account-risk", argv)

    def test_compose_can_enable_sending_with_interactive_risk_acceptance(self):
        self.shell(inputs=["ACCEPT RISK"]).handle("/compose Alice say hello")
        self.assertIn("--accept-account-risk", self.calls[0])

    def test_ordinary_message_is_classified_and_returned_to_chat(self):
        client = FakeClient(
            [
                json.dumps(
                    {
                        "operation": "chat",
                        "name": "",
                        "prompt": "",
                        "privacy_level": 1,
                    }
                )
            ]
        )
        result = self.shell(client).handle("今天过得怎么样？")
        self.assertIs(result.action, ShellAction.CHAT)
        self.assertEqual(result.message, "今天过得怎么样？")
        self.assertEqual(len(client.calls), 1)

    def test_natural_help_is_available_without_wechat_keywords(self):
        client = FakeClient(
            [
                json.dumps(
                    {
                        "operation": "help",
                        "name": "",
                        "prompt": "",
                        "privacy_level": 1,
                    }
                )
            ]
        )
        result = self.shell(client).handle("Show me everything you can do")
        self.assertIs(result.action, ShellAction.HANDLED)
        self.assertIn("/help", "\n".join(self.output))

    def test_natural_doctor_preserves_explicit_timeout(self):
        client = FakeClient(
            [
                json.dumps(
                    {
                        "operation": "doctor",
                        "name": "",
                        "prompt": "",
                        "privacy_level": 1,
                        "media": [],
                        "media_roots": [],
                        "timeout_seconds": 45,
                        "dry_run": False,
                    }
                )
            ]
        )
        self.shell(client).handle("Check WeChat startup with a 45 second timeout")
        self.assertEqual(self.calls, [["doctor", "--timeout", "45.0"]])

    def test_natural_exact_send_is_verbatim_and_risk_gated(self):
        client = FakeClient(
            [
                json.dumps(
                    {
                        "operation": "send_exact",
                        "name": "Alice",
                        "prompt": "Keep THIS punctuation!",
                        "privacy_level": 1,
                        "media": ["photo.jpg"],
                        "media_roots": ["."],
                        "timeout_seconds": 30,
                        "dry_run": False,
                    }
                )
            ]
        )
        self.shell(client, inputs=["ACCEPT RISK"]).handle(
            "Send Alice exactly Keep THIS punctuation! with photo.jpg from ."
        )
        self.assertEqual(
            self.calls,
            [[
                "send",
                "Alice",
                "Keep THIS punctuation!",
                "--media",
                "photo.jpg",
                "--media-root",
                ".",
                "--accept-account-risk",
            ]],
        )

    def test_natural_exact_send_rejects_model_rewritten_text(self):
        client = FakeClient(
            [
                json.dumps(
                    {
                        "operation": "send_exact",
                        "name": "Alice",
                        "prompt": "rewritten text",
                        "privacy_level": 1,
                    }
                )
            ]
        )
        self.shell(client).handle("Send Alice exactly hello")
        self.assertEqual(self.calls, [])
        self.assertTrue(any("逐字文本" in line for line in self.output))

    def test_natural_moment_dry_run_needs_no_account_risk_acceptance(self):
        client = FakeClient(
            [
                json.dumps(
                    {
                        "operation": "moment",
                        "name": "",
                        "prompt": "hello world",
                        "privacy_level": 1,
                        "media": [],
                        "media_roots": [],
                        "timeout_seconds": 30,
                        "dry_run": True,
                    }
                )
            ]
        )
        self.shell(client).handle("Preview only a Moment saying hello world")
        self.assertEqual(self.calls, [["moment", "hello world", "--dry-run"]])

    def test_natural_status_routes_through_wechat_cli(self):
        client = FakeClient(
            [
                json.dumps(
                    {
                        "operation": "status",
                        "name": "",
                        "prompt": "",
                        "privacy_level": 1,
                    }
                )
            ]
        )
        result = self.shell(client).handle("Show WeChat status")
        self.assertIs(result.action, ShellAction.HANDLED)
        self.assertEqual(self.calls, [["status"]])

    def test_natural_mode_switch_requires_confirmation(self):
        client = FakeClient(
            [
                json.dumps(
                    {
                        "operation": "mode_ui",
                        "name": "",
                        "prompt": "",
                        "privacy_level": 1,
                    }
                )
            ]
        )
        self.shell(client, inputs=["RUN"]).handle(
            "Switch the WeChat automation mode to wx4py"
        )
        self.assertEqual(self.calls, [["mode", "ui"]])

    def test_natural_allowlist_change_requires_confirmation(self):
        client = FakeClient(
            [
                json.dumps(
                    {
                        "operation": "allow_add",
                        "name": "Alice",
                        "prompt": "",
                        "privacy_level": 2,
                    }
                )
            ]
        )
        self.shell(client, inputs=["no"]).handle("Add Alice to WeChat allowlist")
        self.assertEqual(self.calls, [])
        self.assertTrue(any("已取消" in line for line in self.output))

    def test_forced_natural_compose_routes_and_keeps_draft_only(self):
        client = FakeClient(
            [
                json.dumps(
                    {
                        "operation": "compose",
                        "name": "Alice",
                        "prompt": "Ask whether she is free tomorrow",
                        "privacy_level": 1,
                    }
                )
            ]
        )
        self.shell(client, inputs=[""]).handle(
            "/do draft a WeChat message to Alice asking if she is free tomorrow"
        )
        self.assertEqual(self.calls[0][:3], [
            "compose",
            "Alice",
            "Ask whether she is free tomorrow",
        ])

    def test_natural_router_cannot_invent_a_contact(self):
        client = FakeClient(
            [
                json.dumps(
                    {
                        "operation": "compose",
                        "name": "Alice",
                        "prompt": "Say hello",
                        "privacy_level": 1,
                    }
                )
            ]
        )
        self.shell(client).handle("/do send someone a friendly hello")
        self.assertEqual(self.calls, [])
        self.assertTrue(any("没有明确写出的联系人" in line for line in self.output))

    def test_natural_act_preserves_original_operator_prompt(self):
        client = FakeClient(
            [
                json.dumps(
                    {
                        "operation": "act",
                        "name": "",
                        "prompt": "altered by router",
                        "privacy_level": 1,
                    }
                )
            ]
        )
        original = "Post a WeChat Moment saying hello"
        self.shell(client, inputs=["ACCEPT RISK"]).handle("/do " + original)
        self.assertEqual(self.calls[0][0:2], ["act", original])

    def test_reset_and_exit_are_returned_to_chat_loop(self):
        shell = self.shell()
        self.assertIs(shell.handle("/reset").action, ShellAction.RESET)
        self.assertIs(shell.handle("/quit").action, ShellAction.EXIT)

    def test_help_lists_all_command_groups_and_usage(self):
        result = self.shell().handle("/help")
        self.assertIs(result.action, ShellAction.HANDLED)
        help_text = "\n".join(self.output)
        for command in (
            "/status",
            "/mode ui|wechaty",
            "/auth",
            "/logout",
            "/allow add",
            "/auto on",
            "/compose",
            "/act",
            "/wechat send",
            "/exact",
            "/wechat /help",
        ):
            self.assertIn(command, help_text)


if __name__ == "__main__":
    unittest.main()
