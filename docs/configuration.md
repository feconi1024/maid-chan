# Configuration

Maid-chan reads configuration from command-line flags, process environment, and
an optional dotenv file. The precedence is:

1. Explicit command-line flag
2. Existing process environment
3. `.env` or `MAID_CHAN_ENV_FILE`
4. Built-in defaults

## Minimal `.env`

```dotenv
DEEPSEEK_API_KEY=your-api-key
```

For another OpenAI-compatible provider:

```dotenv
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://provider.example/v1
OPENAI_MODEL=provider-model-id
```

`.env` is ignored by Git. Do not commit real API keys, WeChat profile files, or
local memory bundles.

## Chat Settings

| Setting | Environment | CLI flag | Default |
| --- | --- | --- | --- |
| API key | `DEEPSEEK_API_KEY`, then `OPENAI_API_KEY` | `--api-key` | none |
| Base URL | `OPENAI_BASE_URL` | `--base-url` | `https://api.deepseek.com` |
| Model | `OPENAI_MODEL` | `--model` | `deepseek-v4-flash` |
| Timeout | none | `--timeout` | `60` seconds |
| Temperature | none | `--temperature` | `0.9` |
| Max tokens | none | `--max-tokens` | `500` |
| Streaming | none | `--no-stream` disables | enabled |
| DeepSeek thinking | none | `--thinking` enables | disabled |

If `base_url` already ends in `/chat/completions`, Maid-chan uses it as-is.
If it points at the official DeepSeek host or ends in `/v1`, Maid-chan appends
`/chat/completions`; otherwise it appends `/v1/chat/completions`.

## Prompt and History

| Setting | CLI flag | Default |
| --- | --- | --- |
| Few-shot file | `--few-shot-file` | `corpus/maid_chan_fewshot.jsonl` |
| Few-shot count | `--few-shots` | `8` |
| History turns | `--history-turns` | `12` |

History is process-local and never written to disk by the core CLI.

## External Memory

| Setting | Environment | CLI flag | Default |
| --- | --- | --- | --- |
| Memory files | `MAID_CHAN_MEMORY_FILES` | `--memory-file` | none |
| Memory budget | none | `--memory-max-chars` | `6000` |
| Privacy ceiling | `MAID_CHAN_MEMORY_PRIVACY_LEVEL` | `--memory-privacy-level` | `3` |
| Restricted alias | none | `--include-restricted-memory` | off |

`MAID_CHAN_MEMORY_FILES` uses the platform path separator. On Windows that is
`;`, so multiple files look like:

```powershell
$env:MAID_CHAN_MEMORY_FILES = "C:\profiles\chatgpt.json;C:\profiles\claude.json"
```

See [Memory and privacy](memory-and-privacy.md) for validation and visibility
details.

## WeChat State Paths

| Purpose | Environment | CLI flag | Default |
| --- | --- | --- | --- |
| Shared WeChat control file | `MAID_CHAN_WECHAT_CONFIG` | `maid-chan wechat --config` | `.maid-chan/wechat.local.json` |
| Wechaty runtime directory | `MAID_CHAN_WECHATY_RUNTIME` | `maid-chan wechat --runtime` | `.maid-chan/wechaty-runtime` |
| Wechaty profile directory | `MAID_CHAN_WECHATY_PROFILE` | `maid-chan wechat --profile` | `.maid-chan/wechaty-profile` |
| Deprecated iLink state | `MAID_CHAN_WEIXIN_STATE` | `maid-chan weixin --state` | `.maid-chan/weixin-ilink.local.json` |

The `.maid-chan/` directory is ignored by Git because it may contain runtime
dependencies, login profiles, local control state, and account credentials.

## Private Space Settings

Private Space commands use `--spaces-dir` to override the default
`.maid-chan/private-spaces` store. Chat mode accepts the normal provider,
few-shot, history, temperature, token, timeout, streaming, and thinking flags.
It additionally supports:

| Flag | Default | Purpose |
| --- | --- | --- |
| `--private-context-chars` | `12000` | Bound selected profile and historical transcript text per request. |
| `--allow-remote-context` | off | Permit selected private text to leave the machine for a non-loopback model URL. |

Private chat deliberately ignores `MAID_CHAN_MEMORY_FILES` so a shared MEMI
pool cannot bleed into a correspondent space. Provider credentials are still
read from the normal environment or `.env` settings.
