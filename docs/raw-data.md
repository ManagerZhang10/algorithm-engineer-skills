# Proxy-check 原始数据说明

看板是给人看的；做分析、算趋势要直接读快照。每轮一个目录：

```text
<out>/
├── index.html                 ← 看板，每轮重出
└── runs/
    └── YYYYmmdd-HHMM/
        ├── run.json           ← 那一轮的全部事实
        └── <泳道名>.svg       ← 成功出图的泳道各一张
```

## run.json

顶层：`stamp`、`at`（本地时间 ISO）、`prompt`、`prompt_version`、`lanes`。

`lanes` 里一条泳道记录：

| 字段 | 含义 |
| --- | --- |
| `key` / `name` / `channel` / `model` | 泳道标识、显示名、通道名、请求的模型 id |
| `effort` | 思考档位的人读标注，来自配置里的 `PB_<名>_EFFORT` |
| `baseline` | 这条是不是该模型的官方直连基线，来自配置里的 `PB_<名>_BASELINE`。看板拿它算入 token 差值；没有显式标记时回退到 `channel` 名里带「直连」/ `direct` 的那条 |
| `ok` / `error` | 是否成功出图；失败原因 |
| `latency_ms` | 总耗时 |
| `ttft_ms` | 首个**正文**字符的耗时。reasoning 模型会先吐几千 token 思考，那段不该算进「多久开始干活」 |
| `prompt_tokens` / `completion_tokens` | 画图那一发的入 / 出 token |
| `reasoning_tokens` | 思考 token。`null` = 该通道不回传这个字段，**不等于没思考** |
| `model_echoed` | 服务端回显的 model |
| `response_id` | 画图那一发的响应 id 前缀，最多 24 字符。OpenAI 协议取流式 chunk 的 `id`，Anthropic 协议取 `message_start` 里的 `message.id`；通道不回传时是空串 |
| `usage_extra` / `usage_extra_values` | `usage` 里的非标准字段名与其标量值 —— 中转层的实现指纹。第三方转售常会漏出自己的计费、缓存或上游平台字段 |
| `text_chars` / `svg_bytes` / `path_count` | 正文字符数 / SVG 体积 / 图元数 |
| `cheats` | 命中的绕过手段，如 `image`、`text`、`外部引用` |
| `error_code` / `error_args` | 失败原因的机器可读形式（`truncated` / `no_svg` / `svg_invalid` / `cheats`），看板据此用别的语言重述同一条错误；`error` 始终是中文原文 |
| `truncated` | SVG 被 max_tokens 截断 |

## 算注入量

同一个 `model`、不同 `channel`，拿官方直连那条（`baseline: true`）的 `prompt_tokens` 当基线，
其余通道减基线即为注入量。**只在同一个 `model` 内部算**：各家分词器不同，跨 model 比入 token
量的是分词器，不是中转。题面逐字相同、思考档位也填成一样，差出来的就是被塞进去的东西。没有直连基线的模型
算不出这个差值。

跨轮次看这个差值的**方差**比看它的绝对值更有信息量：

- 恒定 → 固定的隐藏 system prompt，可以当常量扣掉
- 忽大忽小 → 后面挂着多个上游或池子、路由随机，同一个 prompt 的行为不可复现

## 归档

脚本默认只留最近 3 轮，超出的目录会被删掉。要做长期趋势，在每轮跑完后把 `run.json` 复制
出去（按 `stamp` 命名），几 KB 一份，攒几个月也不大。
