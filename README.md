# Maid-chan

Maid-chan is a corpus-grounded chatbot and experimental automatic messaging
agent inspired by Maid-chan from *The Pet Girl of Sakurasou*. The current MVP is
a terminal chatbot for OpenAI-compatible Chat Completions APIs, with optional
operator-controlled personal-WeChat automation for allowed contacts and
contact-isolated Private Spaces imported from WeFlow chat histories.

The core chatbot combines:

- a behavior-focused Maid-chan persona prompt;
- a scenario-free personality guide derived from behavioral traits rather than
  raw novel dialogue;
- bounded in-memory conversation history;
- optional user-reviewed external profile memories in MEMI JSON format.
- contact-scoped identity and episodic history retrieval in Private Space mode.

The core CLI does not write chat logs or API keys to disk. Optional WeChat
transports are experimental, unofficial automation paths and require explicit
risk confirmation before touching an account.

## Quickstart

Requirements:

- Python 3.10 or newer
- A DeepSeek API key, or another OpenAI-compatible provider key

Create a local environment file:

```powershell
Copy-Item .env.example .env
# Edit .env and set DEEPSEEK_API_KEY=your-api-key
```

Optionally configure how Maid-chan addresses you. Without this setting she uses
the neutral `您` and never assumes the identity of a source character:

```dotenv
MAID_CHAN_OPERATOR_NAME=Hehao
MAID_CHAN_OPERATOR_HONORIFIC=大人
```

Run the interactive shell:

```powershell
python -m maid_chan
```

Send one message and exit:

```powershell
python -m maid_chan "你现在在做什么？"
```

Import WeChat histories and simulate a chat as one exact correspondent:

```powershell
python -m maid_chan private import-wechat "F:\WeChat"
python -m maid_chan private set-identity "津" --relationship "classmate"
python -m maid_chan private chat "津" --allow-remote-context
```

Private chat blocks non-local model endpoints unless
`--allow-remote-context` is given. See [Private Spaces](docs/private-spaces.md)
for the isolation model, local-model setup, bilateral relations, and limits.

Install the editable package and console command:

```powershell
python -m pip install -e .
maid-chan
```

## Configuration

DeepSeek defaults:

| Setting | Default |
| --- | --- |
| Base URL | `https://api.deepseek.com` |
| Model | `deepseek-v4-flash` |
| API key | `DEEPSEEK_API_KEY`, then `OPENAI_API_KEY` |

Use another OpenAI-compatible provider:

```dotenv
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://provider.example/v1
OPENAI_MODEL=provider-model-id
```

Command-line flags override environment and `.env` values:

```powershell
python -m maid_chan `
  --base-url "http://localhost:11434/v1" `
  --model "local-model" `
  --api-key "not-required-by-this-server"
```

See [Configuration](docs/configuration.md) for all environment variables, CLI
flags, state paths, and secret-handling rules. See
[Personality and operator identity](docs/personality-and-identity.md) for the
canon-isolation boundary and custom forms of address.

## Interactive Shell

Ordinary input chats with Maid-chan. Slash commands and clear natural-language
instructions can inspect or control WeChat automation:

```text
/help
/memory
/status
/allow add "张三" 2
/compose "张三" 替我问他明天下午有没有空
/act 给张三和李四分别发一条简短问候
```

Natural-language examples:

```text
显示微信状态
把张三加入微信允许名单，记忆隐私级别设为 2
替我起草一条消息给张三，问他明天下午有没有空
把“我十分钟后到”原样发送给张三
只预览发布朋友圈“今天的晚霞真漂亮”
```

External side effects require typed confirmations such as `RUN`, `ACCEPT RISK`,
`SEND`, or `POST`. See [Shell and outbound actions](docs/shell-and-actions.md).

## WeChat Automation

Maid-chan has one shared WeChat command surface with two selectable modes:

- `ui`: foreground WeChat 4.x Windows desktop automation through `wx4py`, with
  public/default Moment publishing through `pywechat127`.
- `wechaty`: a pinned Node.js Wechaty Web-protocol bridge.

Basic setup:

```powershell
python -m maid_chan wechat mode wechaty
python -m maid_chan wechat install
python -m maid_chan wechat doctor
python -m maid_chan wechat auth --accept-account-risk
python -m maid_chan wechat allow add "张三"
python -m maid_chan wechat on
python -m maid_chan wechat run --accept-account-risk
```

Both modes are experimental and unofficial. Use a non-critical account, keep the
allowlist narrow, and review [WeChat transports](docs/wechat-transports.md)
before enabling automation.

The deprecated `maid-chan weixin` iLink transport remains available only for
migration. It uses an independent bot identity and cannot reply as the personal
account.

## External Memory

Maid-chan External Memory Interchange (MEMI) is the provider-neutral JSON format
for reviewed profile facts:

- [Memory and privacy guide](docs/memory-and-privacy.md)
- [MEMI standard](docs/external-memory-standard.md)
- [MEMI JSON Schema](docs/external-memory.schema.json)
- [Visibility policy schema](docs/memory-visibility-policy.schema.json)
- [Platform export guide](docs/platform-memory-export.md)

Validate a memory bundle:

```powershell
python -m maid_chan.memory examples\master-memory.example.json
```

Load memory in chat:

```powershell
python -m maid_chan --memory-file memories\chatgpt.memory.local.json
```

Real memory files should use ignored local filenames such as
`*.memory.local.json`.

## Private Spaces

Private Spaces imports each WeFlow direct chat into its own hashed local
directory. The selected contact's profile and relevant historical excerpts are
retrieved without searching any other contact. Shared context is possible only
through a separate operator-authored bilateral relation record; group chats are
skipped by default.

- [Private Spaces guide](docs/private-spaces.md)
- [Memory and privacy guide](docs/memory-and-privacy.md)

Local private-space data lives under `.maid-chan/private-spaces` and is ignored
by Git. It is plaintext and should be kept on an access-controlled, encrypted
volume when stronger at-rest protection is required.

## Tests

```powershell
python -m unittest discover -v
```

The tests use mocked API responses and do not need network access or
credentials.

## Project Layout

```text
maid_chan/
  cli.py                 terminal entry point
  shell.py               interactive slash and natural-language router
  client.py              OpenAI-compatible HTTP/SSE client
  config.py              settings and dotenv loading
  prompt.py              canon-isolated persona and operator identity prompt
  memory.py              MEMI validation, selection, and prompt context
  visibility.py          viewer/channel privacy policy
  private_space.py       isolated WeFlow import, identity, relations, and recall
  private_cli.py         contact-selection and impersonation chat mode
  engine.py              transport-neutral reply engine
  wechat.py              shared WeChat config and UI polling runner
  wechat_actions.py      outbound action schema and validation
  wechat_drafting.py     compose/revise/send drafting loop
  wechat_cli.py          WeChat command surface
  wx4py_transport.py     WeChat desktop UI adapter
  wechaty.py             Wechaty bridge and event worker
  moments_transport.py   pywechat127 Moment publisher
  weixin.py              deprecated iLink transport
docs/                    operator and contributor guides
corpus/                  generated few-shot and source-context data
examples/                sample memory and visibility files
tests/                   mocked unit tests
tools/corpus/            reproducible corpus extraction tool
```

More detail lives in [docs/index.md](docs/index.md), especially
[Architecture](docs/architecture.md) and [Development](docs/development.md).

The generated corpus is derived from supplied books. Keep access and use aligned
with the rights and licensing that apply to those source files. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for integration notices.
