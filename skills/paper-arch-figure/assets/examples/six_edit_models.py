"""示例 spec：六个图像编辑模型的三段放大架构图。

用法：archfig build six_edit_models.py --out figs/
事实出处：diffusers e0abab8 与 HunyuanImage-3.0 官方代码；每张图右段底部写了关键行号。
这是事实核对过的完整示例，照着写新模型时优先复制结构最接近的那个函数。
"""
from figlib import *  # noqa: F401,F403  Fig、版式函数和坐标常量


# ================================================================ 1. Qwen-Image-Edit-2511
def q2511(pal):
    f = Fig(pal)
    segs = overall(
        f,
        lanes=[
            dict(inp=("指令", "io", None, False), enc=("Qwen2.5-VL-7B", "cond", "指令 + 384² 参考图", True),
                 enc2=("RMSNorm → Linear", "norm", "3584 → 3072", False)),
            dict(inp=("参考图", "io", None, False), enc=("VAE · 1024²", "io", "8× 下采样 · 16 通道", False),
                 enc2=("2×2 打包", "io", "→ 64 维 → 3072", False)),
            dict(inp=("目标图", "io", "训练才有", False), enc=("VAE", "io", "8× · 16 通道", False),
                 enc2=("加噪 x_t · 2×2 打包", "io", "推理：直接用噪声", False)),
        ],
        seq_title="注意力里的一条序列：[ 文本 | 图像 ]",
        segs=[("文本", "seg_txt", 2, False), ("x_t 目标", "seg_x", 2.2, False),
              ("参考图 1", "seg_ref", 2, True), ("参考图 2 …", "seg_ref", 1.8, True)],
        blocks=[("双流 MMDiT Block × 60", "宽 3072 · 24 头", False)],
        tops=[[("AdaLN-Continuous → proj_out", "norm", "3072 → 64", False)],
              [("取前 N 个 token → 速度 v", "io", None, False)]],
        cap="Qwen-Image-Edit-2511", cross=(1, 0))

    dual_block(f, mods=(("txt_mod(t)", False), ("img_mod(t / 0)", True)),
               attn=("Joint Attention · [ 文本, 图像 ]", "各自 QKV → QK-RMSNorm → MSRoPE"),
               top_note="FFN：3072 → 12288 → 3072；两个流各有一套调制和 FFN 权重", cap="双流 Block（× 60，每层两套调制）")

    # ---- 右段：zero_cond_t ----
    px, py, pww, phh = P3
    f.panel(*P3, main=False)
    f.text(px + 16, py + 14, pww - 32, 40, "zero_cond_t：每个图像 token\n自己挑一组调制", fs=14, color=f.P["text"], bold=True)
    s, sg = f.seq(px + 20, py + 72, pww - 40, 74, "图像流里的 token（目标在前）",
                  [("x_t", "seg_x", 2, False, "index 0"), ("参考图 1", "seg_ref", 2, True, "index 1"),
                   ("参考图 2", "seg_ref", 2, True, "index 1")], fs=12)
    r0 = f.box(px + 30, py + 200, 160, 44, "第 0 行", "mod", sub="真实 t 的 6 组系数", fs=13)
    r1 = f.box(px + pww - 190, py + 200, 160, 44, "第 1 行", "mod", sub="t = 0 的 6 组系数", hl=True, fs=13)
    f.edge(r0, sg[0], sx=.5, sy=0, ex=.5, ey=1)
    f.edge(r1, sg[1], sx=.35, sy=0, ex=.5, ey=1)
    f.edge(r1, sg[2], sx=.65, sy=0, ex=.5, ey=1)
    lin = f.box(px + 60, py + 290, pww - 120, 40, "img_mod：SiLU → Linear", "mod", sub="3072 → 6 × 3072", fs=13)
    f.edge(lin, r0, sx=.3, sy=0, ex=.5, ey=1)
    f.edge(lin, r1, sx=.7, sy=0, ex=.5, ey=1)
    bat = f.box(px + 60, py + 372, pww - 120, 40, "temb 批次拼成 [ t ; 0 · t ]", "cond", hl=True, fs=13)
    f.up(bat, lin)
    t = f.box(px + 130, py + 452, pww - 260, 34, "Timestep t", "cond", fs=13)
    f.up(t, bat)
    f.text(px + 16, py + 500, pww - 32, 40, "文本流只用真实 t 那一半：文本不是 t = 0。\ntorch.where(index == 0, …) 逐 token 选行。", fs=11)
    src(f, "diffusers e0abab8 · transformer_qwenimage.py:963-969, 688-711, 732-734")
    caption(f, px, pww, "独有做法：参考图按 t = 0 调制")
    return f


