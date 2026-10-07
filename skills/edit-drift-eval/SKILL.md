---
name: edit-drift-eval
description: 图像编辑模型多轮漂移评测：同一张图、同一串 prompt，让 N 个编辑模型（FLUX 3 / Ideogram 4.5 / GPT Image 2.5 sunburst / Nano Banana 2.1，可加）各自在自己上一步的输出上连续改 K 步，量「背景 Drift」（远处背景与原图的平均像素差），出 N 栏并排对比视频。用户说「多轮编辑漂移」「连续改 30 步看会不会糊/偏色」「几家编辑模型并排视频」「加一家模型跑 drift」「用已有输出重出 drift 视频」时用。不用于单步编辑质量评测、BBox/mask 保持度打分（那是 image-edit-api-eval），也不用于盲测。
---

# edit-drift-eval

一句话：每个模型都拿自己上一步的结果接着改，看改到第 30 步时没让它动的背景还像不像原图。

能力全在 `edit-drift`（`~/.local/bin/edit-drift` → 本 skill 的 `scripts/edit_drift.py`）。本文件只写判断。

```bash
edit-drift models                                   # 已有适配器、渠道、单步估价
edit-drift run    <wd>/chains.json --budget 20 --dry-run   # 先看计划和估价，不花钱
edit-drift run    <wd>/chains.json --budget 20      # 跑链（付费），可中断续跑
edit-drift score  <wd>/chains.json                  # patches.json / drift.json / manifest.json
edit-drift render <wd>/chains.json                  # <wd>/video/<chain>.mp4 + all.mp4
```

`run` 是付费动作：先 `--dry-run` 把估价告诉用户，预算没说就问。`score` / `render` 不调 API。

准备：`FAL_KEY`（FLUX / Ideogram / GPT）和 `GEMINI_API_KEY`、`GEMINI_BASE_URL`（NB2.1）放环境变量，或写进一个 dotenv 文件并用 `EDIT_DRIFT_ENV_FILE` 指过去；ffmpeg 从 `FFMPEG` 或 PATH 找；字体默认用 macOS 自带的 Helvetica Neue 和冬青黑体。

## chains.json 怎么写

工作目录 = chains.json 所在目录，所有产物都写在它旁边。

```json
{
  "size": 1024,
  "suffix": " Keep everything else in the image exactly the same.",
  "models": ["flux3", "ideogram45", "gpt25-sunburst", "nb21"],
  "images": {"couch": "inputs_raw/couch.jpg"},
  "chains": [{"id": "couch-shirt", "image": "couch", "prompts": ["Change his T-shirt to ... Keep everything else in the image exactly the same.", "..."]}]
}
```

- 输入图由 `run` 统一中心裁正方形、LANCZOS 缩到 `size`（默认 1024），存 `inputs/<image>.png`，每条链的 `00.png` 就是它。不要给不同模型不同尺寸的输入。
- 所有模型的 prompt **逐字相同**。统一后缀写进 prompt 本身，同时填 `suffix`，视频顶部显示时会去掉它。
- 一张图配几条链（比如换衣服、改头发）时 `image` 写同一个名字；背景区域按图选，同一张图的所有链共用。
- `chains` 的顺序就是 `all.mp4` 的拼接顺序。
- **复用已有输出、不花钱**：给模型加 `sources`，该模型不会被 `run` 调用，`score` / `render` 直接读那个目录（`NN.png`），`{chain}` / `{image}` 会被替换：
  ```json
  "sources": {"gpt25-sunburst": {"dir": "/abs/round-02-gpt25/out/{chain}-gpt25",
              "log": "/abs/round-02-gpt25/log.jsonl", "log_chain": "{chain}-gpt25"}}
  ```
  `log` 用来识别「被审核拦截」；可加 `date` 覆盖按文件时间推断的跑批日期。
- 可选 `labels`（栏标题）、`patches`（手动指定背景区域，同 `--patches`）。

## 背景 Drift：定义与盲区

