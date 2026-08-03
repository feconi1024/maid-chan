# Upstream basis

This bridge follows the WeChat event transport used by
[`wangrongding/wechat-bot`](https://github.com/wangrongding/wechat-bot):

- `WechatyBuilder`
- `wechaty-puppet-wechat4u`
- the `uos: true` puppet option
- QR-code login and event-driven text replies

The upstream repository is ISC licensed. Maid-chan keeps its own prompt,
allowlist, memory, and model pipeline instead of invoking the upstream model
providers.
