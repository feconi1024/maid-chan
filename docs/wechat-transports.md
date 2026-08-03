# WeChat Transports

Maid-chan supports two experimental personal-WeChat automation modes behind one
shared allowlist and command interface:

- `ui`: foreground WeChat 4.x Windows desktop automation through `wx4py`, with
  Moment publishing through `pywechat127`.
- `wechaty`: a pinned Node.js Wechaty bridge using
  `wechaty-puppet-wechat4u`.

Both are unofficial automation paths. Test with a non-critical account, keep
the allowlist narrow, and require explicit `--accept-account-risk` for
operations that touch the account.

## Mode Selection

```powershell
python -m maid_chan wechat mode
python -m maid_chan wechat mode ui
python -m maid_chan wechat mode wechaty
```

Stop any existing worker before switching modes. A worker also checks persisted
mode state before replying, so a stale worker fails closed after a mode switch.

## Shared Allowlist

Replies and manual sends are restricted to exact allowlisted contacts:

```powershell
python -m maid_chan wechat allow add "张三" --memory-privacy-level 2
python -m maid_chan wechat allow list
python -m maid_chan wechat on
python -m maid_chan wechat off
```

Each contact stores a memory privacy ceiling from 1 through 5. Automatic
replies pass that ceiling to `MaidChanEngine`, so selected profile memories are
filtered per recipient.

## wx4py UI Mode

UI mode controls the visible logged-in WeChat desktop window. It requires
Windows, a supported WeChat 4.x client, and foreground UI availability.

```powershell
python -m maid_chan wechat mode ui
python -m maid_chan wechat install
python -m maid_chan wechat doctor
python -m maid_chan wechat auth --accept-account-risk
python -m maid_chan wechat run --accept-account-risk
```

UI mode has no independent login profile. Log in and out in the WeChat desktop
client. The WeChat window must remain visible while automation is running.
Keyboard, focus, clipboard, and manual interaction can interfere with UI
automation.

WeChat 4.x UI Automation does not expose reliable sender identity in one-to-one
history. Maid-chan records messages sent by the current worker and suppresses
those, but manual sends from the same desktop window during worker execution can
be misread as incoming messages.

## Wechaty Mode

Wechaty mode starts a Node subprocess bridge and stores its profile under
`.maid-chan/wechaty-profile`.

```powershell
python -m maid_chan wechat mode wechaty
python -m maid_chan wechat install
python -m maid_chan wechat doctor
python -m maid_chan wechat auth --accept-account-risk
python -m maid_chan wechat run --accept-account-risk
```

Logout revokes the separate Web session and clears persisted credentials:

```powershell
python -m maid_chan wechat logout
```

The pinned Wechaty dependency tree is intentionally not auto-upgraded because
forced audit fixes can break the bridge stack. Review runtime advisories before
using this mode with any important account.

## Manual Send

```powershell
python -m maid_chan wechat send "张三" "测试消息" --accept-account-risk
```

With local media:

```powershell
python -m maid_chan wechat send "张三" "看看这张图" `
  --media .\photos\example.jpg `
  --accept-account-risk
```

By default, media paths must be under the current directory. Add
`--media-root PATH` to approve a different directory.

## Moment Publishing

Moment publishing is available only in UI mode with `pywechat127` installed.
The implementation supports text plus local images/videos with public/default
visibility:

```powershell
python -m maid_chan wechat mode ui
python -m maid_chan wechat moment "今天也要加油。" `
  --media .\photo.jpg `
  --accept-account-risk
```

Unsupported Moment controls fail before execution:

- custom visibility;
- include/exclude audiences;
- location;
- reminders.

Always verify non-critical posts with the visible account before relying on UI
automation for public publishing.

## Capabilities

```powershell
python -m maid_chan wechat capabilities
```

Current capability summary:

| Operation | UI mode | Wechaty mode |
| --- | --- | --- |
| Private text send | supported | supported |
| Private media/file send | supported | supported |
| Passive private auto-reply | experimental | supported through events |
| Moment text/image/video | public/default only | unsupported |
| Custom Moment visibility/location/reminders | unsupported | unsupported |

