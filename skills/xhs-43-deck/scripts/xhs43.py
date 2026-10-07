#!/usr/bin/env python3
"""xhs43：4:3（1440×1080）单文件 HTML keynote deck + 逐页 PNG，给小红书图文在手机上读。

只用 Python 标准库；截图和字号自查需要本机装 Chrome / Chromium / Edge（环境变量 CHROME 可指定路径）。

在 deck 脚本里这样用：

    import xhs43
    from xhs43 import T, R, L, ARROW, svg, M, MH, mwidth, INK, MUTED, ACC, ACC_BG

    deck = xhs43.Deck(title='我的 deck', accent='#0071E3')

    @deck.page('公式', '一个公式<span class="acc">三步</span>读完')
    def p1(W, H):                     # W×H 是图区（白卡）的尺寸，按这个坐标系画 SVG
        return svg(W, H, [M(60, 120, 'y = W x + b', 56)])

    deck.main()                       # python3 build.py [--png [页号...]] [--check] [--open] [--out DIR]

命令行：
    python3 xhs43.py new DIR          在 DIR 建一个新 deck（复制本库 + 示例 build.py + 文案.md 模板）
    python3 xhs43.py check deck.html  只做手机字号自查
    python3 xhs43.py copy 文案.md      数正文字数、列出「0X ·」段
"""
import html as _html
import json
import math
import os
import re
import shutil
import subprocess
import sys

# ============================================================== 画幅与配色（可替换的默认值）
DECK_W, DECK_H = 1440, 1080           # 4:3，固定
PAD_T, PAD_X, PAD_B = 34, 56, 34      # 上 / 左右 / 下边距
TITLE_SIZE, TITLE_H, GAP = 64, 74, 22  # 标题字号、标题行高、标题到白卡的间距
PHONE_W = 920                         # 手机上图片实际显示宽度（px，约 1080 宽屏幕减去边距）
MIN_FIG_PX = 28                       # 图内文字最小字号（1440 宽画布上）
MIN_SCRIPT_PX = 20                    # 上下标最小字号（低于它只警告）

INK, MUTED, FAINT, LINE, CARD, BG = '#1D1D1F', '#6E6E73', '#A1A1A6', '#D2D2D7', '#FFFFFF', '#F5F5F7'
GRID = '#E5E5EA'                      # 浅分隔线 / 网格
ACC, ACC_BG = '#0071E3', '#E8F0FE'    # 强调色占位：图里一律用这两个常量，Deck(accent=…) 在输出时统一替换
RED = '#D0342C'                       # 只给「错 / 不行」用，别当第二强调色

SANS = '"PingFang SC","Hiragino Sans GB","Noto Sans CJK SC","Microsoft YaHei","Helvetica Neue",Arial,sans-serif'
MONO = '"SF Mono",Menlo,"JetBrains Mono",Consolas,monospace'
MATH_FONT = "'STIX Two Text','STIX Two Math','STIXGeneral','Times New Roman',Times,serif"


# ============================================================== SVG 小工具
def _attrs(w=None, anchor=None, mono=False, extra=''):
    a = f' font-weight="{w}"' if w else ''
    a += f' text-anchor="{anchor}"' if anchor else ''
    a += ' class="mono"' if mono else ''
    return a + extra


def T(x, y, s, size=32, fill=INK, w=None, anchor=None, mono=False, extra=''):
    """普通文字（不做公式排版）。s 原样进 SVG，需要的话自己转义 < & 。"""
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}"{_attrs(w, anchor, mono, extra)}>{s}</text>'


def R(x, y, w, h, fill=BG, rx=0, extra=''):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" fill="{fill}"{extra}/>'


def L(x1, y1, x2, y2, stroke=INK, sw=2, extra=''):
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{sw}"{extra}/>'


def ARROW(x1, y1, x2, y2, stroke=MUTED, sw=3, extra=''):
    """带箭头的直线；颜色是 ACC 时用强调色箭头，其余用灰箭头。"""
    mk = 'xa' if stroke == ACC else 'xg'
    return L(x1, y1, x2, y2, stroke, sw, f' marker-end="url(#{mk})"{extra}')


def svg(W, H, body):
    """把一组元素包成撑满图区的 SVG；W×H 就是 page 函数拿到的图区尺寸。"""
    return (f'<svg class="sv" viewBox="0 0 {W:.0f} {H:.0f}" xmlns="http://www.w3.org/2000/svg" '
            f'preserveAspectRatio="xMidYMid meet">{"".join(body)}</svg>')


