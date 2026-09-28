"""示例 spec：经典网络结构的论文示意图，用来验证原语能覆盖常见画法。

用法：archfig build classic_figures.py --out figs/ --gallery
事实出处：各自的原论文（每张图底部写了章节或图号），只画论文层面的结构，没有对到源码行号。
每张图用到的特殊原语写在函数的 docstring 里。
"""
from figlib import *  # noqa: F401,F403


def foot(f, x, w, y, cap, source):
    caption(f, x, w, cap, y=y)
    f.text(x, y + 28, w, 18, source, fs=9.5, color="#9A9A9A")


# ================================================================ LoRA
def lora(pal):
    """梯形 trap（降维 A、升维 B）+ 冻结 / 可训练标记 state。"""
    f = Fig(pal)
    x = f.box(200, 384, 120, 32, "x ∈ ℝ^{d}", "io")
    w0 = f.box(50, 200, 180, 120, "预训练权重 W_{0}", "ffn", sub="W_{0} ∈ ℝ^{d×d}", state="frozen")
    a = f.trap(290, 262, 170, 58, "A", "ffn", narrow="top", sub="d → r · 高斯初始化", state="train", hl=True)
    b = f.trap(290, 180, 170, 58, "B", "ffn", narrow="bottom", sub="r → d · 零初始化", state="train", hl=True)
    f.text(462, 232, 60, 18, "r ≪ d", fs=11, align="left")
    f.up(a, b)
    p = f.plus(260, 130)
    f.edge(w0, p, sx=.5, sy=0, ex=0, ey=.5, pts=[(140, 130)])
    f.edge(b, p, sx=.5, sy=0, ex=1, ey=.5, pts=[(375, 130)])
    f.text(384, 150, 120, 18, "BAx 乘 α / r", fs=10.5, align="left")
    h = f.box(170, 56, 180, 34, "h = W_{0}x + BAx", "io")
    f.up(p, h)
    f.edge(x, w0, sx=.3, sy=0, ex=.5, ey=1, pts=[(236, 352), (140, 352)])
    f.edge(x, a, sx=.7, sy=0, ex=.5, ey=1, pts=[(284, 352), (375, 352)])
    foot(f, 20, 500, 432, "LoRA：冻结 W_{0}，只训练低秩的 B·A", "出处：Hu et al. 2021 · 图 1、§4.1")
    return f


# ================================================================ VAE
def vae(pal):
    """横向沙漏：两个梯形 + 圆形变量 node + 运算节点 op。"""
    f = Fig(pal)
    cy = 150
    x = f.box(20, cy - 24, 70, 48, "x", "io")
    enc = f.trap(110, cy - 60, 140, 120, "编码器", "io", narrow="right", sub="q_{φ}(z | x)")
    mu = f.node(300, cy - 40, 20, "μ", "cond")
    sg = f.node(300, cy + 40, 20, "σ", "cond")
    mul = f.op(380, cy + 40, "×")
    eps = f.box(335, cy + 78, 90, 30, "ε ~ 𝒩(0, I)", "cond", hl=True, fs=12)
    add = f.op(450, cy, "+")
    z = f.node(520, cy, 22, "z", "io", hl=True)
    dec = f.trap(580, cy - 60, 140, 120, "解码器", "io", narrow="left", sub="p_{θ}(x | z)")
    xr = f.box(740, cy - 24, 80, 48, "重建 x′", "io")
    f.right(x, enc)
    f.edge(enc, mu, sx=1, sy=.42, ex=0, ey=.5, pts=[(265, cy - 10), (265, cy - 40)])
    f.edge(enc, sg, sx=1, sy=.58, ex=0, ey=.5, pts=[(265, cy + 10), (265, cy + 40)])
    f.right(sg, mul)
    f.up(eps, mul)
    f.edge(mu, add, sx=1, sy=.5, ex=.5, ey=0, pts=[(450, cy - 40)])
    f.edge(mul, add, sx=1, sy=.5, ex=.5, ey=1, pts=[(450, cy + 40)])
    f.right(add, z)
    f.right(z, dec)
    f.right(dec, xr)
    f.text(470, cy + 58, 200, 34, "重参数化：z = μ + σ ⊙ ε\n采样变成可求导", fs=11, align="left")
    f.text(20, 282, 800, 18, "损失 = 重建误差 + KL( q_{φ}(z | x) ‖ 𝒩(0, I) )", fs=11.5, color=f.P["text"])
    foot(f, 20, 800, 312, "VAE：编码成分布，重参数化采样，再解码", "出处：Kingma & Welling 2013 · §2.4、§3")
    return f


