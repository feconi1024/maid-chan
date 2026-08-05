# Shell and Outbound Actions

The default `maid-chan` command opens a unified interactive shell. Ordinary
input is chat. Slash commands and clearly expressed natural-language
instructions can inspect or control WeChat automation without leaving the
session.

## Startup

```powershell
python -m maid_chan
```

Send one message and exit:

```powershell
python -m maid_chan "你现在在做什么？"
```

Show the unified command reference:

```powershell
python -m maid_chan /help
```

## Slash Commands

| Command | Purpose |
| --- | --- |
| `/help` | Show the unified shell reference. |
| `/memory` | Summarize loaded memories without printing contents. |
| `/reset` | Clear current chat history. |
| `/quit`, `/exit` | Leave the shell. |
| `/status` | Show WeChat backend, dependency, profile, toggle, and allowlist state. |
| `/mode ui\|wechaty` | Select wx4py UI mode or Wechaty mode. |
| `/capabilities` | Show backend-supported outbound operations. |
| `/install` | Install the selected backend runtime. |
| `/doctor` | Probe selected backend startup. |
| `/auth` | Verify UI login or authorize Wechaty. |
| `/logout` | Revoke Wechaty session; UI mode logs out in the desktop client. |
| `/allow list` | List allowed contacts. |
| `/allow add <name> [1-5]` | Add or update an exact contact and memory privacy ceiling. |
| `/allow remove <name>` | Remove a contact. |
| `/auto on`, `/auto off` | Enable or disable automatic replies. |
| `/run` | Start the selected foreground reply worker. |
| `/compose <name> [instruction]` | Draft, revise, preview, and optionally send one message. |
| `/act <instruction>` | Plan one or more outbound actions from natural language. |
| `/moment <text>` | Publish a public/default Moment in UI mode. |
| `/wechat <args>` | Call the standalone WeChat CLI directly. |

`/send` is an alias for `/compose`. Use `/wechat send` when you need direct
verbatim sending through the standalone CLI path.

## Natural-Language Commands

Non-slash input first goes through a bounded command router. If the router is
uncertain or returns invalid JSON, the message falls back to ordinary chat.

Examples:

```text
显示微信状态
把张三加入微信允许名单，记忆隐私级别设为 2
替我起草一条消息给张三，问他明天下午有没有空
把“我十分钟后到”原样发送给张三
只预览发布朋友圈“今天的晚霞真漂亮”
```

The router cannot execute shell commands, provide secrets, invent contacts, or
invent attachment paths. Contact names and local paths selected by the model
must appear explicitly in the operator's original text.

Use `/do <instruction>` to force the router and show its error instead of
falling back to chat.

## Confirmations

Maid-chan uses explicit typed confirmations for external side effects:

| Confirmation | Used for |
| --- | --- |
| `RUN` | Inferred configuration changes, mode switches, installs, worker startup. |
| `ACCEPT RISK` | Unofficial account automation and direct send permission. |
| `SEND` | Final private-message sends and action-plan execution. |
| `POST` | Moment publishing. |

Dry runs and preview-only flows do not execute external operations.

## Drafting

`compose` starts a recipient-scoped drafting session:

```powershell
python -m maid_chan wechat compose "张三" "替我问他明天下午有没有空"
```

Inside the drafting session:

| Command | Purpose |
| --- | --- |
| `/show` | Display the current draft and attachments. |
| `/exact <text>` | Replace the draft exactly without a model call. |
| `/clear` | Clear the draft and revision history. |
| `/send` | Preview and request final `SEND` confirmation. |
| `/cancel` | Exit without sending. |

Model-composed drafts are wrapped in a visible Maid-chan messenger envelope.
Exact/verbatim drafts are not rewritten.

## Action Planning

`act` converts an operator instruction into a local `WeChatActionPlan`, then
validates it before any execution:

```powershell
python -m maid_chan wechat act `
  "给张三发送：明天下午三点见，并附上 .\brief.pdf" `
  --dry-run
```

Validation rules include:

- maximum five actions per plan;
- recipients must be exact allowlisted contacts;
- model-selected contacts and media paths must appear in the prompt;
- media files must live under approved media roots;
- files must exist, use supported extensions, and be no larger than 25 MiB;
- unsupported backend capabilities fail the whole plan before any action runs.