# ============================================================== 公式排版（离线，仿 LaTeX 渲染效果）
# 写法是 LaTeX 的一个小子集：
#   x^{2}  x^2  x_{i}  x_i  x_i^2     上下标（可嵌套，下标+上标会叠在一起）
#   \frac{分子}{分母}                  竖排分式（可嵌套）
#   \sqrt{…}                          根号（带顶线）
#   \theta \pi \alpha … \times \cdot \approx \le \ge \ne \to \infty \sum …   符号
#   \text{…} \mathrm{…}               正体（不斜）；中文无论在哪都走无衬线正体
#   \, \; \quad                       空白
# 自动规则（与 LaTeX 一致）：单个拉丁字母、小写希腊字母斜体；数字、运算符、大写希腊字母、
# sin / cos / log / exp / softmax 等函数名正体。空格原样保留（方便中英混排），这一点与 LaTeX 不同。
GREEK = {
    'alpha': 'α', 'beta': 'β', 'gamma': 'γ', 'delta': 'δ', 'epsilon': 'ε', 'varepsilon': 'ε', 'zeta': 'ζ',
    'eta': 'η', 'theta': 'θ', 'iota': 'ι', 'kappa': 'κ', 'lambda': 'λ', 'mu': 'μ', 'nu': 'ν', 'xi': 'ξ',
    'pi': 'π', 'rho': 'ρ', 'sigma': 'σ', 'tau': 'τ', 'phi': 'φ', 'varphi': 'φ', 'chi': 'χ', 'psi': 'ψ',
    'omega': 'ω', 'Gamma': 'Γ', 'Delta': 'Δ', 'Theta': 'Θ', 'Lambda': 'Λ', 'Pi': 'Π', 'Sigma': 'Σ',
    'Phi': 'Φ', 'Psi': 'Ψ', 'Omega': 'Ω',
}
SYMS = {
    'times': '×', 'cdot': '·', 'div': '÷', 'pm': '±', 'approx': '≈', 'le': '≤', 'leq': '≤', 'ge': '≥',
    'geq': '≥', 'ne': '≠', 'neq': '≠', 'to': '→', 'rightarrow': '→', 'leftarrow': '←', 'Rightarrow': '⇒',
    'infty': '∞', 'sum': '∑', 'prod': '∏', 'int': '∫', 'partial': '∂', 'nabla': '∇', 'in': '∈',
    'sim': '∼', 'propto': '∝', 'ldots': '…', 'cdots': '⋯', 'mathbb{R}': 'ℝ', 'R': 'ℝ', 'top': '⊤',
    'odot': '⊙', 'otimes': '⊗', 'oplus': '⊕', 'langle': '⟨', 'rangle': '⟩', 'lVert': '‖', 'rVert': '‖',
    ',': ' ', ';': ' ', 'quad': '  ', 'qquad': '    ', '{': '{', '}': '}', '%': '%', '#': '#', '_': '_',
}
FUNCS = ('softmax', 'sigmoid', 'argmax', 'argmin', 'concat', 'sin', 'cos', 'tan', 'log', 'exp', 'max', 'min',
         'lim', 'det', 'Attn', 'ln', 'mod')
SUP_SCALE, SUP_UP, SUB_DOWN = 0.62, 0.42, 0.22
SQRT_GLYPH, SQRT_TOP = 0.56, 0.86          # 根号（画成路径）的宽度、顶线高度，单位 em


def _is_cjk(c):
    return ord(c) > 0x2E80 and c not in '−' and not ('Ͱ' <= c <= 'Ͽ')


def _group(s, k):
    """s[k] 是 '{'，返回 (组内文字, 组后位置)"""
    depth, j = 0, k
    while j < len(s):
        if s[j] == '{':
            depth += 1
        elif s[j] == '}':
            depth -= 1
            if depth == 0:
                return s[k + 1:j], j + 1
        j += 1
    raise ValueError(f'公式里花括号没配对：{s!r}')


def _arg(s, k):
    """读一个参数：{…} 或单个字符（或 \\命令）"""
    if k < len(s) and s[k] == '{':
        return _group(s, k)
    if k < len(s) and s[k] == '\\':
        m = re.match(r'\\([A-Za-z]+|.)', s[k:])
        return s[k:k + m.end()], k + m.end()
    return s[k:k + 1], k + 1


OPS = set('=+−×÷≈≤≥≠→←⇒±·∼∝∈')        # 二元运算 / 关系符：两边自动留空（上下标里不留）
OPENERS = set('([{⟨|‖,')
OP_SPACE = '\u2005'                   # 四分之一 em 的定宽空格；普通空格跟在上下标后面会被 SVG 吞掉


