from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from maid_chan.moments_transport import (
    MomentsPublishError,
    PyWeixinMomentsPublisher,
)
from maid_chan.wechat_actions import PostMomentAction


class FakeMoments:
    def __init__(self):
        self.kwargs = None

    def post_moments(self, **kwargs):
        self.kwargs = kwargs


class MomentsTransportTests(unittest.TestCase):
    def test_calls_audited_pyweixin_api_and_keeps_wechat_open(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "photo.jpg"
            media.write_bytes(b"jpeg")
            api = FakeMoments()
            PyWeixinMomentsPublisher(api).publish(
                PostMomentAction(text="hello", media=(media,))
            )
        self.assertEqual(api.kwargs["text"], "hello")
        self.assertEqual(api.kwargs["medias"], [str(media.resolve())])
        self.assertFalse(api.kwargs["close_weixin"])

    def test_wraps_ui_failures(self):
        class BrokenMoments:
            @staticmethod
            def post_moments(**_kwargs):
                raise RuntimeError("hidden UI tree")

        with self.assertRaisesRegex(MomentsPublishError, "accessibility tree"):
            PyWeixinMomentsPublisher(BrokenMoments).publish(
                PostMomentAction(text="hello")
            )


if __name__ == "__main__":
    unittest.main()
