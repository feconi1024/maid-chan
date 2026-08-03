import unittest

from maid_chan.config import Settings
from maid_chan.engine import MaidChanEngine
from maid_chan.prompt import Example


class FakeClient:
    def __init__(self):
        self.requests = []

    def complete(self, messages):
        self.requests.append(messages)
        return f"reply-{len(self.requests)}"


class EngineTests(unittest.TestCase):
    def test_keeps_histories_separate_by_conversation(self):
        client = FakeClient()
        engine = MaidChanEngine(
            client,
            Settings(api_key="test", few_shot_count=0),
            [Example("example", "answer")],
        )
        engine.reply("Alice one", conversation_id="alice")
        engine.reply("Bob one", conversation_id="bob")
        engine.reply("Alice two", conversation_id="alice")
        alice_request = client.requests[-1]
        self.assertTrue(
            any(message["content"] == "Alice one" for message in alice_request)
        )
        self.assertFalse(
            any(message["content"] == "Bob one" for message in alice_request)
        )


if __name__ == "__main__":
    unittest.main()