def parse(s, script=False):
    """公式串 → 节点列表。节点：('t', 文字, 类别) / ('sup'|'sub', 子列表) / ('frac', 分子, 分母) / ('sqrt', 子列表)
    / ('big', 括号, 倍数) / ('bold', 子列表)。类别：var 斜体衬线 / rm 正体衬线 / cjk 中文无衬线"""
    out, k = [], 0
    eat_space = False

    def add(txt, kind):
        nonlocal eat_space
        if txt == ' ' and eat_space:
            return
        eat_space = False
        if len(txt) == 1 and txt in OPS and not script:
            j = len(out) - 1
            while j >= 0 and out[j][0] == 't' and not out[j][1].strip(' \u2005'):
                j -= 1                                   # 跳过纯空格节点找前一个实际符号
            prev = (out[j][1].rstrip(' \u2005') if out[j][0] == 't' else 'x') if j >= 0 else ''
            unary = txt in '−+±' and (not prev or prev[-1] in OPS or prev[-1] in OPENERS)
            if not unary and out:
                del out[j + 1:]
                if out and out[-1][0] == 't':
                    out[-1] = ('t', out[-1][1].rstrip(' \u2005'), out[-1][2])
                txt = OP_SPACE + txt + OP_SPACE
                eat_space = True
        if out and out[-1][0] == 't' and out[-1][2] == kind:
            out[-1] = ('t', out[-1][1] + txt, kind)
        else:
            out.append(('t', txt, kind))

    while k < len(s):
        c = s[k]
        if c in '^_':
            body, k = _arg(s, k + 1)
            out.append(('sup' if c == '^' else 'sub', parse(body, True)))
            continue
        if c == '\\':
            m = re.match(r'\\([A-Za-z]+|.)', s[k:])
            name = m.group(1)
            k += m.end()
            if name.isalpha() and k < len(s) and s[k] == ' ':
                k += 1                          # 和 LaTeX 一样，命令后面的一个空格吞掉
            if name in ('big', 'Big', 'bigg', 'Bigg', 'left', 'right'):
                if k < len(s):
                    ch, k = _arg(s, k)
                    ch = {'\\{': '{', '\\}': '}', '\\|': '‖', '.': ''}.get(ch, ch)
                    if ch:
                        out.append(('big', ch, 1.25 if name in ('big', 'left', 'right') else 1.45))
                continue
            if name == 'frac':
                a, k = _arg(s, k)
                b, k = _arg(s, k)
                out.append(('frac', parse(a, script), parse(b, script)))
            elif name == 'sqrt':
                a, k = _arg(s, k)
                out.append(('sqrt', parse(a, script)))
            elif name in ('text', 'mathrm', 'operatorname'):
                a, k = _arg(s, k)
                for ch in a:
                    add(ch, 'cjk' if _is_cjk(ch) else 'rm')
            elif name in ('mathbf', 'boldsymbol'):
                a, k = _arg(s, k)
                out.append(('bold', parse(a, script)))
            elif name == 'mathbb':
                a, k = _arg(s, k)
                add({'R': 'ℝ', 'N': 'ℕ', 'Z': 'ℤ', 'E': '𝔼'}.get(a, a), 'rm')
            elif name in GREEK:
                g = GREEK[name]
                add(g, 'var' if g.islower() else 'rm')
            elif name in SYMS:
                add(SYMS[name], 'rm')
            elif name in FUNCS:
                add(name, 'rm')
            else:
                add(name, 'rm')               # 不认识的命令按正体原样输出，渲染出来一眼能看见
            continue
        if c in '{}':                          # 裸花括号只做分组
            k += 1
            continue
        fn = next((f for f in FUNCS if s.startswith(f, k) and not s[k + len(f):k + len(f) + 1].isalpha()
                   and (k == 0 or not s[k - 1].isalpha())), None)
        if fn:
            add(fn, 'rm')
            k += len(fn)
            continue
        if c == '-':
            c = '−'
        if _is_cjk(c):
            kind = 'cjk'
        elif c.isalpha() and (c.isascii() or c.islower()):
            kind = 'var'
        else:
            kind = 'rm'
        add(c, kind)
        k += 1
    return out


def _cw(c, kind):
    """单个字符的估算宽度（单位：em）。只用于排分式、根号、上下标叠放的位置。"""
    if kind == 'cjk':
        return 1.0
    if c in ' \u2005':
        return 0.25
    if c in '×÷=≈+−→←≤≥≠±∼∝⇒⊙⊗⊕':
        return 0.68
    if c in '()[]|‖⟨⟩{}':
        return 0.34
    if c in ',.;:·、':
        return 0.28
    if c in '∑∏∫':
        return 0.8
    if c.isdigit():
        return 0.5
    if c in 'mwMWΩ':
        return 0.8
    if c in 'iljftrI':
        return 0.32
    if c.isupper():
        return 0.66
    return 0.52


def _width(nodes, size):
    w = 0.0
    for n in nodes:
        if n[0] == 't':
            w += sum(_cw(c, n[2]) for c in n[1]) * size
        elif n[0] in ('sup', 'sub'):
            w += _width(n[1], size * SUP_SCALE)
        elif n[0] == 'frac':
            w += max(_width(n[1], size * .9), _width(n[2], size * .9)) + size * 0.45
        elif n[0] == 'sqrt':
            w += _width(n[1], size) + size * (SQRT_GLYPH + 0.08)
        elif n[0] == 'bold':
            w += _width(n[1], size) * 1.05
        elif n[0] == 'big':
            w += sum(_cw(c, 'rm') for c in n[1]) * size * n[2] + size * 0.06
    # 下标紧跟上标（或反过来）会叠放，只算宽的那个
    for a, b in zip(nodes, nodes[1:]):
        if {a[0], b[0]} == {'sup', 'sub'}:
            w -= min(_width(a[1], size * SUP_SCALE), _width(b[1], size * SUP_SCALE))
    return w


def mwidth(s, size):
    """估算一段公式的宽度（px），用来接着往右排东西。"""
    return _width(parse(s), size)