# ================================================================ 2. Qwen-Image 2.1
def q21(pal):
    f = Fig(pal)
    overall(
        f,
        lanes=[
            dict(inp=("指令 + 参考图", "io", None, False), enc=("Qwen3-VL", "cond", "读指令和 1024² 参考图", True),
                 enc2=("ZeroCenter RMSNorm", "norm", "→ MLP 4096 → 4096", False)),
            dict(inp=("参考图", "io", None, False), enc=("VAE 16× · 64 通道", "io", "RGBA 四通道", True),
                 enc2=("直接展平", "io", "1 latent 像素 = 1 token", True)),
            dict(inp=("目标图", "io", "训练才有", False), enc=("VAE 16× · 64 通道", "io", "RGBA 四通道", True),
                 enc2=("加噪 x_t · 直接展平", "io", "推理：直接用噪声", False)),
        ],
        seq_title="一条序列：参考图 token 填进 image_pad 槽，目标接在最后",
        segs=[("文字", "seg_txt", 1.6, False), ("参考图（槽）", "seg_ref", 2.2, True),
              ("文字", "seg_txt", 1.4, False), ("x_t 目标", "seg_x", 2.2, False)],
        blocks=[("单流 Block × 32", "宽 4096 · 32 头", True)],
        tops=[[("norm_out（只 scale）→ proj_out", "norm", "4096 → 64", False)],
              [("取最后 N 个 token → 速度 v", "io", None, True)]],
        cap="Qwen-Image 2.1")
    single_block(
        f,
        [dict(label="Hidden (B, S, 4096)", role="io", h=28, key="in"),
         dict(label="LayerNorm", role="norm", h=26, key="n1"),
         dict(label="× (1 + scale)", role="mod", h=26, key="m1", join=True, hl=True),
         dict(label="Q K V · QK-RMSNorm · RoPE", role="attn", h=30, key="qkv"),
         dict(label="块因果 Self-Attention", role="core", h=32, key="att", bold=True, hl=True),
         dict(label="× tanh(gate)", role="mod", h=26, key="g1"),
         dict(kind="plus", key="p1"),
         dict(label="LayerNorm", role="norm", h=26, key="n2"),
         dict(label="× (1 + scale)", role="mod", h=26, key="m2", join=True, hl=True),
         dict(label="SwiGLU · 4096 → 12288", role="ffn", h=30, key="ff"),
         dict(label="× tanh(gate)", role="mod", h=26, key="g2"),
         dict(kind="plus", key="p2"),
         dict(label="下一层", role="io", h=26, key="out")],
        bus_label=("全网共享调制", True), bus_keys=["m1", "g1", "m2", "g2"],
        residuals=[("in", "p1"), ("p1", "p2")],
        injects=[("块因果 mask", None, "att", True), ("3 轴 RoPE", None, "qkv", False)],
        gap=19, cap="单流 Block（× 32，块内没有自己的参数）", note=("没有 shift", "只有 scale 和 gate"))
    # 右段：块因果 mask 矩阵
    px, py, pww, phh = P3
    f.panel(*P3, main=False)
    f.text(px + 16, py + 12, pww - 32, 24, "块因果注意力：谁能看谁", fs=14, color=f.P["text"], bold=True)
    toks = ["文", "文", "参", "参", "文", "文", "目", "目"]
    img = [-1, -1, 0, 0, -1, -1, 1, 1]
    cs, gx, gy = 30, px + 110, py + 70
    for j, t in enumerate(toks):
        f.text(gx + j * cs, gy - 22, cs, 18, t, fs=11, color=f.P["text"])
        f.text(gx - 50, gy + j * cs + 6, 44, 18, t, fs=11, color=f.P["text"], align="right")
    for q in range(8):
        for k in range(8):
            ok = q >= k or (img[q] == img[k] and img[q] >= 0)
            fut = ok and k > q
            role = "core" if ok else "white"
            f.box(gx + k * cs + 1, gy + q * cs + 1, cs - 2, cs - 2, "", role, arc=10,
                  stroke=None if ok else "#E0E0E0", sw=1, hl=False, fill="#0071E3" if (fut and pal == "deck") else None)
    f.text(gx, gy + 8 * cs + 6, 8 * cs, 18, "行 = query，列 = key；着色 = 能看", fs=10.5)
    f.text(gx - 100, gy - 22, 44, 18, "q ↓ k →", fs=10)
    f.text(px + 16, py + 350, pww - 32, 44, "文字严格从前往后；同一张图内部双向（对角块）；\n后面的图能看前面的图，反过来不行。", fs=11)
    kv = f.box(px + 30, py + 410, pww - 60, 66, "条件前缀按 t = 0 调制 → K / V 每步一样", "cond", hl=True,
               sub="第 0 步存下前缀 K / V，之后只喂目标 token", fs=12.5)
    src(f, "diffusers e0abab8 · transformer_qwenimage21.py:257-306, 56-84, 238-254")
    caption(f, px, pww, "独有做法：块因果 + 前缀 KV cache")
    return f