# ================================================================ LeNet-5
def lenet(pal):
    """一叠特征图 fmaps（原图画法）：方块边长 ∝ 空间尺寸，叠几张示意通道数。"""
    f = Fig(pal)
    cy = 130
    maps = [  # (边长, 叠几张, role, 下方文字)
        (96, 1, "io", "输入 32×32"), (84, 4, "attn", "C1 · 6@28×28"), (42, 4, "io", "S2 · 6@14×14"),
        (30, 6, "attn", "C3 · 16@10×10"), (16, 6, "io", "S4 · 16@5×5"),
    ]
    ids, x = [], 30
    for s, n, role, below in maps:
        ids.append(f.fmaps(x, cy - s / 2, s, s, n=n, off=6, role=role, below=below))
        x += s + 6 * (n - 1) + 80
    for lab, h, role in (("C5 · 120", 120, "ffn"), ("F6 · 84", 84, "ffn"), ("输出 · 10", 30, "io")):
        ids.append(f.box(x, cy - h / 2, 14, h, "", role, arc=30))
        f.text(x - 36, cy + h / 2 + 4, 86, 16, lab, fs=10.5)
        x += 14 + 80
    ops = ["卷积 5×5", "下采样 2×2", "卷积 5×5", "下采样 2×2", "卷积 5×5", "全连接", "RBF 输出"]
    for k, (a, b) in enumerate(zip(ids, ids[1:])):
        ax, ay, aw, ah = f.geo[a]
        gap_x = ax + aw + 6 * (maps[k][1] - 1) if k < len(maps) else ax + aw
        bx = f.geo[b][0]
        f.edge(start=(gap_x + 8, cy), end=(bx - 6, cy))
        f.text(gap_x, cy - 34, bx - gap_x, 30, ops[k], fs=10.5)
    foot(f, 20, x - 40, 240, "LeNet-5：卷积和下采样交替，最后全连接", "出处：LeCun et al. 1998 · 图 2")
    return f


