from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maid_chan.cli import main as cli_main
from maid_chan.private_cli import main as private_main
from maid_chan.private_space import PrivateSpaceStore
from tests.test_private_space import message, write_export


class PrivateCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        export_root = self.root / "export"
        export_root.mkdir()
        write_export(
            export_root,
            "Alice",
            "wxid_alice",
            [message(1, "alice-only memory", sent=False)],
        )
        write_export(
            export_root,
            "Bob",
            "wxid_bob",
            [message(1, "bob-only secret", sent=False, sender="Bob")],
        )
        self.store_path = self.root / "spaces"
        PrivateSpaceStore(self.store_path).import_weflow(export_root)

    def test_top_level_cli_routes_private_list(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = cli_main(
                ["private", "--spaces-dir", str(self.store_path), "list"]
            )
        self.assertEqual(result, 0)
        self.assertIn("Alice", output.getvalue())
        self.assertIn("Bob", output.getvalue())

    def test_set_identity_command_updates_only_selected_profile(self):
        result = private_main(
            [
                "--spaces-dir",
                str(self.store_path),
                "set-identity",
                "Alice",
                "--relationship",
                "classmate",
            ]
        )
        self.assertEqual(result, 0)
        store = PrivateSpaceStore(self.store_path)
        self.assertEqual(store.resolve("Alice").relationship, "classmate")
        self.assertEqual(store.resolve("Bob").relationship, "")

    def test_remote_provider_context_requires_explicit_opt_in(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            result = private_main(
                [
                    "--spaces-dir",
                    str(self.store_path),
                    "chat",
                    "Alice",
                    "hello",
                    "--api-key",
                    "test-key",
                    "--base-url",
                    "https://provider.example/v1",
                    "--no-stream",
                ]
            )
        self.assertEqual(result, 2)
        self.assertIn("blocked from remote model providers", errors.getvalue())

    @patch("maid_chan.private_cli.ChatClient")
    def test_remote_opt_in_sends_only_selected_space_context(self, client_class):
        client_class.return_value.complete.return_value = "private reply"
        global_memory = self.root / "global.memory.local.json"
        global_memory.write_text("GLOBAL MEMORY MUST NOT LOAD", encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.dict(
            "os.environ", {"MAID_CHAN_MEMORY_FILES": str(global_memory)}
        ):
            result = private_main(
                [
                    "--spaces-dir",
                    str(self.store_path),
                    "chat",
                    "Alice",
                    "remember",
                    "--api-key",
                    "test-key",
                    "--base-url",
                    "https://provider.example/v1",
                    "--allow-remote-context",
                    "--no-stream",
                ]
            )
        self.assertEqual(result, 0)
        messages = client_class.return_value.complete.call_args.args[0]
        serialized = "\n".join(item["content"] for item in messages)
        self.assertIn("alice-only memory", serialized)
        self.assertNotIn("bob-only secret", serialized)
        self.assertNotIn("GLOBAL MEMORY MUST NOT LOAD", serialized)
        self.assertIn("private reply", output.getvalue())


if __name__ == "__main__":
    unittest.main()
