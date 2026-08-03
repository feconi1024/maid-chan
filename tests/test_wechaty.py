import tempfile
import unittest
from pathlib import Path

from maid_chan.wechat import WeChatConfigStore
from maid_chan.wechaty import (
    WechatyAutoReplyRunner,
    WechatyRuntime,
    logout_session,
    send_many_to_names,
)


class FakeEngine:
    def __init__(self):
        self.calls = []

    def reply(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return "Maid reply"


class FakeBridge:
    def __init__(self):
        self.commands = []

    def command(self, command_type, **payload):
        self.commands.append((command_type, payload))
        return "request-id"


class FakeLogoutBridge:
    def __init__(self, runtime, **kwargs):
        self.runtime = runtime
        self.command_type = ""
        self.stopped = False

    def start(self):
        pass

    def command(self, command_type, **payload):
        self.command_type = command_type
        return "logout-request"

    def events(self):
        yield {"type": "started"}
        yield {
            "type": "result",
            "requestId": "logout-request",
            "ok": True,
            "remoteAttempted": True,
            "credentialsCleared": True,
        }

    def stop(self):
        self.stopped = True


class FakeSendBridge:
    def __init__(self, runtime, **kwargs):
        self.commands = []
        self.stopped = False

    def start(self):
        pass

    def command(self, command_type, **payload):
        request_id = f"request-{len(self.commands) + 1}"
        self.commands.append((request_id, command_type, payload))
        return request_id

    def events(self):
        yield {"type": "login", "user": {"name": "Owner"}}
        yielded = 0
        while yielded < 2:
            if len(self.commands) <= yielded:
                raise AssertionError("next send was not submitted")
            request_id = self.commands[yielded][0]
            yielded += 1
            yield {"type": "result", "requestId": request_id, "ok": True}

    def stop(self):
        self.stopped = True


def private_message(
    message_id="message-1",
    text="hello",
    *,
    contact_id="contact-1",
    name="Alice",
    alias="Alice Remark",
):
    return {
        "type": "message",
        "id": message_id,
        "text": text,
        "contact": {"id": contact_id, "name": name, "alias": alias},
        "room": None,
    }


class WechatyRuntimeTests(unittest.TestCase):
    def test_prepare_files_copies_pinned_bridge_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = WechatyRuntime(
                Path(directory) / "runtime", Path(directory) / "profile"
            )
            runtime.prepare_files()
            self.assertTrue((runtime.runtime_path / "bridge.mjs").exists())
            self.assertTrue((runtime.runtime_path / "package-lock.json").exists())
            package = (runtime.runtime_path / "package.json").read_text()
            self.assertIn('"wechaty": "1.20.2"', package)
            self.assertIn('"wechaty-puppet-wechat4u": "1.14.14"', package)

    def test_quarantines_a_truncated_profile_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = WechatyRuntime(
                Path(directory) / "runtime", Path(directory) / "profile"
            )
            runtime.profile_path.mkdir(parents=True)
            runtime.profile_file.write_text('{"broken":', encoding="utf-8")
            output = []
            backup = runtime.quarantine_corrupt_profile(output=output.append)
            self.assertIsNotNone(backup)
            self.assertFalse(runtime.profile_file.exists())
            self.assertEqual(backup.read_text(encoding="utf-8"), '{"broken":')
            self.assertTrue(any("profile 损坏" in line for line in output))

    def test_logout_requests_remote_logout_and_credential_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = WechatyRuntime(
                Path(directory) / "runtime", Path(directory) / "profile"
            )
            output = []
            created = []

            def factory(*args, **kwargs):
                bridge = FakeLogoutBridge(*args, **kwargs)
                created.append(bridge)
                return bridge

            logout_session(runtime, output=output.append, bridge_factory=factory)
            self.assertEqual(created[0].command_type, "logout")
            self.assertTrue(created[0].stopped)
            self.assertTrue(any("服务端注销" in line for line in output))
            self.assertTrue(any("自动登录凭据已清除" in line for line in output))

    def test_sends_multiple_actions_sequentially_with_media(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = WechatyRuntime(
                Path(directory) / "runtime", Path(directory) / "profile"
            )
            media = Path(directory) / "image.jpg"
            media.write_bytes(b"image")
            created = []

            def factory(*args, **kwargs):
                bridge = FakeSendBridge(*args, **kwargs)
                created.append(bridge)
                return bridge

            send_many_to_names(
                runtime,
                [
                    ("Alice", "one", (media,)),
                    ("Bob", "two", ()),
                ],
                output=lambda _: None,
                bridge_factory=factory,
            )
            commands = created[0].commands
            self.assertEqual([item[2]["name"] for item in commands], ["Alice", "Bob"])
            self.assertEqual(commands[0][2]["files"], [str(media.resolve())])
            self.assertTrue(created[0].stopped)


class WechatyRunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = WeChatConfigStore(Path(self.directory.name) / "wechat.json")
        self.store.add_contact("Alice Remark", 2)
        self.store.set_enabled(True)
        self.bridge = FakeBridge()
        self.engine = FakeEngine()
        self.output = []
        self.runner = WechatyAutoReplyRunner(
            self.store,
            self.bridge,
            self.engine,
            output=self.output.append,
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_replies_to_allowed_private_alias(self):
        self.assertEqual(self.runner.handle_event(private_message()), 1)
        self.assertEqual(
            self.bridge.commands,
            [
                (
                    "send",
                    {"contactId": "contact-1", "text": "Maid reply"},
                )
            ],
        )
        self.assertEqual(self.engine.calls[0][0], "hello")
        self.assertEqual(
            self.engine.calls[0][1],
            {
                "conversation_id": "wechaty:Alice Remark",
                "memory_privacy_level": 2,
            },
        )

    def test_toggle_is_checked_for_each_event(self):
        self.store.set_enabled(False)
        self.assertEqual(self.runner.handle_event(private_message()), 0)
        self.assertEqual(self.bridge.commands, [])

    def test_switching_to_ui_disables_wechaty_runner(self):
        self.store.set_mode("ui")
        self.assertEqual(self.runner.handle_event(private_message()), 0)
        self.assertEqual(self.bridge.commands, [])

    def test_unknown_contact_and_group_are_not_replied_to(self):
        unknown = private_message(name="Mallory", alias="")
        self.assertEqual(self.runner.handle_event(unknown), 0)
        group = private_message(message_id="message-2")
        group["room"] = {"id": "room-1", "topic": "Group"}
        self.assertEqual(self.runner.handle_event(group), 0)
        self.assertEqual(self.bridge.commands, [])

    def test_duplicate_message_id_is_ignored(self):
        event = private_message()
        self.assertEqual(self.runner.handle_event(event), 1)
        self.assertEqual(self.runner.handle_event(event), 0)
        self.assertEqual(len(self.bridge.commands), 1)


if __name__ == "__main__":
    unittest.main()
