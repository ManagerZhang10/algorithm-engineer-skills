---
name: api-relay-verify
description: 拿官方直连当对照，查 API 中转 / 网关 / 转售商有没有注水：往请求里偷塞系统提示词、多算 input token、背后换成别的模型、偷偷调低思考档位、改写响应元数据。Claude 走签名回放：把中转返回的 thinking 块拿到官方 API 回放，签名伪造会被拒、对话前缀被改会被识别（还能还原塞进去的原文）、生成它的模型能靠跨模型读取规律认出来；OpenAI 兼容通道（GPT、混元、DeepSeek 等）做 token、思考档位和元数据比对。触发词：中转站检测、中转注水、中转掺水、验证中转、中转是不是真的、偷换模型、降智、relay audit, API proxy verification, model substitution。不用于：判断模型本身好坏（用评测）、只有中转没有官方 key 的场景、没有思考签名的模型背后到底是谁（需要行为指纹工具）。
---

# api-relay-verify · API 中转验真

一句话：**同一个请求，官方发一遍、中转发一遍，凡是不一样的地方都要有解释。** Claude 还多一层硬证据：
thinking 块的签名由官方服务端生成，锁定了生成它的模型和完整对话前缀，中转改不了也造不出来。

检测全在 `scripts/api_relay_verify.py`（只用 Python 标准库）。本文件只写什么时候用、怎么配、怎么读结果。

## 什么时候用

- 要用某条中转跑评测、上生产或大批量调用之前，先验一遍。
- 怀疑中转降智、偷换模型、多收 token。
- 中转换了分组 / 上游，或者隔了一段时间要复查。

前提：**同一个模型要有一把官方直连 key** 当对照。没有官方 key，这个工具帮不上忙。

## 怎么跑

key 只从环境变量读，不要写进命令行参数（会进 shell 历史）。可以用 `--env-file` 指向 `KEY=VALUE` 文件，
文件权限设成 600。

```bash
# Claude：四项全做
python3 scripts/api_relay_verify.py --relay-base https://relay.example \
  --relay-key-env RELAY_KEY --model claude-opus-5-5 --env-file ~/.config/api-relay-verify/keys.env

# OpenAI 兼容通道：base 要给到 /v1 这一级
python3 scripts/api_relay_verify.py --relay-base https://relay.example/v1 --relay-key-env RELAY_KEY \
  --model gpt-x --official-key-env OPENAI_API_KEY
```

常用参数：`--relay-model`（中转上的模型名和官方不同时）、`--official-base`（对照不是默认官方地址时）、
`--checks inject,signature,effort,meta`（只跑其中几项）、`--effort-runs N`（档位检查每档次数，默认 2）、
`--candidate "文本"`（补充猜测的注入原文）、`--probe-models a,b`（跨模型回放用的模型）、`--out DIR`。
报告默认写到 `~/.local/share/api-relay-verify/<时间>/report.md`，原始数据在同目录 `raw.json`。

**花费**：一轮 Claude 检查官方和中转各约 30 个请求，大头是档位检查那道题（high 档几千思考 token）；
Opus 级别一轮在 1 美元以内。思考很长的模型（某些国产推理模型 high 档能到 5 万思考 token）先用
`--effort-runs 1` 或 `--checks inject,meta` 摸底。跑之前把预计花费告诉用户。

## 四项检查和读法

| 检查 | 怎么做 | 结论怎么读 |
| --- | --- | --- |
| 注入 inject | 同一个极短请求两边各发 3 次，比 input token；Claude 再用官方 `count_tokens`（免费）试候选系统提示词，找出正好对上中转数字的那句 | 差值恒定 = 固定塞了一段 system；三次不一致 = 后面挂着多个上游或间歇注入；中转比官方少 = usage 被改写 |
| 签名回放 signature（仅 Claude） | 把中转的 thinking 块原样放进对话，发给官方 API，带 `thinking-binding-controls-2026-08-01` 让官方逐块报告：通过 / 前缀不一致 / 模型不匹配；篡改签名必须 400 | 见下一节 |
| 思考档位 effort | 同一道有标准答案的题，low / high 两档各跑 N 次，比思考 token 和答对率 | high 档思考量不到官方一半 = 档位被调低；low 档远高于官方 = 被统一改写；同一区间 = 正常 |
| 元数据 meta | 消息 id 格式、`model` 字段、usage 字段、响应头、`count_tokens` 是否可用 | 只作线索：id 是 `msg_bdrk` / `msg_vrtx` 说明上游是 Bedrock / Vertex；usage 多出的字段是中转或上游平台的痕迹 |

### 签名回放怎么判

先看三组对照，**对照不成立就不下结论**（脚本会自动标「无法判定」）：

1. 官方自己的块原样回放 → 必须通过；
2. 官方的块改了 system 再回放 → 必须报「前缀不一致」（不报说明这个模型 / 账号不做前缀校验，只能验真伪和模型）；
3. 签名改一个字符 → 必须 400。

然后看中转的块：

- **官方报 400**：签名是伪造的；或者上游不是 Claude API（Bedrock / Vertex 的块可能跨平台解不开），这时看 id 前缀区分。
- **原样通过**：签名真实，请求没被改。
- **前缀不一致**：中转改过请求。脚本逐个试候选系统提示词，哪个补上后能通过，哪个就是塞进去的原文——这是密码学证据，不是猜。
- **跨模型回放**：同一个块分别回放给几个模型，记录谁能读、谁丢弃。中转的块和官方同款模型的块在每个模型上表现都一样，才算「是这个模型生成的」。

签名的前缀和模型绑定是 Fable 5.1、Opus 5.5、Sonnet 5.5 这一代 Claude 才有的（本技能在 Opus 5.5 上实测过）；
更早的模型对照 2 会不成立，脚本只给真伪结论。

## 已知局限

- **一次只是一张快照。** 中转可以随时换上游，注入也可能间歇出现（实测有中转相邻几轮的注入量是 0、几千、近万）。
  要下结论就隔几小时多跑几轮；用之前当天再跑一遍。
- 签名只覆盖模型、system、tools、对话内容。`max_tokens`、档位、temperature 这类请求参数不在签名里，档位靠 effort 一项单独查。
- OpenAI 兼容通道没有签名，查不了「背后换没换模型」。要查这个用单 token 答案分布之类的行为指纹工具，同样要先用官方 key 建基线。
- 「塞了一句 Claude Code 身份提示词」是用 Claude 订阅账号转发的典型特征：模型是真的，但每题都多了一句身份设定，
  正式评测和官方直连比时这是个干扰项，要在结论里写明。

## 失败怎么报

- 缺 key：脚本直接退出并说明是哪个环境变量。让用户把 key 放进环境变量或 600 权限的 env 文件，不写进命令行、报告或仓库。
- 官方请求失败（额度、权限、模型名不对）：该项标「无法判定」，原样转述官方报错。
- 中转请求失败：标出来并转述报错，不要拿失败的请求下「中转造假」的结论。
- 给用户的结论先用一两句大白话（「模型是真的，但每个请求被加了一句话」），再附报告路径和关键数字。
