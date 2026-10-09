# 协议清单、protocol.json 模板、报告模板

## 1. 冻结前逐项打勾

### 问题与臂

- [ ] 这次比的是「模型本身」还是「端到端链路」，只选一个作为主口径
- [ ] 每个臂的精确标识：模型 ID / ckpt 路径 + step / 供应商路由字符串 / prompt 版本号
- [ ] 每个臂的接入方式：官方直连 / 自部署 / 第三方网关（网关单独成臂）
- [ ] 每个臂接口的官方文档链接和查阅日期（接口会变）
- [ ] 各臂背后若是同一个模型的不同路由，仍按不同臂处理

### 输入

- [ ] 样本来源、数量、抽样方式、随机种子
- [ ] 与任何一臂的训练 / 调参数据是否重叠（ckpt 对比尤其要查验证集泄漏）
- [ ] 预处理只做一次：缩放算法、目标尺寸、颜色模式、EXIF 旋转、编码格式和质量、文本模板
- [ ] 冻结后的输入落盘，`freeze_manifest.py` 生成 `manifest.jsonl` + `manifest.digest`
- [ ] prompt / system prompt 逐字节相同；统一后缀写进 prompt 本身
- [ ] 多模态：图片传法统一（都 base64 内联，或都传同一 URL），不混用

### 推理参数

- [ ] temperature / top_p / top_k / max_tokens / stop / seed
- [ ] 推理档位（reasoning effort、thinking 开关、思考预算）
- [ ] 输出尺寸 / 质量档 / 输出格式（PNG / JPEG）
- [ ] 重复次数（随机性大的任务每样本 ≥ 3 次）
- [ ] 超时、重试次数、重试是否换种子
- [ ] 某臂不支持的参数列入「未对齐项」

### 指标

- [ ] 主指标一个；名字、公式、方向（越大越好 / 越小越好）
- [ ] 指标的两个操作数是哪两样产物（例如「模型实际输入」vs「模型原生输出」）；缩略图、截图、二次缩放图不能当操作数
- [ ] 归一化和聚合方式；是否给置信区间（bootstrap）或显著性
- [ ] 裁判模型（LLM-as-judge）：模型 ID、prompt、温度固定；位置偏差（A/B 顺序随机化）
- [ ] 已在几条极端 case 上和肉眼 / 人工判断对照过
- [ ] 指标盲区写下来

### 失败处理

- [ ] 状态枚举：`ok / refused / content_filter / error / timeout / invalid_output`（可按需加）
- [ ] `invalid_output` 的判定（尺寸不符、格式解析失败、空输出、截断）
- [ ] 主指标只在全部臂 `ok` 的交集上算；失败率单独报告
- [ ] 交集占比过低时的补充口径（例如失败记最差分算全集）

### 运行

- [ ] 先烟测 1～3 条 / 臂，读原始输出和轨迹
- [ ] 从请求日志 / 响应元数据核对实际参数
- [ ] 起量后结果写 `results.jsonl`：`sample_id`、`status`、`input_sha256`、`params`、输出路径、耗时、token 用量
- [ ] 跑批中途不改配置；必须改就开新 run 目录，旧结果不混用

## 2. protocol.json 模板

```json
{
  "run_id": "2026-10-09_vlm-caption-compare",
  "question": "同一批图片上，三家 VLM 的描述事实准确率谁高（模型本身口径）",
  "mode": "model_only",
  "manifest_digest": "<freeze_manifest.py 输出的 digest>",
  "n_samples": 200,
  "arms": [
    {"name": "A", "model_id": "<exact-model-id>", "route": "<exact-route-string>",
     "access": "official_direct", "doc_url": "<official-doc-url>", "doc_checked_at": "2026-10-09"},
    {"name": "B", "model_id": "<exact-model-id>", "route": "<exact-route-string>",
     "access": "official_direct", "doc_url": "<official-doc-url>", "doc_checked_at": "2026-10-09"}
  ],
  "preprocess": {"resize": "LANCZOS long-edge 1024", "format": "JPEG q95", "exif_transpose": true},
  "prompt_sha256": "<sha256 of the exact prompt bytes>",
  "decoding": {"temperature": 0, "top_p": 1, "max_tokens": 2048, "seed": 1234, "repeats": 1},
  "unaligned": [
    {"arm": "B", "item": "seed", "note": "接口不支持 seed，用 3 次重复取均值代替"}
  ],
  "metric": {
    "primary": "fact_precision",
    "operands": ["reference_annotation", "model_raw_text"],
    "aggregate": "mean over common_ids, bootstrap 95% CI",
    "blind_spots": "只检查写出来的事实是否正确，不惩罚遗漏"
  },
  "failure_policy": {
    "statuses": ["ok", "refused", "content_filter", "error", "timeout", "invalid_output"],
    "max_retries": 2,
    "score_on": "intersection_of_ok"
  }
}
```

## 3. 报告模板

```markdown
## 结论（大白话）
<一两句：谁在什么条件下更好，差距多大，可信度如何>

## 每臂 N
<粘贴 intersect.py 生成的 report.md>

## 主指标（交集 N = xx）
| 臂 | 主指标 | 95% CI | 失败率 |

## 协议摘要
- manifest digest：<digest>
- 输入：<分辨率 / 格式 / prompt 版本>
- 解码：<temperature / max_tokens / 推理档位 / 重复次数>
- 每臂实际路由与模型 ID：<从请求日志读出的值>
- 跑批日期：<日期>

## 未对齐项
- <哪一臂、哪个参数、可能对结论的影响方向>

## 指标盲区
- <这个指标看不到什么>

## 抽样看过的输出
- <每臂各看了几条、有什么共性问题；附几条代表样例>
```