def _spans(nodes, size, off, bold, script, out):
    """把不含分式 / 根号的节点摊平成 span 列表：每项 (文字, 类别, 字号, 竖直偏移, 粗体, 是否上下标, dx)"""
    prev = None
    for n in nodes:
        if n[0] == 't':
            out.append([n[1], n[2], size, off, bold, script, 0.0])
        elif n[0] in ('sup', 'sub'):
            sub = size * SUP_SCALE
            start = len(out)
            _spans(n[1], sub, off + (-SUP_UP if n[0] == 'sup' else SUB_DOWN) * size, bold, True, out)
            if prev is not None and {prev[0], n[0]} == {'sup', 'sub'} and len(out) > start:
                out[start][6] = -_width(prev[1], sub)        # x_i^2：退回去和前一个脚标叠放
        elif n[0] == 'bold':
            _spans(n[1], size, off, True, script, out)
        elif n[0] == 'big':                                   # 放大的括号，略往下沉以对齐分式中线
            out.append([n[1], 'rm', size * n[2], off + (n[2] - 1) * 0.36 * size, bold, script, size * 0.06])
        prev = n
    return out


def _line(x, y, nodes, size, fill, w):
    """一行（不含分式 / 根号）→ 一个 <text>，上下标用 tspan 的 dy 抬降"""
    parts, cur = [], 0.0
    for txt, kind, sz, off, bold, script, dx in _spans(nodes, size, 0.0, False, False, []):
        cls = {'var': 'm mi', 'rm': 'm', 'cjk': ''}[kind] + (' ms' if script else '')
        st = f' class="{cls.strip()}"' if cls.strip() else ''
        if bold:
            st += ' font-weight="700"'
        if abs(sz - size) > .01:
            st += f' font-size="{sz:.1f}"'
        if dx:
            st += f' dx="{dx:.1f}"'
        if abs(off - cur) > .01:
            st += f' dy="{off - cur:.1f}"'
            cur = off
        parts.append(f'<tspan{st}>{_html.escape(txt, quote=False)}</tspan>')
    wa = f' font-weight="{w}"' if w else ''
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size:.1f}" fill="{fill}"{wa}>{"".join(parts)}</text>'


def _render(x, y, nodes, size, fill, w):
    """按块（普通行 / 分式 / 根号）从左往右排，返回 (svg 串, 宽度)"""
    out, cx, run = [], x, []

    def flush():
        nonlocal cx, run
        if run:
            out.append(_line(cx, y, run, size, fill, w))
            cx += _width(run, size)
            run = []

    for n in nodes:
        if n[0] == 'frac':
            flush()
            fs = size * .9
            wn, wd = _width(n[1], fs), _width(n[2], fs)
            wf = max(wn, wd) + size * 0.3
            x0 = cx + size * 0.08
            bar = y - size * 0.3
            num_y = bar - size * 0.26
            den_y = bar + size * 0.84
            sn, _ = _render(x0 + (wf - wn) / 2, num_y, n[1], fs, fill, w)
            sd, _ = _render(x0 + (wf - wd) / 2, den_y, n[2], fs, fill, w)
            out.append(sn + L(x0, bar, x0 + wf, bar, fill, max(2, size / 16)) + sd)
            cx = x0 + wf + size * 0.08
        elif n[0] == 'sqrt':
            flush()
            wi = _width(n[1], size)
            x0 = cx + size * SQRT_GLYPH
            top, s_ = y - size * SQRT_TOP, size
            out.append(f'<path d="M{cx + .04 * s_:.1f},{y - .34 * s_:.1f} L{cx + .14 * s_:.1f},{y - .40 * s_:.1f} '
                       f'L{cx + .30 * s_:.1f},{y + .14 * s_:.1f} L{x0 - .04 * s_:.1f},{top:.1f} H{x0 + wi + .06 * s_:.1f}" '
                       f'fill="none" stroke="{fill}" stroke-width="{max(2, size / 17):.1f}" stroke-linejoin="miter"/>')
            s, _ = _render(x0, y, n[1], size, fill, w)
            out.append(s)
            cx = x0 + wi + size * 0.08
        else:
            run.append(n)
    flush()
    return ''.join(out), cx - x


def M(x, y, s, size=40, fill=INK, w=None, anchor=None):
    """SVG 里的公式 / 中英混排文字。y 是基线；anchor 取 None | 'middle' | 'end'。"""
    nodes = parse(s)
    if anchor in ('middle', 'end'):
        wid = _width(nodes, size)
        x -= wid / 2 if anchor == 'middle' else wid
    body, _ = _render(x, y, nodes, size, fill, w)
    return f'<g class="mx">{body}</g>'


def FRAC(x, y, num, den, size=40, fill=INK, w=None):
    """兼容写法：单独一个竖排分式，返回 (svg, 宽度)。等价于 M(x, y, r'\\frac{num}{den}')。"""
    nodes = [('frac', parse(num), parse(den))]
    body, wid = _render(x, y, nodes, size, fill, w)
    return f'<g class="mx">{body}</g>', wid


def _html_nodes(nodes):
    out = []
    for n in nodes:
        if n[0] == 't':
            t = _html.escape(n[1], quote=False)
            out.append({'var': f'<i class="mv">{t}</i>', 'rm': f'<span class="mr">{t}</span>', 'cjk': t}[n[2]])
        elif n[0] == 'sup':
            out.append(f'<sup>{_html_nodes(n[1])}</sup>')
        elif n[0] == 'sub':
            out.append(f'<sub>{_html_nodes(n[1])}</sub>')
        elif n[0] == 'frac':
            out.append(f'<span class="mf"><span>{_html_nodes(n[1])}</span><span>{_html_nodes(n[2])}</span></span>')
        elif n[0] == 'sqrt':
            out.append(f'<span class="msq"><svg viewBox="0 0 10 20" preserveAspectRatio="none" aria-hidden="true">'
                       f'<path d="M1,12 L3,11 L5.5,19.5 L9.6,.6 H10" vector-effect="non-scaling-stroke"/></svg>'
                       f'<span class="mq">{_html_nodes(n[1])}</span></span>')
        elif n[0] == 'bold':
            out.append(f'<b>{_html_nodes(n[1])}</b>')
        elif n[0] == 'big':
            out.append(f'<span class="mr" style="font-size:{n[2]:.2f}em;vertical-align:-.1em">{_html.escape(n[1])}</span>')
    return ''.join(out)


