# figlib 版式 API

写新 spec 前读本文件。`from figlib import *` 会带进 `Fig`、原语、现成版式函数和三段模板的坐标常量。

分两层：**原语**负责风格（颜色、圆角、箭头、字号都已按 style.md 实现），能拼出任意结构；
**现成版式**是用原语拼好的常用组合，可以放在画布任意位置，也可以完全不用。

完整用例：`assets/examples/six_edit_models.py`（三段放大，覆盖双流、单流、并行单流、LLM 解码层四种 block）、
`assets/examples/free_layouts.py`（两段的编码器-解码器、横向流水线 + 向下放大）、
`assets/examples/classic_figures.py`（LoRA、VAE、LeNet、U-Net、ViT、CLIP、LSTM、ControlNet、MLP 九张经典图）。
经典结构该用哪个原语见 `references/classic-figures.md`。

## 原语（任意版式都用这些）

坐标都是画布绝对像素，y 向下增大。画布大小由内容决定，不用预设。

| 方法 | 用途 |
| --- | --- |
| `f.box(x, y, w, h, label, role, sub=, hl=, bold=, fs=, stroke=, dashed=, fill=, state=)` | 块，返回 id；`state="frozen"/"train"` 加 ❄️ / 🔥 |
| `f.text(x, y, w, h, text, fs=, color=, bold=, align=)` | 文字，`\n` 换行 |
| `f.plus(cx, cy)` / `f.op(cx, cy, sym, r=11)` | ⊕ / 其他逐元素运算圆（× σ tanh ©） |
| `f.node(cx, cy, r, label, role)` | 填色圆：变量（μ、σ、z）、神经元、图节点 |
| `f.trap(x, y, w, h, label, role, narrow="top", ratio=0.3)` | 梯形，窄边 = 维度小的一侧（LoRA 的 A/B、Adapter、自编码器） |
| `f.fmaps(x, y, w, h, n=3, off=6, role, below=)` | 一叠错开的特征图（CNN），返回最前一张 |
| `f.cuboid(x, y, w, h, depth=14, role=, below=)` | 立体长方体特征图 |
| `f.grid(x, y, rows, cols, cs, role_at, hl_at=, label_at=)` | 格子矩阵（注意力 / mask / 相似度、patch 网格），返回 `ids[r][c]` |
| `f.neurons(x, cy, layers, dx=, dy=, r=, roles=)` | 神经元全连接示意，`layers=[3, 5, 2]` |
| `f.image(x, y, w, h, path)` | 嵌入真图（PNG / JPEG），写进 .drawio，SVG 导出保留 |
| `f.stack(cx, w, y_bottom, items, gap=, y_top=)` | 竖向自下而上堆叠并自动连箭头；给 `y_top` 会自动撑满 |
| `f.row(x_left, cy, items, gap=28, h=44)` | 横向自左向右排一行并自动连箭头；每项可带 `w`（默认 120） |
| `f.group(x, y, w, h, title, dashed=True)` | 带标题的分组虚线框（编码器 / 一个 stage / 训练 vs 推理） |
| `f.panel(x, y, w, h, main=True)` | 放大面板底框：`main=True` 黑边主面板，`False` 灰边次面板。先画 |
| `f.seq(x, y, w, h, title, segs)` | 序列条，返回 `(容器 id, [段 id])` |
| `f.up(a, b)` / `f.right(a, b)` | a 下 b 上竖直连 / a 左 b 右水平连 |
| `f.edge(src, tgt, sx=, sy=, ex=, ey=, pts=, start=, end=, dashed=, color=)` | 任意连线；`sx/sy/ex/ey` 是 0–1 的出入点，`pts` 是折点 |
| `f.residual(from_id, plus_id, x_side)` | 残差：从块顶上方分出，沿 `x_side` 上行进 ⊕ |
| `f.bus(src_id, targets, x_bus, labels=)` | 调制总线：灰线从调制源上行，逐个水平进入目标 |
| `f.inject(src_id, tgt_id, side=)` | 侧向注入 |
| `f.zoom(box_id, rect, side="right")` | 放大虚线；`side` 取 `right` / `left` / `down` / `up`，面板在块的哪一侧 |
| `caption(f, x, w, text, y=)` | 段落底部 15px 说明；`y` 默认三段模板的 `CAP_Y`，自由版式传面板底边 + 12 |
| `src(f, "仓库 @ commit · 文件:行号", rect=)` | 出处行，贴在 `rect` 底部（默认右段 `P3`） |

所有文字（label、sub、text）里 `x_{t-1}` 渲染成下标、`ℝ^{d×d}` 渲染成上标；不带花括号的 `_` `^` 原样显示。

`stack` / `row` 的 item 统一是 `dict(label, role, sub=None, h, w, key, bold=False, hl=False, join=False, fs=, stroke=, dashed=)`，
`dict(kind="plus", key=...)` 是 ⊕。`join=True` 表示紧贴上一块、不画箭头。返回 `{key: id}`。

大 block 框（「Encoder 层 × 6」这类）写 `role="white", stroke="#222222", bold=True`。