# ================================================================ U-Net
def unet(pal):
    """U 形手排：特征图条（宽 ∝ 通道、高 ∝ 空间尺寸）+ 横向跳连 + 图例。"""
    f = Fig(pal)
    ch = [64, 128, 256, 512, 1024]
    size = ["572²", "284²", "140²", "68²", "32²"]
    hts = [120, 88, 64, 46, 34]
    cys = [90, 215, 325, 420, 500]
    gap = 22

    def bar(cx, k, role="attn", **kw):
        w = 8 + 4 * k
        return f.box(cx - w / 2, cys[k] - hts[k] / 2, w, hts[k], "", role, arc=8, **kw)

    def convs(first, k):
        """first 右边再接两次 3×3 卷积，返回最后一条"""
        w = 8 + 4 * k
        cx = f.geo[first][0] + w / 2
        b = bar(cx + w + gap, k)
        c = bar(cx + 2 * (w + gap), k)
        f.right(first, b)
        f.right(b, c)
        f.text(f.geo[b][0] - 20, cys[k] - hts[k] / 2 - 18, w + 40, 16, str(ch[k]), fs=10)  # 标在中间条，首尾条顶上要走箭头
        return c

    cx_of = lambda i: f.geo[i][0] + f.geo[i][2] / 2  # noqa: E731
    # 收缩路径：下一层第一条正对上一层最后一条，最大池化竖直向下
    inp = f.box(34, cys[0] - hts[0] / 2, 6, hts[0], "", "io", arc=8)
    f.text(22, cys[0] - hts[0] / 2 - 18, 30, 16, "1", fs=10)
    enc, prev = {}, None
    for k in range(5):
        first = bar(80 if k == 0 else cx_of(prev), k)
        if k == 0:
            f.right(inp, first)
        else:
            f.edge(prev, first, sx=.5, sy=1, ex=.5, ey=0)
        f.text(f.geo[inp if k == 0 else first][0] - 50, cys[k] - 8, 44, 16, size[k], fs=10, align="right")
        prev = enc[k] = convs(first, k)
    # 扩张路径：上卷积竖直向上，左边拼上从编码器拷来的特征（虚线框）
    for k in range(3, -1, -1):
        up = bar(cx_of(prev) + 30, k)
        f.edge(prev, up, sx=.5, sy=0, ex=.5, ey=1, pts=[(cx_of(prev), cys[k] + hts[k] / 2 + 16),
                                                       (cx_of(up), cys[k] + hts[k] / 2 + 16)])
        ux, uy, uw, uh = f.geo[up]
        cp = f.box(ux - uw, uy, uw, uh, "", "white", arc=8, stroke="#9A9A9A", sw=1, dashed=True)
        f.edge(enc[k], cp, sx=1, sy=.5, ex=0, ey=.5, dashed=True, color="#9A9A9A", w=1.2)
        prev = convs(up, k)
    ox, oy, ow, oh = f.geo[prev]
    out = f.box(ox + ow + 40, cys[0] - hts[0] / 2, 8, hts[0], "", "ffn", arc=8)
    f.right(prev, out)
    f.text(ox + ow + 16, cys[0] + hts[0] / 2 + 4, 60, 30, "2 类\n388²", fs=10)
    # 图例放右下空白处
    lx, ly = cx_of(enc[4]) + 190, 420
    for k, (txt, kw) in enumerate([("卷积 3×3 + ReLU", {}), ("最大池化 2×2（向下）", {}), ("上卷积 2×2（向上）", {}),
                                    ("复制并裁剪", dict(dashed=True, color="#9A9A9A", w=1.2)), ("卷积 1×1 → 分割图", {})]):
        f.edge(start=(lx, ly + k * 22), end=(lx + 34, ly + k * 22), **kw)
        f.text(lx + 42, ly + k * 22 - 8, 200, 16, txt, fs=10.5, align="left")
    f.text(lx - 4, ly + 110, 260, 30, "虚线框 = 从编码器拷来的特征，\n与上采样结果拼接", fs=10, align="left")
    W = f.geo[out][0] + 40
    foot(f, 0, W, 560, "U-Net：收缩路径 + 对称扩张路径，逐层跳连", "出处：Ronneberger et al. 2015 · 图 1")
    return f


# ================================================================ ViT
def vit(pal):
    """patch 网格 grid + token 序列 + 可学习 [class]。"""
    f = Fig(pal)
    tint = ["io", "attn", "ffn", "norm", "cond", "attn", "ffn", "io", "norm"]
    f.grid(30, 370, 3, 3, 36, lambda r, c: tint[r * 3 + c], arc=6)
    f.text(10, 482, 150, 16, "图像切成 P×P 的 patch", fs=10.5)
    flat = f.grid(200, 406, 1, 9, 30, lambda r, c: tint[c], arc=6)
    f.edge(start=(142, 424), end=(196, 424))
    f.text(200, 440, 270, 16, "展平成 9 个 patch 向量", fs=10.5)
    proj = f.box(170, 334, 300, 34, "线性投影 E", "ffn", sub=None)
    f.edge(start=(335, 404), end=(335, 370))
    f.edge(start=(335, 334), end=(335, 323))
    toks = f.grid(170, 262, 1, 10, 30, lambda r, c: "cond" if c == 0 else "io",
                  hl_at=lambda r, c: c == 0, label_at=lambda r, c: "*" if c == 0 else str(c), arc=6, fs=11)
    f.grid(170, 292, 1, 10, 30, lambda r, c: "inject", label_at=lambda r, c: str(c), arc=6, fs=10)
    f.text(60, 268, 106, 18, "patch 嵌入", fs=10.5, align="right")
    f.text(60, 298, 106, 18, "+ 位置编码", fs=10.5, align="right")
    f.text(60, 234, 220, 18, "* = 可学习的 [class] 嵌入", fs=10.5, align="left")
    enc = f.box(170, 150, 300, 60, "Transformer 编码器 × L", "white", sub="Pre-LN · 多头自注意力 + MLP", bold=True,
                stroke="#222222", fs=15)
    f.edge(start=(320, 262), end=(320, 212))
    head = f.box(140, 84, 90, 32, "MLP Head", "ffn")
    f.edge(enc, head, sx=.05, sy=0, ex=.5, ey=1)
    cls = f.box(140, 30, 90, 30, "类别", "io")
    f.up(head, cls)
    f.text(240, 88, 220, 34, "只用 [class] 位置的输出做分类", fs=10.5, align="left")
    foot(f, 20, 480, 510, "ViT：把图像当成 patch 序列送进 Transformer", "出处：Dosovitskiy et al. 2020 · 图 1、§3.1")
    return f


