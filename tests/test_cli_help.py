from __future__ import annotations

import contextlib
import io
import unittest

from maid_chan.cli import main as cli_main
from maid_chan.wechat_cli import main as wechat_main


class CliHelpTests(unittest.TestCase):
    def test_top_level_slash_help_aliases_argparse_help(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = cli_main(["/help"])
        self.assertEqual(result, 0)
        help_text = output.getvalue()
        self.assertIn("usage: maid-chan", help_text)
        self.assertIn("/compose", help_text)
        self.assertIn("/wechat send", help_text)
        self.assertIn("maid-chan private chat", help_text)

    def test_wechat_slash_help_aliases_argparse_help(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            wechat_main(["/help"])
        self.assertEqual(raised.exception.code, 0)
        help_text = output.getvalue()
        self.assertIn("usage: maid-chan wechat", help_text)
        self.assertIn("compose", help_text)
        self.assertIn("allow", help_text)


if __name__ == "__main__":
    unittest.main()