- 每张图自动选 3 块 96×96 背景区域（整图 1024 时；其他尺寸按比例缩放）：离**所有模型第 1 步编辑区域的并集**最远，两两中心距 ≥ 360 px。第 1 步整图都变了的模型（如 NB2.1 整图重画）不参与定位。
- `drift_k = 3 块区域内 |x_k − x_0| 的平均（RGB 0–255）`，**始终与原图比**，不和上一步比。
- 选区随参与模型而变；要和以前的结果直接比，就用 `--patches` 传旧的 `patches.json`。出报告前人工看一眼这 3 块是不是确实是地板/树/墙。
- **盲区**：只量远处背景，量不到编辑区旁边的局部损伤。例：FLUX 3 换衣服链在贴回圈内出现网格噪点，Drift 仍是 0。结论里写 Drift 时要带上这句，必要时补局部截图。
- 颜色档：< 5 绿（肉眼看不出），< 20 黄，其余红。

## 公平性检查清单（manifest.json 要能回答，交付时写明未对齐项）

1. 质量档：各家口径不同（FLUX 3 只有 1k 分辨率档；Ideogram / GPT 用 medium；NB2.1 没有质量参数），写明各用了哪档。
2. 输出格式：NB2.1 只返回 JPEG（原样存 `NN.jpg`，下一步原样喂回；`NN.png` 是无损解码供分析），其余 PNG。
3. 渠道：NB2.1 走 Google 官方直连，其余走 fal。**评测只走官方直连或 fal，不用中转站。**
4. 每条链只跑 1 次、无种子重复——单次结果，不当成稳定排名。
5. 跑批日期：不同模型隔几天跑的要写出来（模型可能被静默更新）。
6. 被拦截/失败的链：manifest 里 `status` 为 `blocked` / `failed`，视频里该栏停在最后一张成功图并标注「被内容审核拦截（第 k 步）」。比较时只比双方都有数据的步数。

## 成本与规模

- 单步粗估：NB2.1 ≈ $0.04（按返回 token 实算），GPT Image 2.5 sunburst medium ≈ $0.025，FLUX 3 1k ≈ $0.096、Ideogram 4.5 medium ≈ $0.06（2026-10 实测）。4 模型 × 4 链 × 30 步 ≈ $26。
- `--budget` 是总上限，含 log.jsonl 里已花的；脚本按单步估价预扣，超了就停。跑完把实际花费记进对应目录的 ledger。
- 几十次以内的调用本机全并发（默认每条「链 × 模型」一个线程，上传并发 8）；更大规模放到常驻 CPU worker 上跑，跑完把整个工作目录拉回本地再 `score` / `render`。
- 加新模型：在 `scripts/edit_drift.py` 的 `ADAPTERS` 加一个函数和一条登记（标签、渠道、端点、分辨率、质量档、输出格式、单步估价），先用 `--max-steps 1` 试一步。

## 内容审核

- 人像图在 fal 上可能触发审核（422 `content_policy_violation`），GPT Image 2.5 尤其常见，而且是随机的：同一步重试有时能过。
- 脚本把它记为 `blocked`，不算普通失败；默认同一步再试 2 次（`--blocked-retries`），仍拦截就停这条链，续跑时也不再重试。不要为了凑满 30 步无限重试。
- 普通失败（网络、5xx）单链连续 3 次后停，续跑会从断点接着来。

## 视频版式（默认值不要随手改）

1920×1080；顶部步数 + prompt；中间 N 栏出图（不画测量框）；每栏下方「背景 Drift（与原图比）」大数字 + 累积曲线；底部一行中文解释。每步 0.25 秒，原图帧 0.5 秒、末帧 0.5 秒（段间约 1 秒停顿），`all.mp4` 为合集。3 栏、4 栏都已验证；5 栏以上能排但偏挤。

## 交付

给用户：工作目录绝对路径、`video/all.mp4`、`drift.json` 里第 1 / 10 / 30 步的表、`manifest.json` 里的未对齐项和拦截情况，以及 Drift 盲区那句话。密钥只从环境变量或 `EDIT_DRIFT_ENV_FILE` 指向的 dotenv 文件读，任何产物里都不能出现。
