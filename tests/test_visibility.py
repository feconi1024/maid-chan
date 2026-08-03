import unittest

from maid_chan.visibility import VisibilityPolicyError, parse_visibility_policy


def policy():
    return {
        "format": "maid-chan-memory-visibility",
        "version": "1.0",
        "default_viewer_max_privacy_rating": 1,
        "viewers": [
            {
                "platform": "wechat",
                "user_id": "owner-id",
                "max_privacy_rating": 5,
            },
            {
                "platform": "wechat",
                "user_id": "friend-id",
                "max_privacy_rating": 3,
            },
        ],
        "channels": [
            {
                "platform": "wechat",
                "channel_id": "group-id",
                "max_privacy_rating": 1,
            }
        ],
    }


class VisibilityPolicyTests(unittest.TestCase):
    def test_unknown_viewer_uses_fail_closed_default(self):
        parsed = parse_visibility_policy(policy())
        self.assertEqual(
            parsed.max_privacy_rating_for(
                platform="wechat",
                user_id="unknown-id",
            ),
            1,
        )

    def test_resolves_known_viewer_clearance(self):
        parsed = parse_visibility_policy(policy())
        self.assertEqual(
            parsed.max_privacy_rating_for(
                platform="wechat",
                user_id="friend-id",
            ),
            3,
        )

    def test_group_channel_ceiling_limits_owner(self):
        parsed = parse_visibility_policy(policy())
        self.assertEqual(
            parsed.max_privacy_rating_for(
                platform="wechat",
                user_id="owner-id",
                channel_id="group-id",
            ),
            1,
        )

    def test_rejects_duplicate_viewer_rules(self):
        data = policy()
        data["viewers"].append(dict(data["viewers"][0]))
        with self.assertRaisesRegex(VisibilityPolicyError, "duplicates viewer"):
            parse_visibility_policy(data)


if __name__ == "__main__":
    unittest.main()