def MH(s):
    """HTML 里的公式（标题、HTML 文字块用）。返回 <span class="mx">…</span>。"""
    return f'<span class="mx">{_html_nodes(parse(s))}</span>'


# ============================================================== 页面框架
FRAME_CSS = r'''
:root{--bg:%(BG)s;--ink:%(INK)s;--muted:%(MUTED)s;--line:%(LINE)s;--card:%(CARD)s;--accent:%(ACC)s;
  --font:%(SANS)s;--mono:%(MONO)s;--math:%(MATH)s}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%%;background:var(--bg);color:var(--ink);font-family:var(--font);overflow:hidden}
#stage{position:absolute;left:50%%;top:50%%;width:%(W)dpx;height:%(H)dpx;transform:translate(-50%%,-50%%);transform-origin:center;background:var(--bg)}
.slide{position:absolute;inset:0;padding:%(PT)dpx %(PX)dpx %(PB)dpx;display:none;flex-direction:column}
.slide.active{display:flex}
.slide h1{font-size:%(TS)dpx;font-weight:600;letter-spacing:-.01em;line-height:%(TH)dpx;white-space:nowrap;flex:none}
h1 .acc,.acc{color:var(--accent)}
h1 .thin{font-weight:400;color:var(--muted)}
.figbox{flex:1;min-height:0;position:relative;margin-top:%(GAP)dpx;background:var(--card);border-radius:24px;box-shadow:0 10px 36px rgba(0,0,0,.05);overflow:hidden}
.figbox>svg{position:absolute;inset:0;width:100%%;height:100%%}
.figbox>.html{position:absolute;inset:0;padding:40px 48px;font-size:36px;line-height:1.45}
.sv text{font-family:var(--font)}
.sv .mono{font-family:var(--mono)}
.sv .m{font-family:var(--math)}.sv .mi{font-style:italic}
/* 公式（HTML 版） */
.mx{white-space:nowrap}
.mx .mv{font-family:var(--math);font-style:italic}
.mx .mr{font-family:var(--math)}
.mx sup,.mx sub{font-size:.62em;line-height:0;position:relative;vertical-align:baseline}
.mx sup{top:-.62em}.mx sub{top:.24em}
.mx .mf{display:inline-flex;flex-direction:column;vertical-align:middle;text-align:center;font-size:.9em;margin:0 .1em}
.mx .mf>span{padding:0 .15em;line-height:1.15}
.mx .mf>span:first-child{border-bottom:.06em solid currentColor}
.mx .msq{display:inline-flex;align-items:stretch;vertical-align:bottom}
.mx .msq svg{width:.55em;flex:none;overflow:visible}.mx .msq path{fill:none;stroke:currentColor;stroke-width:.06em}
.mx .mq{border-top:.06em solid currentColor;padding:0 .06em 0 .04em;line-height:1.1}
/* 导航：左下角小按钮，截图时整个隐藏 */
#nav{position:fixed;left:12px;bottom:12px;display:flex;gap:6px;align-items:center;font:14px var(--mono);color:#fff;background:rgba(29,29,31,.72);border-radius:9px;padding:4px 6px;opacity:.25;transition:opacity .2s;z-index:9;user-select:none}
#nav:hover{opacity:1}
#nav b{width:26px;height:26px;display:flex;align-items:center;justify-content:center;border-radius:6px;cursor:pointer;font-weight:400}
#nav b:hover{background:rgba(255,255,255,.2)}
body.cap #nav{display:none!important}
'''

MARKERS = ('<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>'
           '<marker id="xg" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto">'
           f'<path d="M0,0 L10,5 L0,10 z" fill="{MUTED}"/></marker>'
           '<marker id="xa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto">'
           f'<path d="M0,0 L10,5 L0,10 z" fill="{ACC}"/></marker></defs></svg>')

