"""Configuration loading for Maid-chan CLI and transport workers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_FEW_SHOT_PATH = (
    Path(__file__).resolve().parent.parent / "corpus" / "maid_chan_fewshot.jsonl"
)
DEFAULT_MEMORY_MAX_CHARS = 6000
DEFAULT_MEMORY_PRIVACY_LEVEL = 3
DEFAULT_ENV_PATH = Path(".env")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_dotenv(path: Path | str | None = None) -> dict[str, str]:
    """Read a small, dependency-free subset of dotenv syntax."""
    selected = Path(
        path
        if path is not None
        else os.environ.get("MAID_CHAN_ENV_FILE", DEFAULT_ENV_PATH)
    ).expanduser()
    try:
        content = selected.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ValueError(f"could not read environment file {selected}: {exc}") from exc

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(content.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, raw_value = line.partition("=")
        name = name.strip()
        if not separator or not _ENV_NAME.fullmatch(name):
            raise ValueError(
                f"{selected}:{line_number} is not a valid KEY=VALUE entry"
            )
        value = raw_value.strip()
        if value.startswith(("'", '"')):
            quote = value[0]
            if len(value) < 2 or not value.endswith(quote):
                raise ValueError(
                    f"{selected}:{line_number} has an unterminated quoted value"
                )
            value = value[1:-1]
            if quote == '"':
                replacements = {
                    r"\\": "\\",
                    r"\"": '"',
                    r"\n": "\n",
                    r"\r": "\r",
                    r"\t": "\t",
                }
                for encoded, decoded in replacements.items():
                    value = value.replace(encoded, decoded)
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[name] = value
    return values


@dataclass(frozen=True)
class Settings:
    """Resolved runtime settings for model calls, memory, and prompt assembly."""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = 60.0
    temperature: float = 0.9
    max_tokens: int = 500
    few_shot_path: Path = DEFAULT_FEW_SHOT_PATH
    few_shot_count: int = 8
    history_turns: int = 12
    memory_paths: tuple[Path, ...] = ()
    memory_max_chars: int = DEFAULT_MEMORY_MAX_CHARS
    memory_privacy_level: int = DEFAULT_MEMORY_PRIVACY_LEVEL
    memory_include_restricted: bool = False
    stream: bool = True
    thinking: bool = False

    @classmethod
    def from_environment(
        cls,
        *,
        env_file: Path | str | None = None,
        **overrides: object,
    ) -> "Settings":
        """Build settings from dotenv, process environment, and overrides."""
        dotenv = load_dotenv(env_file)

        def environment(name: str, default: str = "") -> str:
            """Return the first configured value for a single variable name."""
            return os.environ.get(name) or dotenv.get(name) or default

        values: dict[str, object] = {
            "api_key": environment("DEEPSEEK_API_KEY")
            or environment("OPENAI_API_KEY"),
            "base_url": environment("OPENAI_BASE_URL", DEFAULT_BASE_URL),
            "model": environment("OPENAI_MODEL", DEFAULT_MODEL),
        }
        memory_files = environment("MAID_CHAN_MEMORY_FILES")
        if memory_files:
            values["memory_paths"] = tuple(
                Path(item) for item in memory_files.split(os.pathsep) if item
            )
        memory_privacy_level = environment("MAID_CHAN_MEMORY_PRIVACY_LEVEL")
        if memory_privacy_level:
            try:
                values["memory_privacy_level"] = int(memory_privacy_level)
            except ValueError as exc:
                raise ValueError(
                    "MAID_CHAN_MEMORY_PRIVACY_LEVEL must be an integer from 1 to 5"
                ) from exc
        values.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**values)

    @property
    def chat_completions_url(self) -> str:
        """Return the concrete ``/chat/completions`` URL for the provider."""
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        if self.is_official_deepseek:
            return f"{base}/chat/completions"
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    @property
    def is_official_deepseek(self) -> bool:
        """Whether DeepSeek-specific request options should be emitted."""
        return urlparse(self.base_url).hostname == "api.deepseek.com"
