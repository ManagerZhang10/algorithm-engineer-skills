---
name: paper-arch-figure
description: 画论文 / 讲解用的神经网络架构图，任意结构都行（DiT、MMDiT、LLM 解码层、MoE、编码器-解码器、U-Net、多阶段流水线、只有三个模块的小图）。固定的是统一风格：五色语义配色、圆角无描边块、单一方向的主干、虚线放大、蓝框标独有做法；版式由 Agent 按结构自己定，三段放大（整体 / 一个 block / 独有机制）只是现成模板之一。先从源码取证并记行号，再用 Python spec 生成可编辑的 draw.io，导出 SVG / PNG，按最终显示宽度自查字号。用户说「画模型架构图」「画论文结构图」「把 block 内部画出来」「重画这张架构图」「用 draw.io 画模型结构」时用。不用于系统 / 基础设施 / 数据流水线架构图（那是 archify 或 drawio-skill），也不用于数据图表。
---

# 论文风模型架构图

这个技能固定的是**风格**，不是版式：同一套五色语义、块和连线的画法、字号底线，让不同结构的图放在一起像一套。
画成几段、怎么排、放大哪里，都由你按这个模型的结构来定。每个块都要能指到源码行。

效果参考：`assets/examples/` 里的四张 PNG，三段放大有 `q2511_paper.png`（双流 MMDiT）和 `hy3_paper.png`（MoE LLM），
两段有 `transformer_paper.png`（编码器-解码器），横向流水线加向下放大有 `ldm_paper.png`，
梯形加冻结 / 可训练标记有 `lora_paper.png`。

## 一条命令

```bash
archfig build my_models.py --palette paper --fit-width 1664 --gallery
```

- `archfig` 是 `scripts/archfig.py`，通常软链在 `~/.local/bin/`；没有软链就用 `python3 <本技能>/scripts/archfig.py`。
- 依赖：Python ≥ 3.9（只用标准库），draw.io 桌面版（导出用；`archfig doctor` 检查）。
- 产物在 spec 同级的 `figs/`：每张图一个 `.drawio`（可在 diagrams.net 里继续拖改）、`.svg`、`.png`，
  `--gallery` 另出 `index.html` 逐张看、切配色。画布大小由内容决定，不用预设。
- `archfig new my_models.py` 生成一个能直接跑的最小 spec（三段模板，按需删改）。

## 先定版式

一张好的架构图回答：**数据怎么流、关键单元里面发生什么、这个模型和别家哪里不一样**。
哪一问最重要，就决定画成什么样。常见结构对应的版式：

| 结构 | 版式 | 用什么 |
| --- | --- | --- |
| 同构 block 堆叠（DiT / MMDiT / LLM），独有做法是一条规则（mask、坐标、路由） | 三段放大：整体 → 一个 block → 独有机制 | `overall` + `*_block` + 右段自由排 |
| 同上，但独有做法就在 block 里 | 两段：整体 → 一个 block | 整体用 `overall` 或 `stack`，block 用 `*_block(rect=)` |
| 多个模块串起来（VAE + 扩散 + 解码、两阶段、检索 + 生成） | 单画布横向流水线，关键模块再放大 | `row` + `group`，`zoom(side="down")` |
| 编码器-解码器、双塔 | 两列并排，列间横向连 | 两次 `stack` + `right` |
| U-Net / 多尺度金字塔 | U 形或分层，跳连走外侧 | `group` 分层，原语手排 |
| 训练和推理路径不同 | 上下两栏对照，同一模块对齐 | 两个 `group` |
| 只有三五个模块 | 一行或一列，不加面板 | `row` / `stack` |
| 经典结构（LoRA、VAE、CNN、U-Net、ViT、CLIP、LSTM、ControlNet…） | 沿用原论文图的视觉习惯 | 查 `references/classic-figures.md` |
| 多个模型对比 | 每个模型一张、版式相同 | 同一个函数换参数 |

表外的结构直接用原语自由排，只要守住 `references/style.md` 的风格规则。
版式定下来后在交付时一句话说明为什么这么排。

## 工作流