# 键盘翻页 + ?cap=1 隐藏导航 + ?measure=1 逐页量字号（结果写进 <pre id="__measure">，供 --dump-dom 读取）
FRAME_JS = r'''
(function(){
  const W=%(W)d,H=%(H)d,stage=document.getElementById('stage'),slides=[...document.querySelectorAll('.slide')];
  const q=location.search; if(/[?&]cap=1/.test(q)||/[?&]measure=1/.test(q)) document.body.classList.add('cap');
  let cur=-1, scale=1;
  function fit(){ scale=Math.min(innerWidth/W,innerHeight/H); stage.style.transform=`translate(-50%%,-50%%) scale(${scale})`; }
  function show(n){ n=Math.max(0,Math.min(slides.length-1,n)); slides.forEach((s,k)=>s.classList.toggle('active',k===n));
    cur=n; history.replaceState(null,'','#'+(n+1)); document.getElementById('pg').textContent=(n+1)+' / '+slides.length; }
  addEventListener('keydown',e=>{
    if(['ArrowRight','ArrowDown','PageDown',' ','Enter'].includes(e.key)){e.preventDefault();show(cur+1);}
    else if(['ArrowLeft','ArrowUp','PageUp','Backspace'].includes(e.key)){e.preventDefault();show(cur-1);}
    else if(e.key==='Home')show(0); else if(e.key==='End')show(slides.length-1);
    else if(e.key==='f'||e.key==='F'){ if(document.fullscreenElement)document.exitFullscreen(); else document.documentElement.requestFullscreen().catch(()=>{}); }
  });
  document.getElementById('nb-prev').onclick=()=>show(cur-1);
  document.getElementById('nb-next').onclick=()=>show(cur+1);
  addEventListener('resize',fit); fit();
  const h=parseInt((location.hash||'#1').slice(1),10); show(isNaN(h)?0:h-1);
  function measure(){
    const res=[];
    slides.forEach((sl,k)=>{
      show(k);
      const fb=sl.querySelector('.figbox'), fr=fb?fb.getBoundingClientRect():null, items=[];
      const tw=document.createTreeWalker(sl,NodeFilter.SHOW_TEXT); let n;
      while((n=tw.nextNode())){
        const t=n.nodeValue.trim(); if(!t) continue;
        const el=n.parentElement, cs=getComputedStyle(el);
        if(cs.display==='none'||cs.visibility==='hidden'||+cs.opacity===0) continue;
        let fs=parseFloat(cs.fontSize), r;
        const te=el.closest('text');
        if(te){ const m=te.getScreenCTM(); fs*=Math.hypot(m.a,m.b); r=el.getBoundingClientRect(); }
        else { const rg=document.createRange(); rg.selectNodeContents(n); r=rg.getBoundingClientRect(); }
        fs/=scale;
        const inFig=!!(fb&&fb.contains(el));
        const out=inFig&&(r.left<fr.left-1||r.right>fr.right+1||r.top<fr.top-1||r.bottom>fr.bottom+1);
        items.push({t:t.slice(0,30),fs:Math.round(fs*10)/10,script:!!el.closest('.ms,sup,sub'),
                    ok:!!el.closest('[data-small-ok]'),fig:inFig,out:out});
      }
      // 文字互相压住：两个 <text> 的外框交叠超过小的那个的 25%%
      const ts=[...sl.querySelectorAll('.figbox text')].filter(t=>t.textContent.trim()).map(t=>[t,t.getBoundingClientRect()]), ov=[];
      for(let i=0;i<ts.length;i++) for(let j=i+1;j<ts.length;j++){
        const a=ts[i][1], b=ts[j][1], w=Math.min(a.right,b.right)-Math.max(a.left,b.left), h=Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top);
        if(w>0&&h>0&&w*h>0.25*Math.min(a.width*a.height,b.width*b.height)) ov.push([ts[i][0].textContent.trim().slice(0,12),ts[j][0].textContent.trim().slice(0,12)]);
      }
      const h1=sl.querySelector('h1');
      res.push({page:k+1,items:items,overlaps:ov,titleOverflow:!!(h1&&h1.scrollWidth>h1.clientWidth+1)});
    });
    const pre=document.createElement('pre'); pre.id='__measure'; pre.textContent=JSON.stringify(res); document.body.appendChild(pre);
  }
  if(/[?&]measure=1/.test(q)) (document.fonts?document.fonts.ready:Promise.resolve()).then(()=>setTimeout(measure,50));
})();
'''


def _mix_white(hex_color, t=0.9):
    h = hex_color.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return '#%02X%02X%02X' % tuple(round(v + (255 - v) * t) for v in (r, g, b))


def strip_tags(s):
    return _html.unescape(re.sub(r'<[^>]+>', '', s))


