---
name: batch-vlm-requests
description: 把一批图片发给 VLM / 多模态 API（批量打标、蒸馏造数据、LLM-as-judge 批量判分、多家 teacher 对比）时的请求工程：图片怎么传（默认内联 base64，不传 URL）、走 batch 还是实时通道、开跑前估成本并用几十条真实请求校准、并发与重试、冻结实际提交的请求字节、按 custom_id 收结果并把空输出 / 截断 / 拒答分开记。用户说「把这几千张图丢给 GPT/Claude/Gemini 打标」「用 VLM 批量判分」「蒸馏一批图文数据」「batch API 怎么提交」「估一下跑完要多少钱」「结果怎么对回原图」「为什么返回空内容」时用。English keywords: batch inference, VLM, multimodal, image labeling, distillation, LLM-as-judge, Batch API, base64 inline images, token cost estimate, rate limit, retry, reproducibility, custom_id, empty content, reasoning tokens. 不用于：单张图的问答、写 prompt 本身、图像生成 / 编辑 API 评测、训练集的质量判断（那是数据准入质检）。
---

# batch-vlm-requests

一句话：**把图片字节直接塞进请求、提交前把每条请求的字节冻住并记下哈希、先花一点钱实测再开全量、结果只按 ID 对回去。**

本文件只写判断。干活的是 `scripts/` 下四个只用 Python 标准库的脚本：

```bash
python3 scripts/build_requests.py images/ --out runs/r001 --model <model> --prompt-file prompt.txt --max-tokens 4096
python3 scripts/estimate.py runs/r001 --scheme openai-tile --out-tokens 300            # 公式粗估，不花钱
python3 scripts/run_realtime.py runs/r001 --base-url <https://.../v1> --api-key-env <ENV_NAME> --limit 30 \
        --out runs/r001/results/smoke.jsonl                                           # 付费 smoke
python3 scripts/estimate.py runs/r001 --calibrate runs/r001/results/smoke.jsonl \
        --price-in <今天查的价> --price-out <今天查的价> --batch-discount <折扣>         # 用实测校准
python3 scripts/collect_results.py runs/r001 runs/r001/results/*.jsonl --write runs/r001/merged.jsonl
```

`build_requests.py` 产出 OpenAI 兼容格式（`/v1/chat/completions` 的 batch 行）。别家原生格式（Anthropic `source.type=base64`、Gemini `inline_data`）照同样的冻结规则自己写构建器，形状见 `references/providers.md`。

## 流程

1. **定口径**：任务、模型、prompt、输出格式（要不要 JSON）、`max_tokens`。这些一变就是新 run。
2. **构建并冻结**：`build_requests.py` 写进一个**新的** run 目录，目录已存在就拒绝。
3. **公式粗估**：`estimate.py`，告诉用户量级和最大的那几张图。
4. **付费 smoke**：几十条、尽量跨 2 个分片，跑真实请求（见下文「开全量之前」）。
5. **校准估价**：`estimate.py --calibrate`，把校准后的数字和价格来源（今天查的哪页文档）给用户，**预算没说就问**。
6. **选通道、选机器**，跑全量（batch 或 `run_realtime.py`）。
7. **收结果**：`collect_results.py`，按状态分类，只补跑该补的。
8. **交付**：merged.jsonl + run.json + manifest，加一段状态计数。

## 规则一：图片默认内联 base64，不传 URL

把图片字节直接放进请求（OpenAI `image_url` 用 `data:` URI，Anthropic `source.type=base64`，Gemini `inline_data`）。不要给 provider 一个公网 URL 让它自己去抓。

**为什么**：传 URL 时去取图的是 provider 的服务器，这个抓取动作通常有一个**单独的、组织级共享的、你看不见也调不动**的配额；一条两图请求算两次抓取。batch 一次性交出去后，取图节奏由 provider 决定，撞上配额的行会直接返回限流错误，不会排队重试。另外 URL 会过期、会被改、会被防盗链拦，复现时你无法证明模型看到的是哪张图。

