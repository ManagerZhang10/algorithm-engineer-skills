---
name: paper-arch-figure
description: 画论文 / 讲解用的神经网络架构图（DiT、MMDiT、FLUX 单流块、LLM 解码层、MoE 等）。版式是三段放大：左边整体数据流，中间拆开一个 block（Norm、调制、注意力、FFN、残差、时间步从哪进），右边放大这个模型独有的机制。先从源码取证并记行号，再用 Python spec 生成可编辑的 draw.io，导出 SVG / PNG，按最终显示宽度自查字号。用户说「画模型架构图」「画论文结构图」「把 block 内部画出来」「重画这张架构图」「用 draw.io 画模型结构」时用。不用于系统 / 基础设施 / 数据流水线架构图（那是 archify 或 drawio-skill），也不用于数据图表。
---

# 论文风模型架构图

一张好的模型架构图回答三个问题：**条件从哪进、一层里面发生什么、这个模型和别家哪里不一样**。
所以固定画三段：左「整体」、中「一个 block」、右「独有做法」。
每个块都要能指到源码行。块的位置交给 `figlib` 算，你负责内容取舍和最后看图。

效果参考：`assets/examples/q2511_paper.png`（双流 MMDiT）、`assets/examples/hy3_paper.png`（MoE 大语言模型）。

## 一条命令

```bash
archfig build my_models.py --palette paper --fit-width 1664 --gallery
```

- `archfig` 是 `scripts/archfig.py`，通常软链在 `~/.local/bin/`；没有软链就用 `python3 <本技能>/scripts/archfig.py`。
- 依赖：Python ≥ 3.9（只用标准库），draw.io 桌面版（导出用；`archfig doctor` 检查）。
- 产物在 spec 同级的 `figs/`：每张图一个 `.drawio`（可在 diagrams.net 里继续拖改）、`.svg`、`.png`，
  `--gallery` 另出 `index.html` 逐张看、切配色。
- `archfig new my_models.py` 生成一个能直接跑的最小 spec。

## 工作流

1. **定范围**：画哪几个模型，最终放在哪里（论文、16:9 deck、竖屏图文）。显示宽度决定 `--fit-width`，也决定要不要拆页。
2. **取证**：按 `references/fact-sourcing.md` 从源码拿整体路径、一个 block 的执行顺序、独有机制和配置数字，每条带 `文件:行号`。
   多个模型时每个 subagent 负责一到两个，并行跑，模板在该文件里。查不到的写 not found，不画进图。
3. **写 spec**：`archfig new`，然后照 `assets/examples/six_edit_models.py` 里结构最接近的函数改。
   API 和参数含义见 `references/layouts.md`。三段各画什么：
   - 左段：保留输入 lane 和汇成的那条序列，序列里标出条件和目标的顺序；block 只写种类、层数、宽度。
   - 中段：画数量最多的那种 block。调制总线画出 t 进入的每一处；没有 adaLN 就在右上角写明「无 adaLN」。
   - 右段：只放一个机制，画成能看懂规则的样子（mask 矩阵、坐标表、路由图），不要写成一段文字。底部写出处行号。
   - 蓝框只给独有做法，一张图 3–6 个。
4. **导出并量字号**：`archfig build ... --fit-width <显示宽度>`。输出里标「偏小」的，先想版式（拆页、全宽），再考虑删字。
5. **看图**：打开 PNG 逐项查。常见问题和改法：
   - 箭头穿过文字：改出入点（`sx/ex`）或把标签放进块的 `sub`，不要把文字放在箭头路径上。
   - 文字溢出块：缩短文案；4 条 lane 时每行不超过 8 个汉字。
   - 注入块的说明叠在一起：相邻两个注入只留一个说明。
   - 中段上方空一大块：`stack(..., y_top=)` 会自动撑满，手排的部分检查是否漏传。

   自动修改最多两轮，还不对就把问题列给用户。
6. **交付**：给出 `.drawio` 和 SVG / PNG 路径，说明用了哪种配色、哪些字号偏小、出处 commit。

## 配色

- 默认 `paper`：五色语义（灰 IO、蓝 Norm 与注入、紫 时间步与调制、橙 注意力、绿 FFN），block 内部一眼分层。
- `deck`：全灰块 + 单一强调蓝，只在整套材料必须严格单色时用。`--palette both` 两版都出，方便对比。
- 两套都遵守「蓝框 = 独有做法」。颜色、字体都是 `figlib.PALETTES` / `figlib.FONT` 里的可替换默认值，细则见 `references/style.md`。

## 放进 slide 的字号

三段图约 1460 × 740。放进 1920×1080 slide 时正文最多约 15px，放进左图右注释的版式只有约 9.5px。
所以要么**拆两页**（整体 + block 一页，独有做法一页），要么全宽放图、注释挪进讲稿。不要缩进小框里凑版式。

## 什么时候读哪个参考

| 文件 | 读的时机 |
| --- | --- |
| `references/fact-sourcing.md` | 每次画新模型之前 |
| `references/layouts.md` | 写或改 spec 时 |
| `references/style.md` | 改配色、加新元素、或脱离 figlib 手写 XML 时 |
| `assets/examples/six_edit_models.py` | 找最接近的现成写法 |

## 已知的坑

- draw.io 导出的 SVG 会给每个文字块塞 PNG 兜底图，还用 `light-dark()` 让暗色系统变黑底。`archfig` 导出后会自动清掉并锁成浅色，别跳过它直接用 draw.io 导出。
- draw.io 的 `value` 属性里的 HTML 要转义，否则整张图导出空白；用 `figlib` 不会遇到，手写 XML 时注意。
- 已有的 `.drawio` 在 diagrams.net 里手改过之后，不要再用 spec 重新生成覆盖。要改就另存新文件名。