# ================================================================ 3. FLUX.1 Kontext
def kontext(pal):
    f = Fig(pal)
    overall(
        f,
        lanes=[
            dict(inp=("指令", "io", None, False), enc=("CLIP + T5", "cond", "只读文字", False),
                 enc2=("T5 token → 文本流", "norm", "CLIP 池化 → 调制", False)),
            dict(inp=("参考图", "io", None, False), enc=("VAE", "io", "8× · 16 通道", False),
                 enc2=("2×2 打包", "io", "→ 64 维 → 3072", False)),
            dict(inp=("目标图", "io", "训练才有", False), enc=("VAE", "io", "8× · 16 通道", False),
                 enc2=("加噪 x_t · 2×2 打包", "io", "推理：直接用噪声", False)),
        ],
        seq_title="一条序列：[ T5 文字 | x_t | 参考图 ]",
        segs=[("T5 文字", "seg_txt", 2, False), ("x_t 目标", "seg_x", 2.2, False),
              ("参考图 · id₀ = 1", "seg_ref", 2.4, True)],
        blocks=[("双流 MMDiT Block × 19", None, False), ("单流 Block × 38", None, False)],
        tops=[[("AdaLN-Continuous → proj_out", "norm", "3072 → 64", False)],
              [("取前 N 个 token → 速度 v", "io", None, False)]],
        cap="FLUX.1 Kontext")
    parallel_block(f, "[ 文本, 图像 ] (B, S, 3072)", None,
                   ("Attention", "QKV · QK-RMSNorm\nRoPE (t, h, w)"), ("proj_mlp", "3072 → 12288\nGELU"),
                   ("concat → proj_out", "15360 → 3072", False), ("AdaLN-Zero（本层自己的）", False),
                   "注意力和 MLP 并行，最后一个 Linear 合并；\n双流 19 层的内部同 2511（不含 zero_cond_t）", "单流 Block（× 38，占 2/3 层数）")
    # 右段：RoPE 坐标
    px, py, pww, phh = P3
    f.panel(*P3, main=False)
    f.text(px + 16, py + 12, pww - 32, 44, "参考图靠位置编码第 0 维区分", fs=14, color=f.P["text"], bold=True)

    def grid(gx, gy, t0, role, hl, title):
        f.text(gx - 10, gy - 26, 170, 20, title, fs=12, color=f.P["text"])
        for r in range(3):
            for c in range(3):
                f.box(gx + c * 50, gy + r * 44, 46, 40, f"{t0},{r},{c}", role, fs=11, arc=12, hl=hl and r == 0 and c == 0)
    grid(px + 30, py + 110, 0, "seg_x", False, "目标 x_t：(0, h, w)")
    grid(px + 222, py + 110, 1, "seg_ref", True, "参考图：(1, h, w)")
    f.text(px + 16, py + 252, pww - 32, 40, "h / w 用同一套网格：同一位置的像素天然对齐。\n文字的坐标全是 (0, 0, 0)。", fs=11)
    gb = f.box(px + 30, py + 320, pww - 60, 60, "guidance 3.5 当作输入", "cond", hl=True,
               sub="和 t、CLIP 池化向量加在一起进调制；一次前向模拟 CFG", fs=12.5)
    f.text(px + 16, py + 400, pww - 32, 60, "文本编码器看不到参考图：\n指令和图怎么对上，全靠 transformer 的注意力。", fs=11)
    src(f, "pipeline_flux_kontext.py:560-563, 659-663 · transformer_flux.py:725-733")
    caption(f, px, pww, "独有做法：参考图 id₀ = 1")
    return f