**代价几乎为零**：图片 token 由图片尺寸决定，跟字节怎么传过去无关，带宽不计费。

**典型事故**：全量几千条传 URL，三分之一被取图限流打回，补数只能走全价实时通道；而且这种问题 smoke 测不出来——几十条请求离配额差两个数量级，**只在规模下出现**。

**例外**：单图很大、总量超过 batch 文件上限时，用 provider 自己的文件存储（如 Gemini File API、OpenAI Files）上传后引用 file id，那仍然是「字节在你手里交出去」，不是让对方去抓公网 URL。

### 内联之后，分片大小变成字节问题

单条请求从几 KB 涨到几百 KB，**分片必须按实测字节切，不能沿用条数**。各家单文件上限差很多（数量级不同），同一个分片在一家安全、在另一家超限，别用一家的经验推另一家。`build_requests.py --shard-max-bytes` 按字节切，`estimate.py --shard-limit-bytes` 复核。按行序切分时同类大图会扎堆，所以留 20–30% 余量，别按均值卡满。

## 规则二：batch 还是实时

经验阈值（不是硬规定）：**按图片张数算，≥ 1000 张默认 batch，否则随意；用户明确说要实时就用实时。**

- batch：通常有明显折扣（截至 2026-10，主流家多为约五折，以官方文档为准），代价是交出节奏控制、结果最长可能要等一天。图片内联后 batch 原来最大的风险（取图限流）就没了。
- 实时更合适的情况：调 prompt / smoke 要立刻看结果；全量跑完剩几十条残渣；batch 已终结又急着交付。
- 一句话：**batch 省钱但交出控制权，实时贵但拿回控制权。**

## 开全量之前：先花一点钱验证

任何**第一次**的组合（第一次内联、换 provider、换模型、换图片格式、换输出格式），先跑几十条真实请求，确认：

1. provider 接受这个请求形状（单测通过不算）；
2. `usage` 里的输入 token 与估算同量级——**同时证明图真的到了模型手里**；公式和实测差 25% 以上，就以实测为准；
3. 输出确实随图片变化（不是每条都一样的标签 / 框）；
4. 输出 token 没有顶到 `max_tokens`（见规则六「空输出和截断」）；
5. 有历史结果的话，同一批样本逐条对比。

验证的钱通常是事故成本的百分之一量级，而且很多问题（分片超限、空输出、价格口径）只有真跑才量得出来。

## 规则三：成本先估、再实测、价格不写死

- 价格、折扣、图片 token 换算规则都会变。**每次开跑前去查 provider 当前的定价页和视觉文档**，把查到的数和日期写进 run 记录；脚本里不内置任何价格。
- 公式只是第一眼（`estimate.py --scheme openai-tile|anthropic|gemini|fixed`，各家规则摘要见 `references/providers.md`，都标了截至日期）。**给用户的数字以 smoke 校准为准**：`--calibrate` 读真实 `usage`，按 输入/输出/推理 token 的均值外推。
- 推理模型的推理 token 按输出价计费，常常比答案本身多几倍。估价时 `--out-tokens` 要填「答案 + 推理」。
- 报给用户时给范围：实时价、batch 价、样本数；样本少于 20 条就明说长尾可能移动结论。

## 规则四：并发、重试、在哪跑

- **小批量（几十条）直接本机全并发**，起远程作业的开销比跑本身还长。
- **大批量（成千上万条、或要跑几小时）放到常驻 worker / 云主机上跑**，编排脚本（提交、轮询、下载）也放上去，别让笔记本合盖就断。结果直接写到持久存储，run 目录整个可以拉回来。
- 实时通道并发默认开足（如 32），遇到 429 再退避并报告实际并发；不要从 4 起步慢慢试。`run_realtime.py` 对网络错误、408/409/429/5xx 做指数退避 + 抖动，尊重 `Retry-After`；4xx（除上述）视为终态不重试。
- **可续跑**：结果文件只追加，重跑同一命令会跳过已有终态的 ID。
- **评测、判分只走官方直连**。第三方中转 / 代理可能降质、往请求里注入内容（多出来的缓存 token 让成本数据变脏）、不返回推理 token 细分、批量时报「无可用通道」。用中转跑出来的分数不能和直连的比。
- 密钥只从环境变量读（`--api-key-env` 传**变量名**），不写进命令行、run 目录、日志和提交历史。

