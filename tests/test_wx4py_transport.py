from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from maid_chan.wechat import WeChatError
from maid_chan.wx4py_transport import (
    Wx4PyTransport,
    install_wx4py,
    send_many_with_wx4py,
)


class FakeChat:
    def __init__(self):
        self.search_results = {
            "联系人": [SimpleNamespace(name="Alice")],
            "最常使用": [],
        }
        self.history = []
        self.opened = []
        self.sent = []
        self.files = []

    def search(self, name):
        return self.search_results

    def open_chat(self, name, **kwargs):
        self.opened.append((name, kwargs))
        return True

    def get_chat_history(self, *args, **kwargs):
        return list(self.history)

    def send_message(self, text):
        self.sent.append(text)
        return True

    def send_file(self, paths, message=None):
        self.files.append((list(paths), message))
        return True


class FakeClient:
    def __init__(self):
        self.chat_window = FakeChat()
        self.connected = False
        self.disconnected = False

    def connect(self):
        self.connected = True
        return True

    def disconnect(self):
        self.disconnected = True


class Wx4PyTransportTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.transport = Wx4PyTransport(lambda: self.client)
        self.transport.connect()

    def test_connects_and_sends_text_to_exact_contact(self):
        self.transport.send_text("Alice", "hello")
        self.assertEqual(self.client.chat_window.sent, ["hello"])
        self.assertEqual(self.client.chat_window.opened[0][0], "Alice")

    def test_rejects_non_exact_contact_result(self):
        self.client.chat_window.search_results["联系人"] = [
            SimpleNamespace(name="Alice Cooper")
        ]
        with self.assertRaisesRegex(WeChatError, "one exact contact"):
            self.transport.send_text("Alice", "hello")

    def test_rejects_partial_result_even_when_exact_result_also_exists(self):
        self.client.chat_window.search_results["联系人"] = [
            SimpleNamespace(name="Alice Cooper"),
            SimpleNamespace(name="Alice"),
        ]
        with self.assertRaisesRegex(WeChatError, "one exact contact"):
            self.transport.send_text("Alice", "hello")

    def test_marks_transport_sent_history_as_self(self):
        self.transport.send_text("Alice", "bot reply")
        self.client.chat_window.history = [
            {"type": "text", "content": "incoming", "time": "12:00"},
            {"type": "text", "content": "bot reply", "time": "12:01"},
        ]
        messages = self.transport.read_chat("Alice")
        self.assertEqual([item.attr for item in messages], ["friend", "self"])

    def test_sends_files_with_optional_text(self):
        path = Path("photo.png")
        self.transport.send_payload("Alice", "caption", [path])
        sent_paths, caption = self.client.chat_window.files[0]
        self.assertTrue(sent_paths[0].endswith("photo.png"))
        self.assertEqual(caption, "caption")

    def test_batch_helper_disconnects(self):
        client = FakeClient()
        output = []
        send_many_with_wx4py(
            [("Alice", "hello", ())],
            output=output.append,
            transport_factory=lambda: Wx4PyTransport(lambda: client),
        )
        self.assertTrue(client.disconnected)
        self.assertTrue(any("Alice" in line for line in output))

    @patch("maid_chan.wx4py_transport.subprocess.run")
    def test_installer_uses_pinned_version(self, run):
        with (
            patch("maid_chan.wx4py_transport.sys.prefix", "same"),
            patch("maid_chan.wx4py_transport.sys.base_prefix", "same"),
        ):
            install_wx4py(output=lambda _: None)
        command = run.call_args.args[0]
        self.assertIn("wx4py==0.2.1", command)
        self.assertIn("--user", command)


if __name__ == "__main__":
    unittest.main()
