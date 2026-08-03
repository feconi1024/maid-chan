import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maid_chan.config import Settings, load_dotenv


class SettingsTests(unittest.TestCase):
    def write_env(self, content):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / ".env"
        path.write_text(content, encoding="utf-8")
        self.addCleanup(directory.cleanup)
        return path

    def test_builds_chat_completions_url_from_provider_base(self):
        settings = Settings(api_key="test", base_url="https://example.test")
        self.assertEqual(
            settings.chat_completions_url,
            "https://example.test/v1/chat/completions",
        )

    def test_uses_official_deepseek_endpoint_without_v1(self):
        settings = Settings(api_key="test")
        self.assertEqual(
            settings.chat_completions_url,
            "https://api.deepseek.com/chat/completions",
        )
        self.assertTrue(settings.is_official_deepseek)

    def test_preserves_v1_and_full_endpoint(self):
        v1 = Settings(api_key="test", base_url="https://example.test/openai/v1/")
        full = Settings(
            api_key="test",
            base_url="https://example.test/custom/chat/completions",
        )
        self.assertEqual(
            v1.chat_completions_url,
            "https://example.test/openai/v1/chat/completions",
        )
        self.assertEqual(
            full.chat_completions_url,
            "https://example.test/custom/chat/completions",
        )

    @patch.dict(
        "os.environ",
        {"MAID_CHAN_MEMORY_FILES": f"one.json{os.pathsep}two.json"},
        clear=True,
    )
    def test_reads_memory_paths_from_environment(self):
        settings = Settings.from_environment()
        self.assertEqual(
            settings.memory_paths,
            (Path("one.json"), Path("two.json")),
        )

    @patch.dict(
        "os.environ",
        {"MAID_CHAN_MEMORY_PRIVACY_LEVEL": "4"},
        clear=True,
    )
    def test_reads_memory_privacy_level_from_environment(self):
        settings = Settings.from_environment()
        self.assertEqual(settings.memory_privacy_level, 4)

    @patch.dict("os.environ", {}, clear=True)
    def test_reads_api_configuration_from_dotenv(self):
        path = self.write_env(
            "DEEPSEEK_API_KEY='dotenv-secret'\n"
            'OPENAI_BASE_URL="https://example.test/v1"\n'
            "OPENAI_MODEL=example-model # optional comment\n"
        )
        settings = Settings.from_environment(env_file=path)
        self.assertEqual(settings.api_key, "dotenv-secret")
        self.assertEqual(settings.base_url, "https://example.test/v1")
        self.assertEqual(settings.model, "example-model")

    @patch.dict(
        "os.environ",
        {
            "DEEPSEEK_API_KEY": "process-secret",
            "OPENAI_MODEL": "process-model",
        },
        clear=True,
    )
    def test_process_environment_overrides_dotenv(self):
        path = self.write_env(
            "DEEPSEEK_API_KEY=dotenv-secret\nOPENAI_MODEL=dotenv-model\n"
        )
        settings = Settings.from_environment(env_file=path)
        self.assertEqual(settings.api_key, "process-secret")
        self.assertEqual(settings.model, "process-model")

    @patch.dict("os.environ", {}, clear=True)
    def test_explicit_argument_overrides_dotenv(self):
        path = self.write_env("DEEPSEEK_API_KEY=dotenv-secret\n")
        settings = Settings.from_environment(
            env_file=path,
            api_key="argument-secret",
        )
        self.assertEqual(settings.api_key, "argument-secret")

    def test_dotenv_supports_export_and_rejects_invalid_lines(self):
        path = self.write_env("export DEEPSEEK_API_KEY=secret\n")
        self.assertEqual(load_dotenv(path)["DEEPSEEK_API_KEY"], "secret")
        invalid = self.write_env("this is not valid\n")
        with self.assertRaisesRegex(ValueError, "KEY=VALUE"):
            load_dotenv(invalid)


if __name__ == "__main__":
    unittest.main()