## 规则五：冻结实际提交的请求字节

smoke、全量、补跑必须复用**同一个构建器、同一个序列化实现**。构建完、提交前冻结两层：

- `inner`：provider 真正消费的请求体（`body`）；
- `line`：batch 文件里的完整记录（含 `custom_id`、`method`、`url`、`body`）。

每条记两者各自的 SHA-256（行哈希按该行准确的 UTF-8 字节、不含换行），另记每个分片文件的 SHA-256。`build_requests.py` 写在 `manifest.jsonl` 和 `run.json` 里；`run_realtime.py` 发送前校验，字节不一致就拒发。

- 比较时同层比：inner 对 inner、整行对整行。拿解包后的 body 跟整行比只会制造假差异。
- 已提交的分片是不可变输入，提交、重试、恢复时**不要 parse 再序列化一遍写回**。
- 要改 prompt、字段、图片编码、`max_tokens`、序列化方式，就是**新 run 目录、新哈希**；不要在原 run 名下悄悄重建。
- 不同 provider 的原生请求本来就是不同的实验输入，不要为了「格式统一」改写冻结后的请求。

## 规则六：结果按 ID 对回，每条输入恰好一条终态记录

- **只按 `custom_id` 对回，永远不信 provider 返回的行序。** ID 里带图片哈希前缀，manifest 里存原图相对路径和完整哈希。
- `collect_results.py` 给 manifest 里每个 ID 一条记录，状态互斥、一个原因一个标签：`ok` / `invalid_json` / `truncated` / `empty_at_cap` / `empty` / `refusal` / `http_error` / `network_error` / `missing`。出现不属于本 run 的 ID 直接报错（多半是混进了别的 run 的结果）。
- 补跑结果按文件先后叠加，保留 `source_file` 和 `superseded` 血缘；后来的网络失败不会覆盖之前已拿到的模型回答。
- 拒答、空输出、截断都是**显式记录**，不静默丢掉、不手工修、不算进系统成功率。

### 空输出和截断：先看是不是推理模型把 max_tokens 吃光了

推理模型的思考过程和正文共享输出上限。上限给小了，思考把额度用完，**正文返回空字符串，状态却还是成功**。判断方法：`finish_reason == "length"`，或 `输出 token（含推理 token）≥ max_tokens`。

- 是这种情况（`empty_at_cap` / `truncated`）：**提高 `max_tokens` 开新 run**，原样重试没用。生成长文时给到上万（如 16000）很常见。
- 推理内容另有字段（如 `reasoning_content`、`thinking` 块），正文只取 `content`，推理内容不要混进结果。
- 交付前做一次全量断言：没有任何一条的「输出 + 推理 token」顶到上限，否则就是被截断了，不管状态写的什么。

### 拒答

`message.refusal` 非空或 `finish_reason == "content_filter"` 记为 `refusal`。人像类数据常见随机拦截，同一条重试有时能过：给一个小的重试次数（如 2 次），仍拒就保留拒答记录、在交付里写明比例，不要为了凑满无限重试。多家 teacher 对比时，拒答率本身就是要报的一列。

## 交付给下游

最少给：`run.json`（模型、prompt、参数、分片哈希、价格来源和日期）、`manifest.jsonl`（ID → 原图）、`merged.jsonl`（每条输入一条终态记录）、状态计数和总花费。README 里每个数字都要能从交付文件算出来。结构化解析出的字段和原始文本都保留，并写明哪个是权威字段。

## 参考

- `references/providers.md`：各家传图格式、batch 上限、图片 token 规则、推理 token 字段（均标截至日期，用前核对官方文档）。
- `references/results-and-failures.md`：返回体形状、状态判定细节、补跑与叠加、交付前断言清单。
