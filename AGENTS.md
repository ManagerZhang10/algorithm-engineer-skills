# pelican-proxy-check

> 本 Repo 的共享主规则。顶层 `/Users/yuzhang/ZhangYu/AGENTS.md` 的约定继续适用。

## 这是个公开仓库

发出去给陌生人看的。任何改动落地前先过这三条：

1. **密钥零容忍。** 真实 key、base_url 里的私有网关地址、被测中转服务商的名字，
   一个都不进这个仓库——包括 README、示例、截图、commit message、issue 模板。
   `lanes.env.example` 里只放 `<你的 key>` 占位符或 `${VAR}` 引用。
2. **截图必须脱敏。** `assets/board.png` 及任何新增截图，都要用
   `python3 pelican_proxy_check.py render --anonymize` 出图后再截，通道名显示为
   「中转 A / 中转 B」。官方直连的名字可以留。
3. **提交身份用个人 noreply**（见顶层第九节），公司邮箱绝不进这里的历史。

## 事实纪律

README 和 `docs/raw-data.md` 里的每个数字都是实测出来的，标着日期和模型。
**不许为了叙述好看去改数字或补一个没跑过的读数。** 新结论要么附上可复现的跑法，
要么写明是推测。

## 零依赖是硬约束

`pelican_proxy_check.py` 只用 Python 标准库。这是这个工具「一分钟能跑起来」的全部理由，
不要为了省事引入 requests / httpx / rich。

## 边界

只判**通道完整性**（请求在路上被改了什么），不判**模型身份**（端点背后到底是哪个模型）。
README 里不要出现越过这条边界的断言。