1. **定范围**：画哪几个模型，最终放在哪里（论文、16:9 deck、竖屏图文）。显示宽度决定 `--fit-width`，也决定要不要拆页。
2. **取证**：按 `references/fact-sourcing.md` 从源码拿整体路径、关键单元的执行顺序、独有机制和配置数字，每条带 `文件:行号`。
   多个模型时每个 subagent 负责一到两个，并行跑，模板在该文件里。查不到的写 not found，不画进图。
3. **定版式**：按上面的表选，拿不准时先画整体数据流，再看哪个单元值得放大。
4. **写 spec**：API 见 `references/layouts.md`。从 `assets/examples/` 里结构最接近的函数改起：
   三段放大看 `six_edit_models.py`，两段和流水线看 `free_layouts.py`，经典结构看 `classic_figures.py`。
   - 整体：保留输入怎么汇合、主干经过哪些模块；重复的 block 只写种类、层数、宽度。
   - 放大的单元：画数量最多或最关键的那个。有调制就画出 t 进入的每一处；没有就写明「无 adaLN」这类否定。
   - 独有机制：画成能看懂规则的样子（mask 矩阵、坐标表、路由图、公式拆成块），不要写成一段文字。附近写出处行号。
   - 蓝框只给独有做法，一张图 3–6 个。
5. **导出并量字号**：`archfig build ... --fit-width <显示宽度>`。输出里标「偏小」的，先想版式（拆页、全宽），再考虑删字。
6. **看图**：打开 PNG 逐项查。常见问题和改法：
   - 箭头穿过文字：改出入点（`sx/ex`）或把标签放进块的 `sub`，不要把文字放在箭头路径上。
   - 文字溢出块：缩短文案或加宽块；4 条 lane 时每行不超过 8 个汉字。
   - 文字压住块：手排的标题、说明和下方第一个块之间留够距离。
   - 注入块的说明叠在一起：相邻两个注入只留一个说明。
   - 面板里上方空一大块：`stack(..., y_top=)` 会自动撑满，手排的部分检查是否漏传。
   - 放大虚线穿过别的块：换 `zoom` 的 `side`，或挪面板。

   自动修改最多两轮，还不对就把问题列给用户。
7. **交付**：给出 `.drawio` 和 SVG / PNG 路径，说明选了什么版式、用了哪种配色、哪些字号偏小、出处 commit。

## 配色

- 默认 `paper`：五色语义（灰 IO、蓝 Norm 与注入、紫 时间步 / 条件 / 调制、橙 注意力、绿 FFN），和版式无关，任何结构都按语义上色。
  非 Transformer 的模块怎么归类见 `references/style.md`。
- `deck`：全灰块 + 单一强调蓝，只在整套材料必须严格单色时用。`--palette both` 两版都出，方便对比。
- 两套都遵守「蓝框 = 独有做法」。颜色、字体都是 `figlib.PALETTES` / `figlib.FONT` 里的可替换默认值。

## 放进 slide 的字号

图越宽，缩进 slide 后字越小。三段图约 1460 × 740，放进 1920×1080 slide 时正文最多约 15px，放进左图右注释的版式只有约 9.5px。
所以宽图要么**拆页**（整体一页，放大一页），要么全宽放图、注释挪进讲稿。不要缩进小框里凑版式。

## 什么时候读哪个参考

| 文件 | 读的时机 |
| --- | --- |
| `references/fact-sourcing.md` | 每次画新模型之前 |
| `references/layouts.md` | 写或改 spec 时 |
| `references/classic-figures.md` | 画经典结构、照论文原图重画、需要梯形 / 格子 / 特征图 / 运算圆这类特殊形状时 |
| `references/style.md` | 自由排版时（风格规则都在这里）、改配色、脱离 figlib 手写 XML 时 |
| `assets/examples/*.py` | 找最接近的现成写法 |

## 已知的坑

- draw.io 导出的 SVG 会给每个文字块塞 PNG 兜底图，还用 `light-dark()` 让暗色系统变黑底。`archfig` 导出后会自动清掉并锁成浅色，别跳过它直接用 draw.io 导出。
- draw.io 的 `value` 属性里的 HTML 要转义，否则整张图导出空白；用 `figlib` 不会遇到，手写 XML 时注意。
- draw.io 按画的先后决定上下层：`panel` 要先画，否则底色会盖住里面的块。
- 已有的 `.drawio` 在 diagrams.net 里手改过之后，不要再用 spec 重新生成覆盖。要改就另存新文件名。