class Deck:
    """一个 4:3 deck。用 @deck.page(名字, 标题HTML) 注册画图函数，最后 deck.main()。"""

    def __init__(self, title='deck', accent=ACC, out=None):
        self.title = title
        self.accent = accent
        self.pages = []                       # (名字, 标题 HTML, 画图函数, 选项)
        self.out = out or os.path.dirname(os.path.abspath(sys.argv[0]))

    def page(self, name, title_html, html=False):
        """注册一页。name 只写内容名（如 '公式'），文件名会自动按顺序加 01_ 前缀。
        html=True 时画图函数返回 HTML 片段（放进白卡的 .html 容器），否则返回 svg(...)。"""
        def deco(fn):
            self.pages.append((name, title_html, fn, {'html': html}))
            return fn
        return deco

    # ---------------------------------------------------------- 尺寸
    @staticmethod
    def fig_size():
        """图区（白卡）尺寸：1328 × 928"""
        return DECK_W - 2 * PAD_X, DECK_H - PAD_T - PAD_B - TITLE_H - GAP

    def file_names(self):
        return [f'{k:02d}_{name}' for k, (name, *_) in enumerate(self.pages, 1)]

    # ---------------------------------------------------------- 输出 HTML
    def render(self):
        fw, fh = self.fig_size()
        acc_bg = _mix_white(self.accent, 0.9)
        css = FRAME_CSS % dict(BG=BG, INK=INK, MUTED=MUTED, LINE=LINE, CARD=CARD, ACC=ACC, SANS=SANS, MONO=MONO,
                               MATH=MATH_FONT, W=DECK_W, H=DECK_H, PT=PAD_T, PX=PAD_X, PB=PAD_B, TS=TITLE_SIZE,
                               TH=TITLE_H, GAP=GAP)
        secs = []
        for fname, (name, title, fn, opt) in zip(self.file_names(), self.pages):
            body = fn(fw, fh)
            inner = f'<div class="html">{body}</div>' if opt['html'] else body
            secs.append(f'<section class="slide" data-name="{_html.escape(fname)}" '
                        f'data-title="{_html.escape(strip_tags(title))}">\n  <h1>{title}</h1>\n'
                        f'  <div class="figbox">{inner}</div>\n</section>\n')
        doc = ('<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
               f'<title>{_html.escape(self.title)}</title>\n'
               '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
               f'<style>{css}</style>\n</head>\n<body>\n<div id="stage">\n{MARKERS}\n{"".join(secs)}</div>\n'
               '<div id="nav"><b id="nb-prev">‹</b><span id="pg">1 / 1</span><b id="nb-next">›</b></div>\n'
               f'<script>{FRAME_JS % dict(W=DECK_W, H=DECK_H)}</script>\n</body>\n</html>\n')
        if self.accent.upper() != ACC.upper():
            doc = re.sub(re.escape(ACC), self.accent, doc, flags=re.I)
            doc = re.sub(re.escape(ACC_BG), acc_bg, doc, flags=re.I)
        return doc

    def build(self):
        os.makedirs(self.out, exist_ok=True)
        path = os.path.join(self.out, 'deck.html')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.render())
        print(path)
        return path

    # ---------------------------------------------------------- 命令行
    def main(self, argv=None):
        argv = sys.argv[1:] if argv is None else argv
        if '--out' in argv:
            i = argv.index('--out')
            self.out = os.path.abspath(argv[i + 1])
            argv = argv[:i] + argv[i + 2:]
        deck = self.build()
        rc = 0
        if '--png' in argv:
            only = [int(a) for a in argv if a.isdigit()] or None
            export_pngs(deck, os.path.join(self.out, 'png'), self.file_names(), only)
        if '--png' in argv or '--check' in argv:
            rc = check(deck)
            copy = os.path.join(self.out, '文案.md')
            if os.path.exists(copy):
                rc = max(rc, check_copy(copy, len(self.pages)))
        if '--open' in argv:                   # 交给用户看：打开整套 PNG（没出 PNG 就打开 deck.html）
            pngs = [os.path.join(self.out, 'png', n + '.png') for n in self.file_names()]
            pngs = [p for p in pngs if os.path.exists(p)] or [deck]
            opener = 'open' if sys.platform == 'darwin' else ('start' if os.name == 'nt' else 'xdg-open')
            subprocess.run([opener] + pngs, check=False, shell=(os.name == 'nt'))
        sys.exit(rc)


# ============================================================== Chrome：截图与量字号
def find_chrome():
    env = os.environ.get('CHROME')
    if env:
        return env
    for p in ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
              '/Applications/Chromium.app/Contents/MacOS/Chromium',
              '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
              r'C:\Program Files\Google\Chrome\Application\chrome.exe',
              r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'):
        if os.path.exists(p):
            return p
    for n in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome', 'microsoft-edge'):
        p = shutil.which(n)
        if p:
            return p
    sys.exit('找不到 Chrome / Chromium / Edge；装一个，或用环境变量 CHROME=/path/to/chrome 指定。')


def _chrome(args, capture=False):
    cmd = [find_chrome(), '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
           '--no-default-browser-check', '--virtual-time-budget=5000', '--force-device-scale-factor=1',
           f'--window-size={DECK_W},{DECK_H}'] + args
    r = subprocess.run(cmd, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False, timeout=120)
    return r.stdout.decode('utf-8', 'replace') if capture else None


def _uri(path):
    return 'file://' + os.path.abspath(path).replace(os.sep, '/')


def export_pngs(deck_html, out_dir, names, only=None):
    """逐页截图：out_dir/01_xxx.png …（1440×1080，导航隐藏）。整套重出时清掉编号已不存在的旧图。"""
    os.makedirs(out_dir, exist_ok=True)
    if only is None:
        keep = {n + '.png' for n in names}
        for f in os.listdir(out_dir):
            if re.match(r'^\d\d_.*\.png$', f) and f not in keep:
                os.remove(os.path.join(out_dir, f))
                print('删掉旧图', f)
    for k, name in enumerate(names, 1):
        if only and k not in only:
            continue
        png = os.path.join(out_dir, name + '.png')
        if os.path.exists(png):
            os.remove(png)
        _chrome([f'--screenshot={png}', f'{_uri(deck_html)}?cap=1#{k}'])
        print(png if os.path.exists(png) and os.path.getsize(png) else '✗ 截图失败 ' + png)


