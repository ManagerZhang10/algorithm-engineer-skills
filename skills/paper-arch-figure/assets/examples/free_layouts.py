"""示例 spec：不走三段模板的两种版式。

用法：archfig build free_layouts.py --out figs/
事实出处：两篇原论文（每张图底部写了章节）。这里只画论文层面的结构，没有对到源码行号；
画真实模型时仍按 references/fact-sourcing.md 从源码取证。

- transformer：两段（整体 + 一个 block）。输入不是「几路 lane 汇成一条序列」，overall 不合适，
  整体用 stack 手排两列；block 复用 single_block(rect=...)。
- ldm：单画布横向流水线 + 向下放大。主角是模块之间怎么接，不是一个 block 的内部，
  用 row / group 排主干，再把条件注入那一处放大到下方面板。
"""
from figlib import *  # noqa: F401,F403


# ================================================================ 1. Transformer（编码器-解码器）
def transformer(pal):
    f = Fig(pal)
    big = dict(role="white", h=80, bold=True, stroke="#222222", fs=15)
    enc = f.stack(140, 200, 696, [
        dict(label="输入 token", role="io", h=40, key="in"),
        dict(label="Embedding + 位置编码", role="inject", h=44, key="emb", sub="正弦 · d_model 512"),
        dict(label="Encoder 层 × 6", sub="自注意力 → FFN", key="blk", **big),
    ], gap=30)
    dec = f.stack(380, 200, 696, [
        dict(label="输出 token（右移一位）", role="io", h=40, key="in"),
        dict(label="Embedding + 位置编码", role="inject", h=44, key="emb", sub="与输入共享权重"),
        dict(label="Decoder 层 × 6", sub="掩码自注意力 → 交叉 → FFN", key="blk", **big),
        dict(label="Linear", role="ffn", h=34, key="lin"),
        dict(label="Softmax → 下一个 token", role="io", h=34, key="sm"),
    ], gap=30)
    f.right(enc["blk"], dec["blk"])
    f.text(240, 490, 40, 18, "K, V", fs=11)
    caption(f, X0, W1, "Transformer：编码器-解码器")
    f.text(X0, 740, W1, 18, "出处：Vaswani et al. 2017 · §3.1–3.3、图 1", fs=9.5, color="#9A9A9A")

    rect = (550, 36, 470, 664)
    f.zoom(dec["blk"], rect)
    single_block(
        f,
        [dict(label="解码器 hidden (B, T, 512)", role="io", h=28, key="in"),
         dict(label="掩码多头自注意力", role="core", h=40, key="msa", bold=True, sub="8 头"),
         dict(kind="plus", key="p1"),
         dict(label="LayerNorm", role="norm", h=26, key="n1"),
         dict(label="交叉注意力", role="core", h=40, key="ca", bold=True, sub="Q 来自解码器", hl=True),
         dict(kind="plus", key="p2"),
         dict(label="LayerNorm", role="norm", h=26, key="n2"),
         dict(label="FFN · ReLU", role="ffn", h=34, key="ff", sub="512 → 2048 → 512"),
         dict(kind="plus", key="p3"),
         dict(label="LayerNorm", role="norm", h=26, key="n3"),
         dict(label="下一层", role="io", h=26, key="out")],
        residuals=[("in", "p1"), ("n1", "p2"), ("n2", "p3")],
        injects=[("因果 mask", "只看左侧 token", "msa", True),
                 ("编码器 K, V", "6 层读同一份", "ca", True)],
        note=("Post-LN", "Norm 在残差相加之后"),
        w=200, rect=rect, cap="Decoder 层（× 6）")
    return f


# ================================================================ 2. Latent Diffusion
def ldm(pal):
    f = Fig(pal)
    # 条件（上）
    f.group(360, 20, 390, 100, "条件")
    c = f.row(382, 76, [
        dict(label="条件 y", sub="文本 / 语义图 / 图像", w=150, key="y"),
        dict(label="领域编码器 τ_θ", role="cond", w=170, key="tau"),
    ], gap=28, h=48)
    # 主干（中）
    f.group(280, 150, 572, 120, "潜空间（空间下采样 f 倍）")
    m = f.row(40, 214, [
        dict(label="图像 x", w=84, key="x"),
        dict(label="编码器 ℰ", w=110, key="E", hl=True),
        dict(label="潜变量 z", w=84, key="z"),
        dict(label="前向加噪", role="cond", sub="→ z_T", w=130, key="noise"),
        dict(label="去噪 U-Net ε_θ", role="white", sub="重复 T 步", w=170, h=56, bold=True, stroke="#222222", key="unet"),
        dict(label="去噪后 z", w=84, key="z0"),
        dict(label="解码器 𝒟", w=110, key="D", hl=True),
        dict(label="生成图", w=84, key="xt"),
    ])
    f.edge(c["tau"], m["unet"], sx=.5, sy=1, ex=.5, ey=0)
    f.text(652, 124, 120, 18, "交叉注意力", fs=11, align="left")
    # 放大：条件怎么进 U-Net（下）
    px, py, pw, ph = rect = (330, 330, 630, 330)
    f.zoom(m["unet"], rect, side="down")
    f.panel(*rect, main=False)
    f.text(px + 16, py + 10, pw - 32, 24, "交叉注意力：条件从 K、V 进 U-Net", fs=14, color=f.P["text"], bold=True, align="left")
    f.text(px + 16, py + 34, pw - 32, 18, "语义图、低分辨率图这类空间对齐的条件改用通道拼接", fs=10.5, align="left")
    phi = f.box(px + 30, py + 256, 200, 36, "U-Net 中间特征 φ_i(z_t)", "io", fs=12)
    ty = f.box(px + 310, py + 256, 280, 36, "τ_θ(y)", "cond", fs=12)
    q = f.box(px + 30, py + 188, 200, 36, "Q = W_Q · φ_i(z_t)", "attn", fs=12)
    k = f.box(px + 310, py + 188, 130, 36, "K = W_K · τ_θ(y)", "attn", fs=11.5, hl=True)
    v = f.box(px + 460, py + 188, 130, 36, "V = W_V · τ_θ(y)", "attn", fs=11.5, hl=True)
    a = f.box(px + 70, py + 114, 490, 44, "softmax(Q·Kᵀ / √d) · V", "core", bold=True, fs=13)
    o = f.box(px + 225, py + 66, 180, 26, "回到 U-Net", "io", fs=12)
    f.up(phi, q)
    f.vline(ty, k)
    f.vline(ty, v)
    f.vline(q, a)
    f.vline(k, a)
    f.vline(v, a)
    f.up(a, o)
    src(f, "出处：Rombach et al. 2022 · §3.1–3.3、图 3", rect)
    caption(f, px, pw, "独有做法：在潜空间扩散，条件经交叉注意力注入", y=py + ph + 12)
    return f


FIGURES = [("transformer", "Transformer", transformer), ("ldm", "Latent Diffusion", ldm)]