# ================================================================ 4. FLUX.2
def flux2(pal):
    f = Fig(pal)
    overall(
        f,
        lanes=[
            dict(inp=("指令", "io", None, False), enc=("Mistral 3", "cond", "只读文字", False),
                 enc2=("取第 10 / 20 / 30 层", "norm", "叠成 15360 维 → 6144", True)),
            dict(inp=("参考图 × k", "io", None, False), enc=("VAE · 32 通道", "io", "BatchNorm 统计量归一化", True),
                 enc2=("2×2 patchify", "io", "→ 128 维 token", True)),
            dict(inp=("目标图", "io", "训练才有", False), enc=("VAE · 32 通道", "io", "BatchNorm 统计量归一化", True),
                 enc2=("加噪 x_t · 2×2", "io", "→ 128 维 token", False)),
        ],
        seq_title="一条序列：[ 文字 | x_t | 参考图 1 | 参考图 2 … ]",
        segs=[("文字", "seg_txt", 1.6, False), ("x_t 目标", "seg_x", 2, False),
              ("参考 1 · T=10", "seg_ref", 2.1, True), ("参考 2 · T=20", "seg_ref", 2.1, True)],
        blocks=[("双流 MMDiT Block × 8", None, False), ("单流 Block × 48", None, False)],
        tops=[[("AdaLN-Continuous → proj_out", "norm", "6144 → 128", False)],
              [("只留目标 token → 速度 v", "io", None, False)]],
        cap="FLUX.2")
    parallel_block(f, "[ 文本, 图像 ] (B, S, 6144)", ("to_qkv_mlp_proj · 一个 Linear", "6144 → 55296", True),
                   ("Attention", "QK-RMSNorm\nRoPE 4 轴"), ("SwiGLU", "2 × 18432\n→ 18432"),
                   ("concat → to_out · 一个 Linear", "24576 → 6144", True), ("全网共享调制", True),
                   "本层没有自己的调制权重；所有 Linear 都不带 bias", "单流 Block（× 48，占 6/7 层数）")
    # 右段：4 轴 RoPE 表 + 共享调制
    px, py, pww, phh = P3
    f.panel(*P3, main=False)
    f.text(px + 16, py + 12, pww - 32, 24, "多张参考图按时间坐标错开", fs=14, color=f.P["text"], bold=True)
    rows = [("", "T", "H", "W", "L", None, False), ("文字", "0", "0", "0", "l", "seg_txt", False),
            ("x_t", "0", "h", "w", "0", "seg_x", False), ("参考图 1", "10", "h", "w", "0", "seg_ref", True),
            ("参考图 2", "20", "h", "w", "0", "seg_ref", True), ("参考图 i", "10 + 10i", "h", "w", "0", "seg_ref", True)]
    for r, (lab, *vals, role, hl) in enumerate(rows):
        yy = py + 56 + r * 38
        if r == 0:
            for c, v in enumerate(vals):
                f.text(px + 130 + c * 66, yy, 60, 26, v, fs=12, color=f.P["text"], bold=True)
            continue
        f.box(px + 22, yy, 100, 30, lab, role, fs=12, arc=14)
        for c, v in enumerate(vals):
            f.box(px + 130 + c * 66, yy, 60, 30, v, "white", fs=12, stroke="#D0D0D0", sw=1, arc=14,
                  hl=hl and c == 0)
    ty = py + 56 + 6 * 38 + 20
    te = f.box(px + 140, ty + 170, pww - 280, 30, "temb = t + guidance", "cond", fs=12)
    b1 = f.box(px + 20, ty + 100, 118, 42, "双流 · 图像", "mod", sub="6 个系数", fs=12)
    b2 = f.box(px + 147, ty + 100, 118, 42, "双流 · 文本", "mod", sub="6 个系数", fs=12)
    b3 = f.box(px + 274, ty + 100, 118, 42, "单流", "mod", sub="3 个系数", fs=12)
    for b in (b1, b2, b3):
        f.up(te, b)
    al = f.box(px + 20, ty + 30, pww - 40, 36, "8 + 48 个 block 全部共用这 3 组", "mod", hl=True, fs=12.5)
    for b in (b1, b2, b3):
        f.up(b, al)
    src(f, "pipeline_flux2.py:407-454 · transformer_flux2.py:1036-1047, 1291-1293")
    caption(f, px, pww, "独有做法：T 轴错开 + 全网共享调制")
    return f