## 现成版式

四个函数都能放到任意位置；不传位置参数时落在三段模板的默认坐标上。

### overall —— 多路输入汇成一条序列的整体图

```python
overall(f, lanes, seq_title, segs, blocks, tops, cap, cross=None, zoom_idx=-1,
        x0=None, w=None, dy=0, zoom_to=None, zoom_side="right")
```

适合「几路输入各自编码 → 拼成一条序列 → 堆叠 block → 输出头」。输入结构不是这样（编码器-解码器、多阶段）就别硬套，用 `stack` / `row` 手排。

- `lanes`：3–4 条输入路，每条 `dict(inp=..., enc=..., enc2=...)`，自下而上：输入 → 编码器 → 可选第二步。
  4 条时字号自动降 1px，文案要短（每行 ≤ 8 个汉字）。`enc2` 的 role 写 `"white"` 会画成灰色虚线框，表示「无调制」「可选」这类弱化步骤。
- `seq_title` / `segs`：各路汇成的一条序列。`segs` 每项 `(label, role, 权重, hl[, sub])`，权重决定段宽。
- `blocks`：自下而上的 block 列表 `(label, sub, hl)`，一个或两个。`zoom_idx` 选哪个被放大。
- `tops`：block 之上的若干行，每行一个或两个块。上一行一个、这一行两个时自动分叉。
- `cross=(from_lane, to_lane)`：从某条 lane 的输入画蓝色虚线到另一条 lane 的编码器。
- 位置：`x0` / `w` 改起点和宽度，`dy` 整段上下平移（整段约 690px 高）。`zoom_to` 是放大面板的 rect，默认 `P2`；`False` 不画放大线。

### single_block / parallel_block / dual_block —— 一个 block 的内部

三个函数都接受 `rect=(x, y, w, h)`，整块面板（含底部说明）画在这里；默认中段 `P2`。

```python
single_block(f, items, bus_label=None, bus_keys=(), bus_labels=None, residuals=(), injects=(),
             cap="", note=None, w=236, rect=None)
parallel_block(f, in_label, fused, attn, mlp, cat, bus, top_note, cap, rect=None)
dual_block(f, streams=(...), attn=(label, sub), ffn=..., mods=((txt, hl), (img, hl)), top_note="", cap="", rect=None)
```

- **single_block**：单流。`items` 同 `stack`，高度自动撑满面板。
  `residuals=[(from_key, plus_key), ...]`；`bus_label=(文字, hl)` + `bus_keys` 画调制总线，没有 adaLN 就不传；
  `injects=[(label, sub, target_key, hl), ...]` 是右侧注入块，相邻两个目标都有注入时 sub 写 `None`；
  `note=(粗体, 细字)` 是右上角批注（「无 adaLN」「Post-LN」）。面板窄时把 `w` 调小给注入块留地方。
  Pre-LN、Post-LN、带不带门控都能表达，按取证的执行顺序排 items 即可。
- **parallel_block**：FLUX 系并行单流。LayerNorm → Scale & Shift →（可选融合 Linear）→ 注意力与 MLP 并排 → concat → Linear → Gate → ⊕。
  `fused=None` 表示 QKV 和 MLP 输入是分开的 Linear。
- **dual_block**：MMDiT 系双流。两列各自 Norm / 调制 / FFN，中间共用 Joint Attention；返回各块 id。

## 三段放大模板

三段放大 = `overall`（左）+ 一个 `*_block`（中）+ 右段自由排的独有机制，画布约 1460 × 740。
不传位置参数时用下面的默认坐标：

| 常量 | 默认 | 含义 |
| --- | --- | --- |
| `X0, W1` | 24, 470 | 左段起点和宽度 |
| `P2` | (550, 36, 470, 664) | 中段面板 (x, y, w, h) |
| `P3` | (1068, 96, 412, 604) | 右段面板 |
| `CAP_Y` | 712 | 三段底部说明的 y |

要改整体比例就在 spec 顶部 `import figlib; figlib.P3 = (...)`，版式函数读的是模块里的值。

右段没有固定模板：`f.panel(*P3, main=False)` 打底，再用原语拼。已经画过的右段类型可以直接抄：
逐 token 选调制（2511）、注意力 mask 矩阵（Qwen 2.1）、RoPE 坐标网格（Kontext）、坐标表 + 共享调制（FLUX.2）、
逐 token 时间步（Z-Image）、MoE 路由（HunyuanImage 3.0）、交叉注意力拆成 Q/K/V（LDM，在 free_layouts.py）。

## 自由排版的做法

1. 先在纸面上定主干方向（竖直向上或横向向右，一张图只用一个主方向）和放大关系。
2. 从主干开始用 `stack` / `row` 排，拿到 id 后再补跨列连线、分组框、放大面板。
3. 面板和分组框的位置先粗定，出图后按 PNG 微调坐标。标题文字和下方第一个块之间至少留 12px。
4. 每个面板底部一行 `caption`，出处用 `src` 或一行 9.5px 灰字。
