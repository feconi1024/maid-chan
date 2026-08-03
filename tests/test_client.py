import io
import json
import unittest
from unittest.mock import patch

from maid_chan.client import APIError, ChatClient
from maid_chan.config import Settings


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = ChatClient(
            Settings(api_key="secret", base_url="https://example.test")
        )
        self.messages = [{"role": "user", "content": "你好"}]

    @patch("urllib.request.urlopen")
    def test_complete_reads_openai_compatible_response(self, urlopen):
        body = {"choices": [{"message": {"content": "您好，空太大人。"}}]}
        urlopen.return_value = FakeResponse(json.dumps(body).encode())
        self.assertEqual(
            self.client.complete(self.messages),
            "您好，空太大人。",
        )
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertFalse(payload["stream"])
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")

    @patch("urllib.request.urlopen")
    def test_disables_thinking_for_official_deepseek_by_default(self, urlopen):
        client = ChatClient(Settings(api_key="secret"))
        body = {"choices": [{"message": {"content": "收到。"}}]}
        urlopen.return_value = FakeResponse(json.dumps(body).encode())
        client.complete(self.messages)
        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(payload["thinking"], {"type": "disabled"})

    @patch("urllib.request.urlopen")
    def test_stream_ignores_reasoning_and_yields_content(self, urlopen):
        events = [
            {"choices": [{"delta": {"reasoning_content": "thinking"}}]},
            {"choices": [{"delta": {"content": "您好"}}]},
            {"choices": [{"delta": {"content": "。"}}]},
        ]
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        body += "data: [DONE]\n\n"
        urlopen.return_value = FakeResponse(body.encode())
        self.assertEqual("".join(self.client.stream(self.messages)), "您好。")

    @patch("urllib.request.urlopen")
    def test_rejects_invalid_response(self, urlopen):
        urlopen.return_value = FakeResponse(b'{"unexpected": true}')
        with self.assertRaises(APIError):
            self.client.complete(self.messages)


if __name__ == "__main__":
    unittest.main()
