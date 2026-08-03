"""Viewer and channel privacy ceilings for external memory use."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


FORMAT_NAME = "maid-chan-memory-visibility"
FORMAT_VERSION = "1.0"
_PLATFORM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class VisibilityPolicyError(ValueError):
    """A memory visibility policy is invalid."""


def _object(value: object, location: str) -> Mapping[str, Any]:
    """Validate that a visibility-policy value is a JSON object."""
    if not isinstance(value, dict):
        raise VisibilityPolicyError(f"{location} must be a JSON object")
    return value


def _reject_unknown(
    record: Mapping[str, Any], location: str, allowed: set[str]
) -> None:
    """Fail closed when a policy contains unsupported keys."""
    unknown = set(record) - allowed
    if unknown:
        raise VisibilityPolicyError(
            f"{location} contains unsupported fields: {', '.join(sorted(unknown))}"
        )


def _string(value: object, location: str, *, maximum: int = 256) -> str:
    """Validate a bounded non-empty policy string."""
    if not isinstance(value, str) or not value.strip():
        raise VisibilityPolicyError(f"{location} must be a non-empty string")
    result = value.strip()
    if len(result) > maximum:
        raise VisibilityPolicyError(
            f"{location} exceeds the {maximum}-character limit"
        )
    return result


def _rating(value: object, location: str) -> int:
    """Validate a memory privacy rating from 1 through 5."""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise VisibilityPolicyError(f"{location} must be an integer from 1 to 5")
    return value


@dataclass(frozen=True)
class MemoryVisibilityPolicy:
    """Resolve the maximum memory privacy rating for a messaging audience."""

    default_viewer_max_privacy_rating: int
    viewer_ratings: Mapping[tuple[str, str], int]
    channel_ratings: Mapping[tuple[str, str], int]

    def max_privacy_rating_for(
        self,
        *,
        platform: str,
        user_id: str,
        channel_id: str | None = None,
    ) -> int:
        """Return min(viewer clearance, channel ceiling) for this response."""
        viewer_rating = self.viewer_ratings.get(
            (platform, user_id),
            self.default_viewer_max_privacy_rating,
        )
        if channel_id is None:
            return viewer_rating
        channel_rating = self.channel_ratings.get((platform, channel_id), 5)
        return min(viewer_rating, channel_rating)


def parse_visibility_policy(
    data: object, *, location: str = "<visibility-policy>"
) -> MemoryVisibilityPolicy:
    """Validate a raw JSON visibility policy."""
    root = _object(data, location)
    _reject_unknown(
        root,
        location,
        {
            "format",
            "version",
            "default_viewer_max_privacy_rating",
            "viewers",
            "channels",
        },
    )
    if root.get("format") != FORMAT_NAME:
        raise VisibilityPolicyError(f"{location}.format must be {FORMAT_NAME!r}")
    if root.get("version") != FORMAT_VERSION:
        raise VisibilityPolicyError(f"{location}.version must be {FORMAT_VERSION!r}")
    default_rating = _rating(
        root.get("default_viewer_max_privacy_rating"),
        f"{location}.default_viewer_max_privacy_rating",
    )

    raw_viewers = root.get("viewers", [])
    if not isinstance(raw_viewers, list):
        raise VisibilityPolicyError(f"{location}.viewers must be an array")
    viewer_ratings: dict[tuple[str, str], int] = {}
    for index, raw_viewer in enumerate(raw_viewers):
        item_location = f"{location}.viewers[{index}]"
        viewer = _object(raw_viewer, item_location)
        _reject_unknown(
            viewer,
            item_location,
            {"platform", "user_id", "max_privacy_rating", "label"},
        )
        platform = _string(viewer.get("platform"), f"{item_location}.platform", maximum=128)
        if not _PLATFORM_ID.fullmatch(platform):
            raise VisibilityPolicyError(
                f"{item_location}.platform contains unsupported characters"
            )
        user_id = _string(viewer.get("user_id"), f"{item_location}.user_id")
        key = (platform, user_id)
        if key in viewer_ratings:
            raise VisibilityPolicyError(
                f"{item_location} duplicates viewer {platform}:{user_id}"
            )
        viewer_ratings[key] = _rating(
            viewer.get("max_privacy_rating"),
            f"{item_location}.max_privacy_rating",
        )

    raw_channels = root.get("channels", [])
    if not isinstance(raw_channels, list):
        raise VisibilityPolicyError(f"{location}.channels must be an array")
    channel_ratings: dict[tuple[str, str], int] = {}
    for index, raw_channel in enumerate(raw_channels):
        item_location = f"{location}.channels[{index}]"
        channel = _object(raw_channel, item_location)
        _reject_unknown(
            channel,
            item_location,
            {"platform", "channel_id", "max_privacy_rating", "label"},
        )
        platform = _string(
            channel.get("platform"), f"{item_location}.platform", maximum=128
        )
        if not _PLATFORM_ID.fullmatch(platform):
            raise VisibilityPolicyError(
                f"{item_location}.platform contains unsupported characters"
            )
        channel_id = _string(
            channel.get("channel_id"), f"{item_location}.channel_id"
        )
        key = (platform, channel_id)
        if key in channel_ratings:
            raise VisibilityPolicyError(
                f"{item_location} duplicates channel {platform}:{channel_id}"
            )
        channel_ratings[key] = _rating(
            channel.get("max_privacy_rating"),
            f"{item_location}.max_privacy_rating",
        )

    return MemoryVisibilityPolicy(
        default_viewer_max_privacy_rating=default_rating,
        viewer_ratings=viewer_ratings,
        channel_ratings=channel_ratings,
    )


def load_visibility_policy(path: Path) -> MemoryVisibilityPolicy:
    """Read and validate a visibility policy from disk."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise VisibilityPolicyError(
            f"{path}:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise VisibilityPolicyError(f"could not read {path}: {exc}") from exc
    return parse_visibility_policy(data, location=str(path))
