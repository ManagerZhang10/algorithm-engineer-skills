# 各家 provider 速查

> **本页所有数字和规则截至 2026-10，以官方文档为准。** 价格、上限、图片换算规则、字段名都会变；
> 开跑前打开对应官方页面核对一次，把核对日期和链接写进 `run.json` 或 run 记录里。
> 本页只用来知道「该去查什么」，不能代替查。

## 1. 图片怎么放进请求

| 接口 | 内联写法 | 备注 |
| --- | --- | --- |
| OpenAI 兼容 Chat Completions | `{"type":"image_url","image_url":{"url":"data:image/png;base64,<...>","detail":"high"}}` | 很多第三方 / 开源推理服务也认这个形状；`detail` 只有部分模型支持 |
| OpenAI Responses | `{"type":"input_image","image_url":"data:image/png;base64,<...>"}` | 或先上传拿 `file_id` |
| Anthropic Messages | `{"type":"image","source":{"type":"base64","media_type":"image/png","data":"<...>"}}` | 也支持 `source.type=url` 和 Files API；批量时别用 url |
| Gemini generateContent | `{"inline_data":{"mime_type":"image/png","data":"<...>"}}`（REST 有时写作 `inlineData` / `mimeType`） | 单请求有内联大小上限，大图走 File API |

共同注意：

- `media_type` 要和真实字节一致（PNG 写成 JPEG 有的家会报错，有的家静默按错的解码）。`build_requests.py` 按文件头魔数判断，不按扩展名。
- 要缩图就**在构建前显式缩**，把缩后的文件当输入并记哈希；不要指望 provider 内部缩放的规则不变。缩图会改 token 数，也会改结果，是新 run。
- 同一请求多张图时，图和文字的先后顺序也是请求的一部分，冻结后不要动。

## 2. Batch 通道

| | OpenAI Batch | Anthropic Message Batches | Gemini Batch |
| --- | --- | --- | --- |
| 价格 | 约实时价五折 | 约实时价五折 | 约实时价五折 |
| 完成时限 | 24 小时窗口 | 多数 1 小时内，最长 24 小时 | 目标 24 小时内 |
| 单批上限（条数 / 文件） | 约 5 万条、约 200 MB | 约 10 万条、约 256 MB | 输入文件约 2 GB；内联请求方式另有小得多的上限 |
| 关联键 | `custom_id` | `custom_id` | 请求里的 `key` / metadata |
| 结果顺序 | 不保证 | 不保证 | 不保证 |

（均截至 2026-10，以官方文档为准。）

要点：

- **单文件字节上限各家差一个数量级**。同一个 300 MB 的内联分片在一家安全、在另一家超限。用 `--shard-max-bytes` 按目标家上限留 20–30% 余量。
- batch 结束（ended / completed / expired）后不能续跑，剩下的只能新开一批或走实时。
- batch 结果文件通常只保留有限天数，拿到就落盘。
- 有的家 batch 不支持某些新模型或某些参数（如部分工具调用、流式），提交前查兼容表。

## 3. 图片 token 怎么算（用于粗估）

| 规则族 | 近似公式 | `estimate.py --scheme` |
| --- | --- | --- |
| OpenAI 瓦片制（GPT-4o 系） | 先缩进 2048×2048，再把短边缩到 768，按 512 px 切瓦片：`85 + 170 × 瓦片数`；`detail=low` 固定 85 | `openai-tile` |
| OpenAI 补丁制（部分 mini / 新模型） | 按 32 px 补丁计数，有上限，再乘模型相关系数 | 用 `fixed` 或直接校准 |
| Anthropic | 长边先压到约 1568 px（总像素约 115 万以内），`tokens ≈ 宽 × 高 / 750` | `anthropic` |
| Gemini（2.x 系） | 两边都 ≤ 384：258；否则按 768 px 瓦片，每块 258 | `gemini` |
| Gemini（较新模型） | 有 `media_resolution` 之类的参数，每图预算按档位给 | 用 `fixed` 或直接校准 |

（均截至 2026-10，以官方文档为准。）

**公式只用来第一眼看量级和找出超大图。** 真实数字永远以 smoke 返回的 `usage` 为准：

```bash
python3 scripts/estimate.py runs/r001 --calibrate runs/r001/results/smoke.jsonl \
    --price-in <USD/1M> --price-out <USD/1M> --batch-discount 0.5
```

脚本会打印「公式 / 实测」比值；差 25% 以上就说明规则变了或参数（如 `detail`、分辨率档）没对上，以实测为准并去查文档。

## 4. 推理 token 在哪

| 接口 | 推理 token 字段 | 和上限的关系 |
| --- | --- | --- |
| OpenAI 兼容 | `usage.completion_tokens_details.reasoning_tokens` | 推理模型用 `max_completion_tokens`，推理 + 正文共用 |
| Anthropic | 开 extended thinking 时有 `thinking` 内容块；计入输出 token | `budget_tokens` 必须小于 `max_tokens` |
| Gemini | `usageMetadata.thoughtsTokenCount` | 有 thinking budget 参数 |
| 一些 OpenAI 兼容的推理模型 | 正文在 `message.content`，推理在 `message.reasoning_content` | `max_tokens` 小了正文为空；生成长文给到 16000 左右 |

（均截至 2026-10，以官方文档为准。）

推理 token 按输出价计费，所以「答案很短」不等于「输出便宜」。

## 5. 中转 / 代理

评测、判分、teacher 对比一律走官方直连。见过的中转问题：降质；每次请求被注入几千个额外的缓存 prompt token（成本数据变脏）；不返回推理 token 细分；高峰期批量报「无可用通道」。如果某个场景只能走代理，单独标注，不要和直连结果放在同一张表里比。
