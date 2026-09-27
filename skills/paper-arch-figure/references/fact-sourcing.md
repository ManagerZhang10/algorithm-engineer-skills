# 源码取证

一张架构图的每个块都要能指到代码行。画之前先取证，取证结果就是 spec 的输入。

## 来源优先级

1. 模型实现源码（官方仓库或 diffusers / transformers 里的实现），**记下 commit**。
2. 配置文件里的默认值和已发布 checkpoint 的 config.json（两者可能不同，要分开写）。
3. 技术报告和论文原图。只用来确认意图，不覆盖源码。

不从类名推拓扑：注册了的模块不一定被执行，同一个模块也可能被复用多次。以 forward 实际走的路径为准。

## 要拿到的东西

- **整体**：各路输入的 embedder 和维度；时间步 / guidance / 池化向量怎么合成调制输入；条件 token 用什么时间步；
  位置编码的类型和坐标怎么构造；block 数量和种类；输出头；最后返回哪些 token。
- **一个 block**：按执行顺序列出每一步 —— Norm 类型、调制有几组系数（shift / scale / gate 各有没有）、
  调制权重是每层自己的还是全网共享、注意力（QK-Norm、RoPE 在 Norm 之前还是之后、mask）、FFN 类型和隐藏维度、残差怎么加。
- **独有机制**：这个模型和同类最不一样的一处，要具体到张量怎么构造（索引、mask 规则、坐标值）。
- **配置数字**：层数、头数、head dim、宽度、输入通道。

## 多个模型时并行取证

每个 subagent 负责一到两个模型，只读源码，按下面的模板要结构化报告：

```text
Read-only research. Source: <repo path> (commit <sha>), files <file list>.

I need to draw a paper-style architecture diagram (overall model → one transformer block zoomed in →
one unique mechanism zoomed in) for <model>. Report, citing file:line for every claim:

1. Overall forward path: input projections and dims, timestep/condition embedding and how it becomes
   modulation (and what timestep condition tokens get), positional encoding type and coordinate layout,
   number and kinds of blocks, final norm / projection, which tokens are returned.
2. ONE block as an ordered list of ops per stream: norm type, modulation chunks (which of shift/scale/gate,
   per-block or shared), attention (QK norm, where RoPE is applied, mask), gated residuals, FFN type and
   hidden size.
3. The unique mechanism: exact construction rules (indices, masks, coordinate values).
4. Config numbers from __init__ defaults; note if released checkpoints differ.

Output a compact structured report (bullets), under ~900 words. Do not guess; mark anything not found
as "not found".
```

## 把取证结果落到图上

- 右段底部的出处行写 `仓库 @ commit · 文件:行号`，行号挑最关键的 2–4 处。
- 报告里标 not found 的内容不画进图；确实需要就在图上写「未核实」。
- 发现和已有材料（deck、文章）说法冲突时，停下来告诉用户，不要静默改成任何一边。
