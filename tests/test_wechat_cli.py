from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maid_chan.wechat import WeChatConfigStore
from maid_chan.wechat_cli import main


class WeChatCliModeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "wechat.json"

    def test_mode_command_persists_ui_selection(self):
        result = main(["--config", str(self.path), "mode", "ui"])
        self.assertEqual(result, 0)
        self.assertEqual(WeChatConfigStore(self.path).load().mode, "ui")

    @patch("maid_chan.wechat_cli.send_many_with_wx4py")
    def test_send_uses_selected_ui_transport(self, send_many):
        store = WeChatConfigStore(self.path)
        store.add_contact("Alice")
        store.set_mode("ui")
        result = main(
            [
                "--config",
                str(self.path),
                "send",
                "Alice",
                "hello",
                "--accept-account-risk",
            ]
        )
        self.assertEqual(result, 0)
        messages = send_many.call_args.args[0]
        self.assertEqual(messages[0][0:2], ("Alice", "hello"))

    @patch("maid_chan.wechat_cli.PyWeixinMomentsPublisher")
    def test_moment_uses_ui_publisher_after_preview_and_confirmation(
        self, publisher
    ):
        store = WeChatConfigStore(self.path)
        store.set_mode("ui")
        publisher.dependency_available.return_value = True
        result = main(
            [
                "--config",
                str(self.path),
                "moment",
                "hello",
                "--yes",
                "--accept-account-risk",
            ]
        )
        self.assertEqual(result, 0)
        action = publisher.return_value.publish.call_args.args[0]
        self.assertEqual(action.text, "hello")


if __name__ == "__main__":
    unittest.main()