def measure(deck_html):
    dom = _chrome(['--dump-dom', f'{_uri(deck_html)}?measure=1#1'], capture=True)
    m = re.search(r'<pre id="__measure">(.*?)</pre>', dom or '', re.S)
    if not m:
        sys.exit('量字号失败：Chrome 没返回结果（页面 JS 报错？先在浏览器里打开 deck.html 看控制台）。')
    return json.loads(_html.unescape(m.group(1)))


def check(deck_html):
    """手机字号自查。返回 0 = 通过，1 = 有页不达标。
    规则：图内正文 < MIN_FIG_PX（28px @1440）判失败；上下标 < MIN_SCRIPT_PX 警告；
    文字出了白卡、两段文字互相压住、标题一行放不下判失败。元素带 data-small-ok 的小字只警告。"""
    pages = measure(deck_html)
    k = PHONE_W / DECK_W
    fail = 0
    print(f'\n手机字号自查（画布 {DECK_W} 宽 → 手机显示约 {PHONE_W} 宽，×{k:.2f}；图内最小 {MIN_FIG_PX}px）')
    print(f'{"页":>3}  {"图内最小":>8}  {"手机上":>6}  {"上下标最小":>8}  结果')
    for p in pages:
        fig = [i for i in p['items'] if i['fig'] and not i['script']]
        scr = [i for i in p['items'] if i['fig'] and i['script']]
        mn = min((i['fs'] for i in fig), default=0)
        ms = min((i['fs'] for i in scr), default=0)
        bad = [i for i in fig if i['fs'] < MIN_FIG_PX - 0.05 and not i['ok']]
        soft = [i for i in fig if i['fs'] < MIN_FIG_PX - 0.05 and i['ok']]
        sbad = [i for i in scr if i['fs'] < MIN_SCRIPT_PX - 0.05]
        outs = [i for i in p['items'] if i['out']]
        notes = []
        if bad:
            notes.append('✗ 小字 ' + '、'.join(f'「{i["t"]}」{i["fs"]:g}px' for i in bad[:4]))
        if outs:
            notes.append('✗ 出界 ' + '、'.join(f'「{i["t"]}」' for i in outs[:4]))
        if p['titleOverflow']:
            notes.append('✗ 标题一行放不下')
        if p.get('overlaps', []):
            notes.append('✗ 文字压字 ' + '、'.join(f'「{a}」×「{b}」' for a, b in p.get('overlaps', [])[:3]))
        if soft:
            notes.append('! 豁免小字 ' + '、'.join(f'「{i["t"]}」{i["fs"]:g}px' for i in soft[:3]))
        if sbad:
            notes.append('! 上下标偏小 ' + '、'.join(f'「{i["t"]}」{i["fs"]:g}px' for i in sbad[:3]))
        if bad or outs or p['titleOverflow'] or p.get('overlaps', []):
            fail = 1
        print(f'{p["page"]:>3}  {mn:>7g}px  {mn * k:>5.1f}px  {(f"{ms:g}px" if scr else "—"):>9}  '
              + ('；'.join(notes) if notes else '✓'))
    print('结论：' + ('有页不达标，改大字号 / 删标签 / 拆页后重跑' if fail else '全部达标') + '\n')
    return fail


# ============================================================== 文案
def check_copy(path, n_pages=None, limit=1000):
    """数小红书正文字数（含签名、话题；换行不计，口径以 App 为准），并核对「0X ·」段与页数。"""
    text = open(path, encoding='utf-8').read()
    n = len(text.replace('\r', '').replace('\n', ''))
    secs = re.findall(r'^\s*(\d{2})\s*·', text, re.M)
    print(f'文案 {os.path.basename(path)}：{n} 字符（上限 {limit}，换行不计）'
          + (' ✓' if n <= limit else f' ✗ 超出 {n - limit}'))
    rc = 0 if n <= limit else 1
    if secs:
        nums = [int(s) for s in secs]
        print(f'  「0X ·」段：{" ".join(secs)}')
        if n_pages and nums != list(range(1, n_pages + 1)):
            print(f'  ! 段号和图片 01–{n_pages:02d} 对不上，检查漏段 / 顺序')
    return rc


# ============================================================== 新建 deck
COPY_TEMPLATE = '''开头两三句：这期讲什么、先给结论。

01 · 第 1 张图讲什么，一两句。

02 · 第 2 张图讲什么，一两句。

--------------分割线--------------
签名一行
#话题1[话题]# #话题2[话题]#
'''


def new_deck(dst):
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(dst, exist_ok=True)
    for src, name in ((__file__, 'xhs43.py'), (os.path.join(here, 'example_deck.py'), 'build.py')):
        p = os.path.join(dst, name)
        if os.path.exists(p):
            print('已存在，跳过', p)
            continue
        shutil.copy(src, p)
        print(p)
    p = os.path.join(dst, '文案.md')
    if not os.path.exists(p):
        open(p, 'w', encoding='utf-8').write(COPY_TEMPLATE)
        print(p)
    print(f'\n下一步：cd {dst} && python3 build.py --png')


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == 'new':
        new_deck(os.path.abspath(a[1]))
    elif len(a) >= 2 and a[0] == 'check':
        sys.exit(check(os.path.abspath(a[1])))
    elif len(a) >= 2 and a[0] == 'copy':
        sys.exit(check_copy(a[1], int(a[2]) if len(a) > 2 else None))
    else:
        print(__doc__)
