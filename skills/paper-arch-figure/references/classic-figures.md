# 经典网络图的画法

画经典结构或者照着论文原图重画时读本文件：先查这张图靠什么视觉元素表达，再用对应的原语拼。
「已实测」的在 `assets/examples/classic_figures.py` 里有完整函数，可以直接复制改；其余用同样的原语能拼，还没有现成示例。

## 覆盖表

| 结构 | 原图靠什么表达 | 用哪些原语 | 状态 |
| --- | --- | --- | --- |
| LoRA | 冻结的大矩形 W₀ + 两个梯形 A（降维）、B（升维）+ ⊕ | `box(state="frozen")`、`trap(narrow=, state="train")`、`plus` | 已实测 |
| Adapter / 瓶颈层 | 梯形降维 → 非线性 → 梯形升维 + 残差 | `trap`、`residual` | 同 LoRA 拼法 |
| VAE / 自编码器 | 横向沙漏（两个梯形）+ μ、σ 圆 + 重参数化 | `trap(narrow="right"/"left")`、`node`、`op` | 已实测 |
| LeNet / AlexNet / VGG | 错开叠放的特征图，边长 ∝ 空间尺寸 | `fmaps`；要画立体长方体用 `cuboid` | 已实测（LeNet） |
| U-Net | U 形，特征图条宽 ∝ 通道、高 ∝ 尺寸，横向跳连 | `box` 手排、`edge(dashed=True)`、图例 | 已实测 |
| ResNet 残差块 | 两层卷积 + 旁路 + ⊕ | `stack`、`residual` | 与现有 block 版式相同 |
| Transformer / DiT / LLM 层 | 竖直 block 栈 + 残差 + ⊕ | `single_block`、`dual_block`、`parallel_block` | 已实测（six_edit_models、free_layouts） |
| ViT | 图切成 patch 网格 → 展平 → token 序列 + [class] + 位置编码 | `grid`、`image`（放真图） | 已实测 |
| Swin | 窗口划分网格，移位后的窗口 | `grid(role_at=按窗口着色)` | 原语够用 |
| CLIP / 对比学习 | 两个编码器 + N×N 相似度矩阵，对角线是正样本 | `grid(label_at=)` | 已实测 |
| 注意力 mask / 注意力图 | 行 = query、列 = key 的矩阵 | `grid(role_at=)` | 已实测（Qwen 2.1 右段） |
| LSTM / GRU 单元 | 横向细胞状态线 + σ/tanh 门 + ×、+ 运算圆 | `op`、`box`、`edge(start=, end=)` | 已实测 |
| RNN / seq2seq 展开 | 一行重复的单元 + 横向隐状态 | `row` | 原语够用 |
| ControlNet | 锁定原网络 vs 可训练副本 + 零卷积 | `state`、`group` | 已实测 |
| MLP / 感知机 | 神经元圆 + 相邻层全连接 | `neurons` | 已实测 |
| GNN / 图 | 节点 + 边 | `node`、`edge(arrow=False)` | 原语够用 |
| GAN | 生成器、判别器两个块 + 真假样本 | `box`、`row` | 原语够用 |
| MoE | 路由 + 多个专家并排 + 加权求和 | `box`、`edge` | 已实测（HunyuanImage 3.0 右段） |
| Latent Diffusion / 多阶段 | 横向流水线 + 条件注入 + 放大 | `row`、`group`、`zoom(side="down")` | 已实测（free_layouts） |
| 扩散前向 / 反向链 | 一行从清晰到噪声的图 | `image` + `row` 式排列 | 原语够用，需要自备图片 |
| Mamba / SSM 块 | 两路分支 + σ 门 + ⊗ | `stack`、`op` | 原语够用 |

表外的结构先拆成「块 + 连线 + 这张图特有的一种视觉」，特有视觉多半能落到梯形、圆、格子、叠放方块、真图这几类之一。
都不合适时可以在 `figlib.Fig` 里加新原语，按 style.md 的风格规则写，并补一行到本表。

## 各原语的约定

- **梯形**：窄边 = 维度小的一侧。数据向上流时，降维画上窄下宽（`narrow="top"`），升维画上宽下窄（`narrow="bottom"`）；
  横向流时用 `left` / `right`。连线正常用 `sx/ex`，figlib 已经处理了 draw.io 旋转连接点的问题。
- **冻结 / 可训练**：`state="frozen"` 加 ❄️，`state="train"` 加 🔥。颜色仍按语义上色，不用颜色区分冻结和可训练；
  可训练部分如果正是这个方法的独有做法，再加 `hl=True` 蓝框。
- **运算圆**：⊕ 用 `plus`，其余逐元素运算（× σ tanh ©）用 `op`；字多时加大半径 `r`，字号自动缩。
- **变量圆**：μ、σ、z、hₜ 这类中间变量用 `node`，按语义上色；采样得到的关键变量可以加蓝框。
- **格子**：`grid` 的 `role_at` 决定每格颜色，返回 `None` 画空格；矩阵要写行列含义（「行 = query，列 = key」）。
- **特征图**：边长按真实空间尺寸等比缩放，叠几张示意通道数，底下写 `C@H×W`。
- **下标 / 上标**：任何文字里写 `x_{t-1}`、`ℝ^{d×d}` 会渲染成真正的下标 / 上标。Unicode 下标字符（ₜ₋₁）很多字体缺字，不要用。
