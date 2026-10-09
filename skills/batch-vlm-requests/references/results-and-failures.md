# 收结果、判状态、补跑、交付前断言

## 1. run 目录长什么样

```text
runs/r001/
├── run.json              # 模型、prompt 原文与哈希、参数、input_roots、分片字节与哈希
├── manifest.jsonl        # 每条：custom_id, source, root, image_sha256, 宽高, shard, line, inner_sha256, line_sha256
├── requests/
│   └── shard-0000.jsonl  # 冻结的提交字节，只读
├── results/
│   ├── smoke.jsonl       # 实时 smoke 原始返回（只追加）
│   ├── batch_out_0.jsonl # batch 下载回来的原文件，不改名不改内容也行
│   └── retry_01.jsonl    # 补跑
└── merged.jsonl          # collect_results.py 生成：每条输入一条终态记录
```

- 一个 run 目录 = 一组不可变的请求。改任何会进入请求字节的东西（prompt、模型、`max_tokens`、图片缩放、序列化）就是 `r002`。
- 价格来源（链接 + 查询日期）、实际花费、跑的机器，追加写进 run 目录下的一个笔记文件即可，不要改 `run.json` 里冻结部分。
- run 目录可能含原图路径和模型输出，按数据本身的敏感级别管理；密钥永远不进来。

## 2. 返回体形状

`run_realtime.py` 写出的每行和 OpenAI batch 输出文件同形，`collect_results.py` 两种都能读：

```json
{"custom_id": "req-000003-5989b1fd0f",
 "response": {"status_code": 200, "request_id": "...", "body": {"model": "...", "choices": [...], "usage": {...}}},
 "error": null, "attempts": 2, "latency_s": 3.4}
```

其他家（Anthropic、Gemini）的 batch 结果形状不同：先写一个小转换，把它们映射成上面的形状（`custom_id`、`status_code`、`body.choices[0].message.content`、`finish_reason`、`usage`）再收。转换脚本也算 run 的一部分，跟着存。

## 3. 状态判定（一个原因一个标签）

| 状态 | 判定 | 怎么处理 |
| --- | --- | --- |
| `ok` | 2xx，正文非空，没顶到上限（`--expect-json` 时还要能解析） | 用 |
| `invalid_json` | 要求 JSON 但解析失败 | 看几条原文：是 prompt 问题就新 run；个别的可以单独重发 |
| `truncated` | 正文非空，但 `finish_reason == length` 或输出 token ≥ 上限 | 提高上限，新 run |
| `empty_at_cap` | 正文空，且顶到上限 | 几乎都是推理模型把额度用在思考上；提高上限，新 run |
| `empty` | 正文空，没顶到上限 | 抽样看原始返回；可能是模型 / 服务端 bug，可少量重试 |
| `refusal` | `message.refusal` 非空或 `finish_reason == content_filter` | 小次数重试（如 2 次），仍拒就保留并报比例 |
| `http_error` | 非 2xx | 408/409/429/5xx 可重试；其他 4xx 看错误信息，多半是请求本身不对 |
| `network_error` | 重试用尽仍无响应 | 重试 |
| `missing` | manifest 有、所有结果文件都没有 | 重试；batch 里出现大量 missing 先查是不是漏下载了某个结果文件 |

另外两种必须当成 bug 处理的情况：

- **foreign ID**：结果里有 manifest 不认识的 ID——混进了别的 run 的结果。
- **多个模型版本**：同一 run 的返回里 `model` 字段不止一个值——provider 中途换了版本，或别名指向变了。报出来，必要时分开统计。

`collect_results.py --retry-ids retry.txt` 只把 `missing`、`network_error` 和可重试的 `http_error` 写出来，再用 `run_realtime.py --ids retry.txt --out results/retry_01.jsonl` 补跑。截断、空输出、拒答不进这个名单，它们要么是新 run，要么按上表单独处理。

## 4. 补跑叠加规则

`collect_results.py` 按命令行给出的文件顺序（旧在前、新在后）叠加：

- 后来的记录只在「至少同样终态」时覆盖前面的：`ok` > 模型给出的非 ok 回答（空、拒、截断、非法 JSON）> `http_error` > `network_error`。
- 被覆盖的记录写进 `superseded`（`状态@文件名`），可追溯每条是哪一次拿到的。
- 补跑必须用**同一个 run 的冻结字节**（`run_realtime.py` 会校验哈希）。用改过的请求补跑，结果就不是同一个实验。

## 5. 交付前断言清单

1. manifest 条数等于输入图片数，`custom_id` 唯一。
2. merged 里每个 ID 恰好一条，没有 `missing`，没有 foreign ID。
3. 状态计数写进交付说明；`refusal`、`empty*`、`truncated` 的比例单列，不并进成功率。
4. **没有任何一条的输出 token（含推理）顶到上限**——顶到了就是截断，不管状态写什么。
5. 形状断言，不只是能解析：任务要求非空的字段（框列表、标签列表）报非空率；多家 teacher 之间某个字段的非空率差很多时点名（例如一家 35% 返回空列表、另一家几乎从不），这通常是 prompt 理解差异或截断，不是数据本身。
6. 交付说明里的每个数字都能从 merged.jsonl 用一条查询复现。
7. 每个交付文件记字节数和 SHA-256；原图用原始路径 / URI 引用，不交付缩放或重编码后的副本路径作为权威字段。