# ================================================================ CLIP
def clip(pal):
    """相似度矩阵 grid，对角线是正样本。"""
    f = Fig(pal)
    idx = ["_{1}", "_{2}", "_{3}", "…", "_{N}"]
    gx, gy, cs = 210, 170, 46
    f.grid(gx, gy, 5, 5, cs, lambda r, c: "core" if r == c else "io",
           label_at=lambda r, c: "…" if "…" in (idx[r], idx[c]) else f"I{idx[r]}·T{idx[c]}", fs=10)
    t_in = f.box(20, 40, 150, 36, "一批 N 条文本", "io")
    t_enc = f.box(gx, 40, 5 * cs, 36, "文本编码器", "white", stroke="#222222", bold=True)
    f.right(t_in, t_enc)
    trow = f.grid(gx, 106, 1, 5, cs, lambda r, c: "cond", label_at=lambda r, c: f"T{idx[c]}", fs=11)
    f.edge(start=(gx + 2.5 * cs, 76), end=(gx + 2.5 * cs, 106))
    icol = f.grid(gx - 60, gy, 5, 1, cs, lambda r, c: "cond", label_at=lambda r, c: f"I{idx[r]}", fs=11)
    i_enc = f.box(40, gy, 70, 5 * cs, "图像\n编码器", "white", stroke="#222222", bold=True)
    f.edge(start=(110, gy + 2.5 * cs), end=(gx - 60, gy + 2.5 * cs))
    i_in = f.box(25, gy + 5 * cs + 30, 100, 36, "一批 N 张图", "io")
    f.edge(i_in, i_enc, sx=.5, sy=0, ex=.5, ey=1)
    f.text(gx + 5 * cs + 16, gy + 30, 200, 120,
           "橙色对角线：配对的\n图文，拉高相似度\n\n其余 N² − N 格：\n不配对，压低相似度\n\n按行、按列各做一次\n交叉熵", fs=11, align="left")
    foot(f, 20, 640, gy + 5 * cs + 86, "CLIP：一个 batch 内的图文对比学习", "出处：Radford et al. 2021 · 图 1、图 3")
    return f


# ================================================================ LSTM
def lstm(pal):
    """运算节点 op（× + tanh）+ 横向细胞状态线 + 门。"""
    f = Fig(pal)
    f.group(120, 50, 480, 250, None, dashed=False)
    top, bus = 90, 262
    f.text(20, top - 9, 90, 18, "c_{t−1}", fs=13, color=f.P["text"], align="right")
    f.text(20, bus - 9, 90, 18, "h_{t−1}", fs=13, color=f.P["text"], align="right")
    gates = [("f", "σ", "mod", 200), ("i", "σ", "mod", 290), ("g", "tanh", "ffn", 380), ("o", "σ", "mod", 490)]
    gid = {k: f.box(cx - 34, 190, 68, 30, f"{k} · {fn}", role, fs=12) for k, fn, role, cx in gates}
    fx = f.op(200, top, "×")
    ig = f.op(335, 150, "×")
    add = f.op(335, top, "+")
    th = f.op(560, 150, "tanh", r=16)
    ox = f.op(560, 205, "×")
    f.edge(arrow=False, start=(112, top), end=(189, top))
    f.edge(fx, add, sx=1, sy=.5, ex=0, ey=.5)
    f.edge(add, None, sx=1, sy=.5, end=(680, top))
    f.text(684, top - 9, 50, 18, "c_{t}", fs=13, color=f.P["text"], align="left")
    f.edge(gid["f"], fx, sx=.5, sy=0, ex=.5, ey=1)
    f.edge(gid["i"], ig, sx=.5, sy=0, ex=0, ey=.5, pts=[(290, 150)])
    f.edge(gid["g"], ig, sx=.5, sy=0, ex=1, ey=.5, pts=[(380, 150)])
    f.up(ig, add)
    f.edge(tgt=th, ex=.5, ey=0, start=(560, top))
    f.edge(th, ox, sx=.5, sy=1, ex=.5, ey=0)
    f.edge(gid["o"], ox, sx=1, sy=.5, ex=0, ey=.5)
    f.edge(ox, None, sx=1, sy=.5, end=(680, 205))
    f.text(684, 196, 50, 18, "h_{t}", fs=13, color=f.P["text"], align="left")
    f.edge(arrow=False, start=(112, bus), end=(490, bus))
    f.edge(start=(150, 330), end=(150, bus + 1))
    f.text(120, 332, 60, 18, "x_{t}", fs=13, color=f.P["text"])
    for k, _, _, cx in gates:
        f.edge(tgt=gid[k], ex=.5, ey=1, start=(cx, bus))
    f.text(130, 56, 300, 18, "[h_{t−1}, x_{t}] 拼接后分别进四个门", fs=10.5, align="left")
    f.text(20, 360, 700, 18, "c_{t} = f ⊙ c_{t−1} + i ⊙ g；h_{t} = o ⊙ tanh(c_{t})", fs=12, color=f.P["text"])
    foot(f, 20, 700, 388, "LSTM 单元：门控决定细胞状态忘多少、写多少、读多少",
         "出处：Hochreiter & Schmidhuber 1997；遗忘门见 Gers et al. 2000")
    return f