# ================================================================ 5. Z-Image Omni
def zomni(pal):
    f = Fig(pal)
    overall(
        f,
        lanes=[
            dict(inp=("指令", "io", None, False), enc=("文本编码器", "cond", "只读文字", False),
                 enc2=("refiner × 2", "white", "自己的，无调制", False)),
            dict(inp=("参考图", "io", None, False), enc=("SigLIP2", "cond", "读参考图语义", True),
                 enc2=("refiner × 2", "white", "自己的，无调制", False)),
            dict(inp=("参考图", "io", None, False), enc=("VAE", "io", "8× · 16 通道", False),
                 enc2=("2×2 patch", "io", "→ noise_refiner × 2", False)),
            dict(inp=("目标图", "io", "训练才有", False), enc=("VAE", "io", "8× · 16 通道", False),
                 enc2=("加噪 x_t · 2×2", "io", "→ noise_refiner × 2", False)),
        ],
        seq_title="一条序列：[ 文字 | 图像：参考图 · x_t | SigLIP2 ]",
        segs=[("文字", "seg_txt", 1.6, False), ("参考图", "seg_ref", 1.8, False),
              ("x_t 目标", "seg_x", 1.8, False), ("SigLIP2", "seg_ref", 1.8, True)],
        blocks=[("单流 Block × 30", "宽 3840 · 所有 token 共用", True)],
        tops=[[("Final Layer（LN · 只 scale）", "norm", "3840 → 64", False)],
              [("只返回目标 token · 取负 → v", "io", None, True)]],
        cap="Z-Image Omni")
    single_block(
        f,
        [dict(label="Hidden (B, S, 3840)", role="io", h=28, key="in"),
         dict(label="RMSNorm", role="norm", h=26, key="n1"),
         dict(label="× (1 + scale)", role="mod", h=26, key="m1", join=True),
         dict(label="Self-Attention", role="core", h=34, key="att", bold=True, sub="QK-RMSNorm"),
         dict(label="RMSNorm（后置）", role="norm", h=26, key="pn1", hl=True),
         dict(label="× tanh(gate)", role="mod", h=26, key="g1"),
         dict(kind="plus", key="p1"),
         dict(label="RMSNorm", role="norm", h=26, key="n2"),
         dict(label="× (1 + scale)", role="mod", h=26, key="m2", join=True),
         dict(label="SwiGLU · 3840 → 10240", role="ffn", h=30, key="ff"),
         dict(label="RMSNorm（后置）", role="norm", h=26, key="pn2", hl=True),
         dict(label="× tanh(gate)", role="mod", h=26, key="g2"),
         dict(kind="plus", key="p2"),
         dict(label="下一层", role="io", h=26, key="out")],
        bus_label=("adaLN（本层）", False), bus_keys=["m1", "g1", "m2", "g2"],
        residuals=[("in", "p1"), ("p1", "p2")],
        injects=[("RoPE 3 轴", "(位置, h, w)", "att", False)],
        gap=17, cap="单流 Block（× 30，前后各一个 RMSNorm）", note=("三明治 Norm", "没有 shift"))
    px, py, pww, phh = P3
    f.panel(*P3, main=False)
    f.text(px + 16, py + 12, pww - 32, 44, "noise mask：每个 token\n按自己的 mask 挑时间步", fs=14, color=f.P["text"], bold=True)
    s, sg = f.seq(px + 14, py + 76, pww - 28, 74, "Omni 序列（参考图一段、目标一段）",
                  [("文字₁", "seg_txt", 1.5, False, "干净"), ("文字₂", "seg_txt", 1.5, True, "真实 t"),
                   ("参考图", "seg_ref", 1.6, False, "干净"), ("x_t", "seg_x", 1.3, True, "真实 t"),
                   ("SigLIP", "seg_ref", 1.6, False, "干净")], fs=11)
    tc = f.box(px + 24, py + 228, 170, 42, "t_clean = emb(1)", "cond", sub="mask = 0：条件 token", fs=12)
    tn = f.box(px + pww - 194, py + 228, 170, 42, "t_noisy = emb(t)", "cond", sub="mask = 1：目标", fs=12)
    sel = f.box(px + 60, py + 182, pww - 120, 26, "select_per_token", "mod", hl=True, fs=12)
    f.edge(tc, sel, sx=.5, sy=0, ex=.3, ey=1)
    f.edge(tn, sel, sx=.5, sy=0, ex=.7, ey=1)
    f.edge(sel, s, sx=.5, sy=0, ex=.5, ey=1)
    f.text(px + 16, py + 290, pww - 32, 60, "文字 j 继承图像 j 的 mask：\n目标那段文字（文字₂）也按真实 t 调制。", fs=11)
    cv = f.box(px + 30, py + 370, pww - 60, 62, "约定翻转：传 1 − σ，输出取负", "cond", hl=False,
               sub="干净 = t 为 1；换算回来和别家是同一个 flow matching", fs=12.5)
    f.text(px + 16, py + 450, pww - 32, 60, "和 2511 的 zero_cond_t、2.1 的 causal_condition\n是同一件事：条件 token 用「干净」的调制。", fs=11)
    src(f, "transformer_z_image.py:940-941, 155-166, 651 · pipeline_z_image_omni.py:632, 713")
    caption(f, px, pww, "独有做法：逐 token 的干净 / 真实时间步")
    return f


