#!/usr/bin/env python3
"""示例 deck：3 页，展示公式页、3 行对比页、HTML 页的写法。直接跑：

    python3 build.py                 生成 deck.html
    python3 build.py --png           再逐页截图到 png/，并做手机字号自查（和 文案.md 字数检查）
    python3 build.py --png 2         只重出第 2 页
    python3 build.py --check         只自查，不截图
    python3 build.py --png --open    出图、自查后把整套 PNG 打开给人看
    python3 build.py --out DIR       输出到别的目录

改页面只改下面的画图函数。每个函数拿到图区尺寸 W×H（1328×928），按这个坐标系画。
"""
import math

import xhs43
from xhs43 import ACC, ACC_BG, GRID, INK, MUTED, RED, L, M, MH, R, T, mwidth, svg

deck = xhs43.Deck(title='示例 · 注意力为什么除以根号 d', accent='#0071E3')


def check_icon(x, y, r=22):
    return (f'<circle cx="{x}" cy="{y}" r="{r}" fill="{ACC}"/>'
            f'<path d="M{x - r * .45:.1f},{y:.1f} L{x - r * .1:.1f},{y + r * .38:.1f} L{x + r * .5:.1f},{y - r * .4:.1f}" '
            f'fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>')


def cross_icon(x, y, r=22):
    return (f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{RED}" stroke-width="4"/>'
            + L(x - r * .42, y - r * .42, x + r * .42, y + r * .42, RED, 4)
            + L(x - r * .42, y + r * .42, x + r * .42, y - r * .42, RED, 4))


# ---------------------------------------------------------------- 01 公式页：公式 → 推导 → 代入数字
@deck.page('公式', '注意力为什么要<span class="acc">除以 ' + MH(r'\sqrt{d}') + '</span>')
def p_formula(W, H):
    b, X = [], 64
    # 公式 + 紧跟着的一句结论
    b.append(M(X, 150, r'\text{Attention} = \text{softmax}\Big(\frac{QK^{\top}}{\sqrt{d}}\Big) V', 60, INK))
    b.append(M(X, 236, r'结论：除以 \sqrt{d}，把点积的尺度拉回 1', 44, ACC, 600))
    b.append(L(X, 300, W - X, 300, GRID, 2))
    # 推导：两行
    b.append(T(X, 372, '推导', 32, MUTED, 600))
    b.append(M(X, 450, r'q·k = q_{1}k_{1} + q_{2}k_{2} + … + q_{d}k_{d}', 48, INK))
    b.append(M(X, 540, r'每项方差 1，d 项相加 → 方差 d，标准差 \sqrt{d}', 40, INK))
    b.append(L(X, 610, W - X, 610, GRID, 2))
    # 代入具体数字
    b.append(T(X, 682, '代入', 32, MUTED, 600))
    b.append(M(X, 780, r'd = 64：标准差 \sqrt{64} = 8', 52, INK, 600))
    x = X + mwidth(r'd = 64：标准差 \sqrt{64} = 8', 52) + 40
    b.append(M(x, 780, '→ 除以 8，回到 1', 52, ACC, 600))
    b.append(M(X, 862, '不除的话 softmax 被几个大数占满，梯度接近 0', 36, MUTED))
    return svg(W, H, b)


# ---------------------------------------------------------------- 02 对比页：3 行 3 个 case
@deck.page('学习率三档', '学习率：<span class="acc">太小、合适、太大</span>')
def p_compare(W, H):
    b = []
    cases = [  # (名字, 数值, 结论, 好不好, 曲线函数 t∈[0,1] → loss∈[0,1])
        ('太小', r'10^{-5}', '降得太慢', False, lambda t: 0.9 - 0.15 * t),
        ('合适', r'10^{-3}', '稳稳降下来', True, lambda t: 0.12 + 0.78 * math.exp(-5 * t)),
        ('太大', r'10^{-1}', '来回震荡', False, lambda t: 0.55 + 0.3 * math.sin(14 * t) * (0.6 + 0.4 * t)),
    ]
    row_h = H / 3
    for k, (name, val, verdict, good, f) in enumerate(cases):
        y0 = k * row_h
        if good:
            b.append(R(16, y0 + 12, W - 32, row_h - 24, ACC_BG, 20))
        if k:
            b.append(L(48, y0, W - 48, y0, GRID, 2))
        cy = y0 + row_h / 2
        b.append(T(64, cy - 8, name, 48, ACC if good else INK, 600))
        b.append(M(64, cy + 52, r'\text{lr} = ' + val, 36, MUTED))
        # 示意曲线
        x0, x1, ya, yb = 400, 900, y0 + 50, y0 + row_h - 60
        b.append(L(x0, yb, x1, yb, '#C7C7CC', 2) + L(x0, ya, x0, yb, '#C7C7CC', 2))
        pts = ' '.join(f'{x0 + 10 + t / 60 * (x1 - x0 - 20):.1f},{yb - f(t / 60) * (yb - ya):.1f}' for t in range(61))
        b.append(f'<polyline points="{pts}" fill="none" stroke="{ACC if good else INK}" stroke-width="5" '
                 f'stroke-linejoin="round" stroke-linecap="round"/>')
        b.append(T(x1, yb + 40, '训练步数', 28, MUTED, anchor='end'))
        b.append(T(x0 - 14, ya + 24, 'loss', 28, MUTED, anchor='end', mono=True))
        # 结论
        b.append((check_icon if good else cross_icon)(960, cy - 12))
        b.append(T(1000, cy + 2, verdict, 40, ACC if good else INK, 600))
    b.append(T(W - 40, H - 22, '示意曲线', 28, MUTED, anchor='end', extra=' data-small-ok=""'))
    return svg(W, H, b)


# ---------------------------------------------------------------- 03 HTML 页：表格 / 大段文字用 HTML 写，公式用 MH
@deck.page('代入数字', '换几个 <span class="acc">' + MH('d') + '</span> 算一遍', html=True)
def p_table(W, H):
    rows = [(16, 4), (64, 8), (256, 16)]
    tr = ''
    for d, s in rows:
        hi = ' class="hi"' if d == 64 else ''
        sq = MH(r'\sqrt{%d} = %d' % (d, s))
        tr += f'<tr{hi}><td>{MH("d = %d" % d)}</td><td>{sq}</td><td>点积除以 {s}</td></tr>'
    return ('<style>.t3{width:100%;border-collapse:collapse;font-size:48px;text-align:left}'
            '.t3 th{font-size:32px;color:var(--muted);font-weight:500;padding:8px 24px 24px;border-bottom:2px solid var(--line)}'
            '.t3 td{padding:40px 24px;border-bottom:1px solid var(--line)}.t3 tr.hi td{color:var(--accent);font-weight:600}'
            '.note{font-size:36px;color:var(--muted);margin-top:44px}</style>'
            '<table class="t3"><tr><th>维度</th><th>标准差</th><th>怎么缩放</th></tr>' + tr + '</table>'
            f'<div class="note">维度越大，点积越大，越需要缩放；{MH("d")} 翻 4 倍，除数翻 2 倍。</div>')


if __name__ == '__main__':
    deck.main()