# ================================================================ ControlNet
def controlnet(pal):
    """冻结 / 可训练对照 state + 分组框 group。"""
    f = Fig(pal)
    f.group(300, 116, 180, 364, "ControlNet")
    x = f.box(90, 384, 120, 32, "x", "io")
    lock = f.box(70, 250, 160, 70, "神经网络块", "white", stroke="#222222", bold=True, state="frozen", sub="原模型，锁定")
    p_out = f.plus(150, 170)
    yc = f.box(90, 90, 120, 32, "y_{c}", "io")
    c = f.box(330, 500, 120, 32, "条件 c", "cond")
    z1 = f.box(330, 436, 120, 30, "零卷积", "ffn", hl=True, state="train")
    p_in = f.plus(390, 400)
    copy = f.box(310, 250, 160, 70, "可训练副本", "white", stroke="#222222", bold=True, state="train", hl=True, sub="同结构，拷贝权重")
    z2 = f.box(330, 155, 120, 30, "零卷积", "ffn", hl=True, state="train")
    f.up(x, lock)
    f.right(x, p_in)
    f.up(c, z1)
    f.up(z1, p_in)
    f.up(p_in, copy)
    f.up(copy, z2)
    f.edge(z2, p_out, sx=0, sy=.5, ex=1, ey=.5)
    f.up(lock, p_out)
    f.up(p_out, yc)
    f.text(500, 200, 220, 110, "零卷积：1×1 卷积，\n权重和偏置都初始化为 0。\n\n训练刚开始时 ControlNet\n输出为 0，不破坏原模型。", fs=11, align="left")
    foot(f, 20, 700, 548, "ControlNet：锁定原网络，训练一份带零卷积的副本", "出处：Zhang et al. 2023 · 图 2、§3.1")
    return f


# ================================================================ MLP
def mlp(pal):
    """神经元全连接示意 neurons。"""
    f = Fig(pal)
    cols = f.neurons(80, 140, [3, 5, 5, 2], dx=120, dy=40, r=13, roles=["io", "ffn", "ffn", "cond"])
    for k, t in enumerate(["输入层", "隐藏层", "隐藏层", "输出层"]):
        f.text(80 + k * 120 - 40, 250, 80, 16, t, fs=11)
    foot(f, 20, 440, 280, "多层感知机：相邻层全连接", "示意图，不对应具体论文")
    return f


FIGURES = [("lora", "LoRA", lora), ("vae", "VAE", vae), ("lenet", "LeNet-5", lenet), ("unet", "U-Net", unet),
           ("vit", "ViT", vit), ("clip", "CLIP", clip), ("lstm", "LSTM", lstm), ("controlnet", "ControlNet", controlnet),
           ("mlp", "MLP", mlp)]