# ================================================================ 6. HunyuanImage 3.0
def hy3(pal):
    f = Fig(pal)
    overall(
        f,
        lanes=[
            dict(inp=("指令", "io", None, False), enc=("wte 查表", "io", "没有独立文本编码器", True),
                 enc2=("先写思考 · 改写", "cond", "再出尺寸 token", True)),
            dict(inp=("参考图", "io", None, False), enc=("VAE → UNetDown", "io", "按 t = 0", False),
                 enc2=("+ SigLIP2 → MLP", "cond", "拼成一个图像块", True)),
            dict(inp=("Timestep t", "cond", None, False), enc=("timestep_emb", "cond", "序列里的一个 token", True)),
            dict(inp=("目标图", "io", "训练才有", False), enc=("VAE 16×", "io", "32 通道 · 不打包", False),
                 enc2=("加噪 → UNetDown", "io", "按 t 调制", False)),
        ],
        seq_title="一条序列 (B, S, 4096)",
        segs=[("指令 + 参考图块", "seg_ref", 2.4, False), ("思考 · 尺寸", "seg_txt", 1.8, True),
              ("t", "cond", 0.6, True), ("x_t 目标", "seg_x", 1.8, False)],
        blocks=[("Decoder Layer × 32", "同一个 MoE 大语言模型", True)],
        tops=[[("ln_f → lm_head", "ffn", "文字位置 · 4096 → 133120", False), ("UNetUp(t)", "ffn", "只取图像位置", False)],
              [("下一个 token（CE）", "io", None, False), ("速度 v · 32 通道", "io", None, False)]],
        cap="HunyuanImage 3.0")
    single_block(
        f,
        [dict(label="Hidden (B, S, 4096)", role="io", h=28, key="in"),
         dict(label="RMSNorm", role="norm", h=28, key="n1"),
         dict(label="qkv_proj · 32 Q / 8 KV × 128", role="attn", h=30, key="qkv"),
         dict(label="2D RoPE（Q、K）", role="attn", h=30, key="rope"),
         dict(label="QK-RMSNorm", role="attn", h=30, key="qkn"),
         dict(label="广义因果 Self-Attention", role="core", h=32, key="att", bold=True, hl=True),
         dict(label="o_proj", role="attn", h=30, key="o"),
         dict(kind="plus", key="p1"),
         dict(label="RMSNorm", role="norm", h=28, key="n2"),
         dict(label="MoE FFN · 64 选 8 + 1", role="ffn", h=34, key="moe", bold=True, hl=True),
         dict(kind="plus", key="p2"),
         dict(label="下一层", role="io", h=26, key="out")],
        residuals=[("in", "p1"), ("p1", "p2")],
        injects=[("mask", "文字因果\n图内全看", "att", True), ("位置 (y, x)", "文字 (n, n)\n图像网格居中", "rope", False)],
        gap=20, cap="Decoder Layer（= Hunyuan-A13B 层）", note=("无 adaLN", "层内没有 t 输入"))
    px, py, pww, phh = P3
    f.panel(*P3, main=False)
    f.text(px + 16, py + 12, pww - 32, 40, "每个专家都是 SwiGLU：down( x₁ · SiLU(x₂) )\n4096 → 2×3072 → 4096；共享专家同尺寸", fs=11, align="left")
    xin = f.box(px + 24, py + 520, 250, 30, "x（RMSNorm 之后）", "io", fs=12.5)
    rt = f.box(px + 24, py + 440, 250, 36, "Router 4096→64 · softmax · top-8", "cond", fs=12)
    grp = f.box(px + 24, py + 300, 250, 100, "", "white", stroke="#5FA85A", sw=1.5, arc=8, fill="#EEF7EC" if pal == "paper" else "#FBFBFD")
    f.text(px + 24, py + 304, 250, 20, "8 个路由专家（每个 token 各选各的）", fs=11, color=f.P["text"])
    for k, (lab, dx) in enumerate([("E₁", 12), ("E₂", 70), ("E₈", 188)]):
        f.box(px + 24 + dx, py + 336, 50, 48, lab, "ffn", fs=13, arc=12)
    f.text(px + 24 + 128, py + 336, 50, 48, "…", fs=16, color=f.P["text"])
    sh = f.box(px + 292, py + 300, 100, 100, "共享专家", "ffn", sub="所有 token\n都过", bold=True, stroke="#5FA85A", sw=1.5, arc=8, hl=True)
    sg = f.box(px + 24, py + 216, 250, 40, "Σ gᵢ · Eᵢ(x)，gᵢ 归一化到和为 1", "io", fs=12)
    pl = f.plus(px + 149, py + 160)
    mo = f.box(px + 94, py + 90, 110, 30, "MoE(x)", "io", fs=13)
    f.up(xin, rt)
    f.up(rt, grp)
    f.up(grp, sg)
    f.up(sg, pl)
    f.up(pl, mo)
    f.edge(tgt=sh, ex=.5, ey=1, start=(px + 274, py + 535), pts=[(px + 342, py + 535)])
    f.edge(tgt=pl, ex=1, ey=.5, start=(px + 342, py + 300), pts=[(px + 342, py + 160)])
    src(f, "modeling_hunyuan_image_3.py:1142-1232, 1335-1341, 2859-2884")
    caption(f, px, pww, "MoE FFN（每 token 激活 13B 的来源）")
    return f


FIGURES = [("q2511", "Qwen-Image-Edit-2511", q2511), ("q21", "Qwen-Image 2.1", q21),
           ("kontext", "FLUX.1 Kontext", kontext), ("flux2", "FLUX.2", flux2),
           ("zomni", "Z-Image Omni", zomni), ("hy3", "HunyuanImage 3.0", hy3)]
