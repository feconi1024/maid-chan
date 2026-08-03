"""pywechat127 integration for public/default WeChat Moment publishing."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Callable
from typing import Any

from .wechat import WeChatError
from .wechat_actions import PostMomentAction


PYWECHAT_VERSION = "1.9.8"


class MomentsPublishError(WeChatError):
    """A WeChat Moments UI operation could not be completed safely."""


class PyWeixinMomentsPublisher:
    """Adapter for pywechat127's WeChat 4.1+ ``pyweixin.Moments`` API."""

    def __init__(self, moments_api: Any | None = None):
        """Create a publisher with an optional fake Moments API for tests."""
        self._moments_api = moments_api

    @staticmethod
    def dependency_available() -> bool:
        """Return whether ``pyweixin`` from pywechat127 is importable."""
        return importlib.util.find_spec("pyweixin") is not None

    def publish(self, action: PostMomentAction) -> None:
        """Publish a validated public/default-visibility Moment action."""
        if self._moments_api is None:
            try:
                from pyweixin import Moments
            except ImportError as exc:
                raise MomentsPublishError(
                    "pywechat127 is not installed; select UI mode and run "
                    "`maid-chan wechat install`"
                ) from exc
            moments_api = Moments
        else:
            moments_api = self._moments_api

        try:
            moments_api.post_moments(
                text=action.text,
                medias=[str(path.resolve()) for path in action.media],
                close_weixin=False,
            )
        except Exception as exc:
            raise MomentsPublishError(
                "Moments publishing failed; verify that WeChat 4.1.6+ is logged "
                "in, visible, and exposes its accessibility tree"
            ) from exc


def install_pywechat(*, output: Callable[[str], None] = print) -> None:
    """Install the pinned pywechat127 package for UI Moment support."""
    output(
        f"Installing pywechat127 {PYWECHAT_VERSION} for WeChat Moments automation..."
    )
    user_args = [] if sys.prefix != sys.base_prefix else ["--user"]
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                *user_args,
                f"pywechat127=={PYWECHAT_VERSION}",
            ],
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise MomentsPublishError(f"could not install pywechat127: {exc}") from exc
