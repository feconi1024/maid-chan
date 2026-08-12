# Architecture

Maid-chan is a Python package for building a character-grounded chatbot and
routing it through operator-controlled messaging workflows. The core chat path
has no third-party runtime dependencies; optional WeChat integrations install
their own pinned dependencies only when selected.

## Runtime Flow

1. `maid_chan.cli.main` parses CLI arguments, loads `.env`, resolves
   `Settings`, loads few-shot examples, and validates external memories.
2. `MaidChanShell` handles slash commands and model-classified natural
   commands. Ordinary messages are left as chat.
3. `build_messages` assembles the system prompt, selected memory context,
   relevant few-shot examples, recent history, and the current user turn.
4. `ChatClient` sends the request to an OpenAI-compatible
   `/chat/completions` endpoint and returns a full response or streaming
   chunks.
5. `MaidChanEngine` stores bounded per-conversation history and gives the same
   reply interface to the terminal, wx4py runner, Wechaty runner, and iLink
   migration runner.

Private Space mode takes a separate contact-scoped path: `private_cli` resolves
one exact profile, `private_space` retrieves only that space's transcript and
explicit shared relations, and `build_messages` adds the resulting untrusted
JSON as a dedicated system message. Shared MEMI files are excluded from this
path.

## Main Modules

| Module | Responsibility |
| --- | --- |
| `maid_chan.cli` | Top-level terminal entry point and interactive chat loop. |
| `maid_chan.shell` | Slash commands, natural-language operation routing, risk prompts, and delegation to the WeChat CLI. |
| `maid_chan.config` | dotenv parsing, environment-variable precedence, and immutable settings. |
| `maid_chan.client` | Standard-library HTTP/SSE client for OpenAI-compatible chat completions. |
| `maid_chan.prompt` | Maid-chan persona prompt, few-shot loading, and lightweight example retrieval. |
| `maid_chan.memory` | MEMI validation, memory loading, privacy filtering, ranking, and prompt serialization. |
| `maid_chan.visibility` | Viewer and channel memory-privacy ceilings for messaging adapters. |
| `maid_chan.private_space` | Hashed contact stores, WeFlow normalization, identity notes, explicit relations, and episodic retrieval. |
| `maid_chan.private_cli` | Operator import, identity, relation, and contact-impersonation chat commands. |
| `maid_chan.engine` | Transport-neutral reply generation with bounded conversation history. |
| `maid_chan.wechat` | Shared WeChat config, allowlist, UI transport protocol, and polling runner. |
| `maid_chan.wechat_cli` | Standalone WeChat command surface used by both CLI and shell. |
| `maid_chan.wechat_actions` | Model-planned outbound action schema, local validation, and capability checks. |
| `maid_chan.wechat_drafting` | Stateful compose/revise/preview/send drafting loop. |
| `maid_chan.wx4py_transport` | Foreground WeChat desktop UI adapter. |
| `maid_chan.wechaty` | Node Wechaty bridge management and event-driven worker. |
| `maid_chan.moments_transport` | pywechat127 Moment publishing adapter for UI mode. |
| `maid_chan.weixin` | Deprecated Tencent iLink bot-identity transport retained for migration. |

## Data Boundaries

Few-shot corpus data is read from `corpus/maid_chan_fewshot.jsonl`. It is used
only as style and behavior reference material. Chat history remains in memory
for the active process and is trimmed to `history_turns`.

External memories are read from operator-supplied JSON files. They are not
modified by Maid-chan. The memory prompt explicitly marks selected records as
quoted data, filters them by privacy rating, and tells the model not to treat
memory contents as instructions.

Private Space text is copied into `.maid-chan/private-spaces` as one profile and
JSONL transcript per hashed platform ID. Runtime retrieval never scans across
spaces. Cross-contact context lives in a separate pair-scoped relation file and
contains only operator-authored shared text. Remote model endpoints are blocked
for this mode until the operator supplies `--allow-remote-context`.

WeChat control state is local and ignored by Git:

- `.maid-chan/wechat.local.json`
- `.maid-chan/wechaty-runtime`
- `.maid-chan/wechaty-profile`
- `.maid-chan/weixin-ilink.local.json`
- `.maid-chan/private-spaces`

## Extension Points

Add a new chat provider by configuring an OpenAI-compatible base URL and model.
No code changes are required when the provider follows the Chat Completions
schema.

Add a new messaging backend by implementing the `WeChatTransport` protocol for
polling-style transports, or by following the event-driven shape of
`WechatyAutoReplyRunner`. New backends must preserve allowlist checks,
privacy-level propagation, and explicit operator confirmation for outbound
actions.

Add new outbound action types in this order:

1. Extend the dataclasses and schema in `wechat_actions.py`.
2. Update local validation before any execution code.
3. Update `assert_executable` so unsupported transports fail before executing
   partial plans.
4. Add CLI preview and confirmation behavior.
5. Document the new capability in [WeChat transports](wechat-transports.md) and
   [Shell and outbound actions](shell-and-actions.md).
