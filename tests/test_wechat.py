import tempfile
import unittest
import json
from pathlib import Path

from maid_chan.wechat import (
    WeChatAutoReplyRunner,
    WeChatConfigError,
    WeChatConfigStore,
    WeChatMessage,
    new_messages,
)


def message(content, *, attr="friend", type="text"):
    return WeChatMessage(attr, type, "Alice", content)


class FakeTransport:
    def __init__(self):
        self.messages = {"Alice": []}
        self.sent = []

    def connect(self):
        return "test"

    def read_chat(self, contact):
        return list(self.messages[contact])

    def send_text(self, contact, text):
        self.sent.append((contact, text))


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.resets = []

    def reply(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return "Maid reply"

    def reset(self, conversation_id=None):
        self.resets.append(conversation_id)


class ConfigStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "wechat.json"
        self.store = WeChatConfigStore(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def test_requires_allowlist_before_enabling(self):
        with self.assertRaises(WeChatConfigError):
            self.store.set_enabled(True)

    def test_add_enable_remove_fails_closed(self):
        self.store.add_contact("Alice", 2)
        self.store.set_enabled(True)
        config = self.store.load()
        self.assertTrue(config.enabled)
        self.assertEqual(config.contacts[0].memory_privacy_level, 2)
        config = self.store.remove_contact("Alice")
        self.assertFalse(config.enabled)
        self.assertEqual(config.contacts, ())

    def test_sets_validated_poll_interval(self):
        self.store.set_poll_interval(1.5)
        self.assertEqual(self.store.load().poll_interval, 1.5)
        with self.assertRaises(WeChatConfigError):
            self.store.set_poll_interval(0.1)

    def test_defaults_to_wechaty_and_persists_mode_switch(self):
        self.assertEqual(self.store.load().mode, "wechaty")
        self.assertEqual(self.store.set_mode("ui").mode, "ui")
        self.assertEqual(self.store.load().mode, "ui")
        with self.assertRaises(WeChatConfigError):
            self.store.set_mode("unsupported")

    def test_existing_version_one_config_without_mode_migrates_to_wechaty(self):
        self.path.write_text(
            json.dumps(
                {
                    "format": "maid-chan-wechat",
                    "version": 1,
                    "enabled": False,
                    "poll_interval": 2,
                    "contacts": [],
                }
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.store.load().mode, "wechaty")


class MessageDeltaTests(unittest.TestCase):
    def test_detects_append_and_shift(self):
        old = [message("one"), message("two")]
        self.assertEqual(new_messages(old, old + [message("three")]), [message("three")])
        self.assertEqual(
            new_messages(old, [message("two"), message("three")]),
            [message("three")],
        )

    def test_returns_none_when_snapshots_cannot_be_aligned(self):
        self.assertIsNone(new_messages([message("old")], [message("unrelated")]))


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = WeChatConfigStore(Path(self.directory.name) / "wechat.json")
        self.store.add_contact("Alice", 2)
        self.store.set_mode("ui")
        self.store.set_enabled(True)
        self.transport = FakeTransport()
        self.engine = FakeEngine()
        self.output = []
        self.runner = WeChatAutoReplyRunner(
            self.store,
            self.transport,
            self.engine,
            output=self.output.append,
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_baselines_then_replies_only_to_new_friend_text(self):
        self.transport.messages["Alice"] = [message("historical")]
        self.assertEqual(self.runner.poll_once(), 0)
        self.transport.messages["Alice"].extend(
            [
                message("my own", attr="self"),
                message("new incoming"),
                message("[image]", type="image"),
            ]
        )
        self.assertEqual(self.runner.poll_once(), 1)
        self.assertEqual(self.transport.sent, [("Alice", "Maid reply")])
        self.assertEqual(self.engine.calls[0][0], "new incoming")
        self.assertEqual(
            self.engine.calls[0][1]["memory_privacy_level"],
            2,
        )

    def test_reenable_rebaselines_instead_of_replying_to_backlog(self):
        self.runner.poll_once()
        self.store.set_enabled(False)
        self.runner.poll_once()
        self.transport.messages["Alice"].append(message("while disabled"))
        self.store.set_enabled(True)
        self.assertEqual(self.runner.poll_once(), 0)
        self.assertEqual(self.transport.sent, [])

    def test_switching_to_wechaty_disables_ui_runner(self):
        self.runner.poll_once()
        self.store.set_mode("wechaty")
        self.transport.messages["Alice"].append(message("after switch"))
        self.assertEqual(self.runner.poll_once(), 0)
        self.assertEqual(self.transport.sent, [])


if __name__ == "__main__":
    unittest.main()
