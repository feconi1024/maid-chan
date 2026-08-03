import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maid_chan.weixin import (
    WeixinAutoReplyRunner,
    WeixinConfigError,
    WeixinIlinkAPI,
    WeixinStateStore,
)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeEngine:
    def __init__(self):
        self.calls = []

    def reply(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return "Maid API reply"


class FakeAPI:
    responses = []
    sent = []
    starts = 0
    stops = 0

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def get_updates(self, cursor, long_poll_timeout_ms=35_000):
        return self.responses.pop(0)

    def send_text(self, user_id, context_token, text):
        self.sent.append((user_id, context_token, text))

    def notify_start(self):
        type(self).starts += 1

    def notify_stop(self):
        type(self).stops += 1


def inbound(user_id, text, context="context-1"):
    return {
        "message_id": 1,
        "message_type": 1,
        "from_user_id": user_id,
        "context_token": context,
        "item_list": [{"type": 1, "text_item": {"text": text}}],
    }


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = WeixinStateStore(Path(self.directory.name) / "state.json")

    def tearDown(self):
        self.directory.cleanup()

    def test_requires_login_and_allowlist_before_enabling(self):
        with self.assertRaises(WeixinConfigError):
            self.store.set_enabled(True)
        self.store.save_login(
            account_id="bot-id",
            token="secret",
            base_url="https://ilink.example",
            owner_user_id="owner-id",
        )
        with self.assertRaises(WeixinConfigError):
            self.store.set_enabled(True)

    def test_roundtrips_login_and_stable_id_allowlist(self):
        self.store.save_login(
            account_id="bot-id",
            token="secret",
            base_url="https://ilink.example",
            owner_user_id="owner-id",
        )
        self.store.add_contact("user-id", "Alice", 2)
        state = self.store.set_enabled(True)
        self.assertTrue(state.authenticated)
        self.assertTrue(state.enabled)
        self.assertEqual(state.contact("user-id").label, "Alice")
        self.assertEqual(state.contact("user-id").memory_privacy_level, 2)

    def test_logout_removes_credentials_and_disables(self):
        self.store.save_login(
            account_id="bot-id",
            token="secret",
            base_url="https://ilink.example",
            owner_user_id="owner-id",
        )
        state = self.store.clear_login()
        self.assertFalse(state.authenticated)
        self.assertFalse(state.enabled)

    def test_worker_lease_rejects_a_second_local_worker(self):
        with self.store.worker_lease():
            with self.assertRaisesRegex(
                WeixinConfigError, "another local Weixin worker"
            ):
                with self.store.worker_lease():
                    pass

    def test_worker_lease_replaces_a_stale_lock(self):
        lock_path = self.store.path.with_suffix(
            self.store.path.suffix + ".run.lock"
        )
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text("-1\n", encoding="ascii")
        with self.store.worker_lease():
            self.assertEqual(int(lock_path.read_text().strip()), os.getpid())
        self.assertFalse(lock_path.exists())


class APITests(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_get_updates_uses_direct_ilink_protocol(self, urlopen):
        urlopen.return_value = FakeResponse(
            json.dumps({"ret": 0, "msgs": [], "get_updates_buf": "cursor"}).encode()
        )
        api = WeixinIlinkAPI(base_url="https://ilink.example", token="token")
        response = api.get_updates("old")
        self.assertEqual(response["get_updates_buf"], "cursor")
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://ilink.example/ilink/bot/getupdates",
        )
        self.assertEqual(request.get_header("Authorization"), "Bearer token")
        self.assertEqual(request.get_header("Ilink-app-id"), "bot")
        payload = json.loads(request.data)
        self.assertEqual(payload["get_updates_buf"], "old")
        self.assertEqual(payload["base_info"]["bot_agent"], "MaidChan/0.1.0")

    @patch("urllib.request.urlopen")
    def test_login_qr_request_does_not_require_token(self, urlopen):
        urlopen.return_value = FakeResponse(
            json.dumps({"qrcode": "id", "qrcode_img_content": "url"}).encode()
        )
        api = WeixinIlinkAPI()
        api.get_login_qr()
        request = urlopen.call_args.args[0]
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(request.get_header("Authorizationtype"), "ilink_bot_token")

    @patch("urllib.request.urlopen", side_effect=TimeoutError)
    def test_empty_long_poll_timeout_is_not_fatal(self, urlopen):
        api = WeixinIlinkAPI(base_url="https://ilink.example", token="token")
        response = api.get_updates("cursor")
        self.assertEqual(
            response, {"ret": 0, "msgs": [], "get_updates_buf": "cursor"}
        )

    @patch("urllib.request.urlopen")
    def test_lifecycle_notifications_use_current_ilink_endpoints(self, urlopen):
        urlopen.side_effect = [
            FakeResponse(json.dumps({"ret": 0}).encode()),
            FakeResponse(json.dumps({"ret": 0}).encode()),
        ]
        api = WeixinIlinkAPI(base_url="https://ilink.example", token="token")
        api.notify_start()
        self.assertEqual(
            urlopen.call_args.args[0].full_url,
            "https://ilink.example/ilink/bot/msg/notifystart",
        )
        api.notify_stop()
        self.assertEqual(
            urlopen.call_args.args[0].full_url,
            "https://ilink.example/ilink/bot/msg/notifystop",
        )


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = WeixinStateStore(Path(self.directory.name) / "state.json")
        self.store.save_login(
            account_id="bot-id",
            token="secret",
            base_url="https://ilink.example",
            owner_user_id="owner-id",
        )
        self.store.add_contact("alice-id", "Alice", 2)
        self.store.set_enabled(True)
        self.engine = FakeEngine()
        self.output = []
        FakeAPI.responses = []
        FakeAPI.sent = []
        FakeAPI.starts = 0
        FakeAPI.stops = 0
        self.runner = WeixinAutoReplyRunner(
            self.store,
            self.engine,
            output=self.output.append,
            api_factory=FakeAPI,
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_first_sync_baselines_then_replies_to_allowed_stable_id(self):
        FakeAPI.responses = [
            {
                "ret": 0,
                "msgs": [inbound("alice-id", "historical")],
                "get_updates_buf": "cursor-1",
            },
            {
                "ret": 0,
                "msgs": [inbound("alice-id", "hello", "context-2")],
                "get_updates_buf": "cursor-2",
            },
        ]
        self.assertEqual(self.runner.poll_once(), 0)
        self.assertEqual(self.runner.poll_once(), 1)
        self.assertEqual(
            FakeAPI.sent,
            [("alice-id", "context-2", "Maid API reply")],
        )
        self.assertEqual(self.engine.calls[0][0], "hello")
        self.assertEqual(
            self.engine.calls[0][1]["memory_privacy_level"],
            2,
        )

    def test_unknown_sender_is_observed_but_not_replied_to(self):
        self.store.save_runtime(
            sync_cursor="cursor-1",
            context_tokens={},
            observed_users={},
        )
        FakeAPI.responses = [
            {
                "ret": 0,
                "msgs": [inbound("unknown-id", "hello")],
                "get_updates_buf": "cursor-2",
            }
        ]
        self.assertEqual(self.runner.poll_once(), 0)
        self.assertIn("unknown-id", self.store.load().observed_users)
        self.assertEqual(FakeAPI.sent, [])

    def test_replies_to_multiple_following_messages(self):
        self.store.save_runtime(
            sync_cursor="cursor-1",
            context_tokens={},
            observed_users={},
        )
        FakeAPI.responses = [
            {
                "ret": 0,
                "msgs": [inbound("alice-id", "one", "context-1")],
                "get_updates_buf": "cursor-2",
                "longpolling_timeout_ms": 48_000,
            },
            {
                "ret": 0,
                "msgs": [inbound("alice-id", "two", "context-2")],
                "get_updates_buf": "cursor-3",
            },
        ]
        self.assertEqual(self.runner.poll_once(), 1)
        self.assertEqual(self.runner.long_poll_timeout_ms, 48_000)
        self.assertEqual(self.runner.poll_once(), 1)
        self.assertEqual([item[0] for item in self.engine.calls], ["one", "two"])
        self.assertEqual(len(FakeAPI.sent), 2)

    def test_run_forever_notifies_start_and_stop(self):
        def stop_after_start():
            raise KeyboardInterrupt

        self.runner.poll_once = stop_after_start
        with self.assertRaises(KeyboardInterrupt):
            self.runner.run_forever()
        self.assertEqual(FakeAPI.starts, 1)
        self.assertEqual(FakeAPI.stops, 1)


if __name__ == "__main__":
    unittest.main()
