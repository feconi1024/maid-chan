# Third-party notices

## wangrongding/wechat-bot and Wechaty

Maid-chan's experimental personal-WeChat bridge follows the Wechaty transport
configuration published in
[`wangrongding/wechat-bot`](https://github.com/wangrongding/wechat-bot),
including `WechatyBuilder`, `wechaty-puppet-wechat4u`, QR login, and the UOS
puppet option. The referenced repository is distributed under the ISC License.

The installed Node runtime also contains Wechaty, wechaty-puppet-wechat4u, and
their transitive dependencies under their respective licenses. Maid-chan is not
affiliated with or endorsed by those projects or by Tencent.

## Tencent openclaw-weixin

Maid-chan's deprecated Weixin transport interoperates with the iLink bot HTTP
protocol publicly documented by Tencent in
[`Tencent/openclaw-weixin`](https://github.com/Tencent/openclaw-weixin).

Copyright (C) 2026 Tencent. The referenced implementation is distributed under
the MIT License. Maid-chan's Python transport is an independent implementation
of the published protocol and is not affiliated with or endorsed by Tencent.

## qrcode

The optional `qrcode` Python package is used only to render the authorization QR
code in a terminal. It is distributed under the BSD license.

## claw-codes/wx4py

Maid-chan's optional Windows UI-automation transport interoperates with
[`claw-codes/wx4py`](https://github.com/claw-codes/wx4py). Upstream identifies
the package as AGPL-3.0-or-later and also documents additional commercial-use
restrictions. Consult its current license and usage terms before distribution
or commercial use. Maid-chan is not affiliated with or endorsed by wx4py or
Tencent.

## Hello-Mr-Crab/pywechat

Maid-chan's optional Moments publisher calls the `pyweixin.Moments` API from
[`Hello-Mr-Crab/pywechat`](https://github.com/Hello-Mr-Crab/pywechat), packaged
as `pywechat127`. Upstream identifies the project as LGPL-3.0 and supports
Windows UI automation for WeChat 4.1.6+. Maid-chan is not affiliated with or
endorsed by pywechat or Tencent.
