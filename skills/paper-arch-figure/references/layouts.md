# figlib 版式 API

写新 spec 前读本文件。`from figlib import *` 会带进 `Fig`、四个版式函数和坐标常量。
完整用例见 `assets/examples/six_edit_models.py`：六个函数覆盖了双流、单流、并行单流、LLM 解码层四种 block。

## 坐标常量

| 常量 | 默认 | 含义 |
| --- | --- | --- |
| `X0, W1` | 24, 470 | 左段起点和宽度 |
| `P2` | (550, 36, 470, 664) | 中段面板 (x, y, w, h) |
| `P3` | (1068, 96, 412, 604) | 右段面板 |
| `CAP_Y` | 712 | 三段底部说明的 y |

要改整体比例就在 spec 顶部 `import figlib; figlib.P3 = (...)`，版式函数读的是模块里的值。

## 通用参数

- 块的描述元组统一是 `(label, role, sub, hl)`：主文字、语义色（见 style.md 配色表）、副标题或 `None`、是否蓝框。
- `hl=True` 只给「这个模型独有的做法」，一张图通常 3–6 个，多了就不再是重点。

## overall —— 左段整体

```python
overall(f, lanes, seq_title, segs, blocks, tops, cap, cross=None, zoom_idx=-1)
```

- `lanes`：3–4 条输入路，每条 `dict(inp=..., enc=..., enc2=...)`，自下而上：输入 → 编码器 → 可选第二步。
  4 条时字号自动降 1px，文案要短（每行 ≤ 8 个汉字）。`enc2` 的 role 写 `"white"` 会画成灰色虚线框，
  用来表示「无调制」「可选」这类弱化步骤。
- `seq_title` / `segs`：各路汇成的一条序列。`segs` 每项 `(label, role, 权重, hl[, sub])`，权重决定段宽。
- `blocks`：自下而上的 block 列表 `(label, sub, hl)`，一个或两个（如「双流 × 19」「单流 × 38」）。
  `zoom_idx` 选哪个被放大到中段，默认最上面那个。
- `tops`：block 之上的若干行，每行一个或两个块。上一行一个、这一行两个时自动分叉（如 lm_head / UNetUp）。
- `cross=(from_lane, to_lane)`：从某条 lane 的输入画一条蓝色虚线到另一条 lane 的编码器（参考图也喂给 VLM）。

## single_block —— 中段单流 block

```python
single_block(f, items, bus_label=None, bus_keys=(), bus_labels=None, residuals=(), injects=(), cap="", note=None, w=236)
```

- `items`：自下而上，每项 `dict(label, role, h, key, sub=None, bold=False, hl=False, join=False)`；
  `dict(kind="plus", key=...)` 是 ⊕。`join=True` 表示紧贴上一块、不画箭头（Norm 与 Scale & Shift 这种成对的块）。
  高度自动撑满面板，不用算间距。
- `residuals=[(from_key, plus_key), ...]`：残差从哪块分出、进哪个 ⊕。
- `bus_label=(文字, hl)` + `bus_keys`：调制源和它喂给的块。没有 adaLN 的模型（LLM 解码层）不传。
- `injects=[(label, sub, target_key, hl), ...]`：右侧注入块。相邻两个目标都有注入时 sub 写 `None`，否则文字会叠。
- `note=(粗体, 细字)`：右上角批注，写「没有 shift」「无 adaLN」这类否定。

## parallel_block —— 中段并行单流 block（FLUX 系）

```python
parallel_block(f, in_label, fused, attn, mlp, cat, bus, top_note, cap)
```

LayerNorm → Scale & Shift →（可选融合 Linear）→ 注意力与 MLP 并排 → concat → 一个输出 Linear → Gate → ⊕。
`fused=None` 表示 QKV 和 MLP 输入是分开的 Linear（FLUX.1），给元组表示一个融合 Linear（FLUX.2）。

## dual_block —— 中段双流 block（MMDiT 系）

```python
dual_block(f, streams=("文本 token", "图像 token"), attn=(label, sub), ffn="FFN · GELU", mods=((txt, hl), (img, hl)), top_note="", cap="")
```

两列各自 Norm / 调制 / FFN，中间共用一个 Joint Attention；残差和调制总线都走外侧。返回各块 id，想加注释可以用。

## 右段：自由排版

右段没有固定模板，用 `Fig` 的基本元素拼：

| 方法 | 用途 |
| --- | --- |
| `f.panel(*P3, main=False)` | 次面板底框，先画 |
| `f.box(x, y, w, h, label, role, sub=, hl=, fs=, stroke=, dashed=, fill=)` | 块 |
| `f.text(x, y, w, h, text, fs=, color=, bold=, align=)` | 文字，`\n` 换行 |
| `f.seq(x, y, w, h, title, segs)` | 序列条，返回 `(容器 id, [段 id])` |
| `f.stack(cx, w, y_bottom, items, y_top=)` | 竖向堆叠并自动连箭头 |
| `f.up(a, b)` / `f.edge(src, tgt, sx=, sy=, ex=, ey=, pts=, start=, end=, dashed=)` | 连线；`sx/sy/ex/ey` 是 0–1 的出入点 |
| `f.plus(cx, cy)` | ⊕ |
| `src(f, "仓库 @ commit · 文件:行号")` / `caption(f, x, w, text)` | 出处行 / 段落说明 |

已经画过的右段类型，可以直接抄：逐 token 选调制（2511）、注意力 mask 矩阵（Qwen 2.1）、RoPE 坐标网格（Kontext）、
坐标表 + 共享调制（FLUX.2）、逐 token 时间步（Z-Image）、MoE 路由（HunyuanImage 3.0）。
