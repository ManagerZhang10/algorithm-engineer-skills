# xhs43 脚本参考

写第一页之前读。所有东西都在 `scripts/xhs43.py` 一个文件里，只用 Python 标准库。

## 文件

| 文件 | 作用 |
|---|---|
| `scripts/xhs43.py` | 库 + 命令行：页面框架、SVG / 公式 helper、Chrome 截图、手机字号自查、文案字数 |
| `scripts/example_deck.py` | 示例 deck（3 页），`xhs43.py new` 会把它复制成项目里的 `build.py` |

## 命令行

| 命令 | 做什么 |
|---|---|
| `python3 xhs43.py new DIR` | 在 DIR 建新 deck：`xhs43.py`（库的副本）、`build.py`（示例）、`文案.md`（模板）；已有文件不覆盖 |
| `python3 build.py` | 只生成 `deck.html` |
| `python3 build.py --png [页号…]` | 生成 + 逐页截图到 `png/01_xxx.png`，接着自动跑自查；有 `文案.md` 时顺带数字数 |
| `python3 build.py --check` | 只自查，不截图 |
| `python3 build.py --png --open` | 出图 + 自查后打开整套 PNG（macOS `open`，Linux `xdg-open`） |
| `python3 build.py --out DIR` | 输出到别的目录（默认是 `build.py` 所在目录） |
| `python3 xhs43.py check deck.html` | 对任意本框架的 deck 做自查 |
| `python3 xhs43.py copy 文案.md [页数]` | 只数文案字数、列出「0X ·」段 |

退出码：自查或字数有 ✗ 时为 1，方便放进脚本里判断。

## 写一页

```python
import xhs43
from xhs43 import T, R, L, ARROW, svg, M, MH, FRAC, mwidth, INK, MUTED, FAINT, GRID, ACC, ACC_BG, RED

deck = xhs43.Deck(title='系列 · 主题', accent='#0071E3')

@deck.page('公式', '注意力为什么要<span class="acc">除以 ' + MH(r'\sqrt{d}') + '</span>')
def p1(W, H):                       # W×H = 1328×928，白卡内部的坐标系
    b = []
    b.append(M(64, 150, r'\text{softmax}\Big(\frac{QK^{\top}}{\sqrt{d}}\Big) V', 60))
    b.append(M(64, 236, r'结论：除以 \sqrt{d}，尺度拉回 1', 44, ACC, 600))
    return svg(W, H, b)

@deck.page('表格', '换几个数算一遍', html=True)   # html=True：返回 HTML 片段，放进白卡的 .html 容器
def p2(W, H):
    return '<table>…</table>'

deck.main()
```

- `name` 只写内容名，文件名自动按页序加 `01_` 前缀。
- 标题是一段 HTML：`<span class="acc">` 强调色、`<span class="thin">` 灰色细体、`MH(...)` 公式。
- 换强调色只改 `Deck(accent=...)`；图里一律用 `ACC` / `ACC_BG` 常量，输出时统一替换成新颜色和它的浅底色。
- 版式常量（边距、标题字号、手机宽度、最小字号）在 `xhs43.py` 顶部，改了对所有页生效。

## SVG helper

| 函数 | 说明 |
|---|---|
| `T(x, y, s, size=32, fill=INK, w=None, anchor=None, mono=False, extra='')` | 普通文字；`w` 字重，`anchor` 取 `'middle'` / `'end'` |
| `M(x, y, s, size=40, fill=INK, w=None, anchor=None)` | 公式 / 中英混排文字，语法见下 |
| `FRAC(x, y, num, den, size=40)` | 单独一个分式，返回 `(svg, 宽度)`；一般直接在 `M` 里写 `\frac` |
| `mwidth(s, size)` | 估算一段 `M` 文字的宽度，用来在同一行接着往右排 |
| `R(x, y, w, h, fill, rx, extra)` / `L(x1, y1, x2, y2, stroke, sw, extra)` | 矩形 / 线 |
| `ARROW(x1, y1, x2, y2, stroke=MUTED, sw=3)` | 带箭头的线；`stroke=ACC` 时箭头也是强调色 |
| `svg(W, H, body)` | 把元素列表包成撑满白卡的 SVG |

`y` 都是文字基线。颜色常量：`INK` 正文黑、`MUTED` 次要灰、`FAINT` 更淡的灰、`GRID` 分隔线、
`ACC` / `ACC_BG` 强调色和它的浅底、`RED` 只给「不行 / 错」。

## 公式语法（`M` 和 `MH` 共用）

| 写法 | 效果 |
|---|---|
| `x^{2}` `x^2` `x_{i}` `x_i` `x_i^2` | 上下标；下标 + 上标叠放；可嵌套 `e^{x_{t}}` |
| `\frac{a}{b}` | 竖排分式，可嵌套 |
| `\sqrt{d}` | 根号（SVG 里画成路径，不依赖字体） |
| `\Big( … \Big)`、`\big(`、`\left( … \right)` | 放大的括号（两档，不会自动量高度） |
| `\theta \pi \alpha \Delta …` | 希腊字母：小写斜体，大写正体 |
| `\times \cdot \approx \le \ge \ne \to \sum \infty \top \in …` | 符号 |
| `\text{…}` `\mathrm{…}` | 正体（不斜）；中文在哪儿都是无衬线正体 |
| `\mathbf{…}` `\mathbb{R}` | 粗体 / 黑板体 |

自动规则：

- 单个拉丁字母、小写希腊字母斜体；数字、大写希腊字母、`sin cos log exp max min softmax` 等函数名正体。
- `= + − × ≈ → ≤ ≥ ·` 等运算符两边自动留空（上下标里不留，开头和括号后的负号不留）。
- `-` 自动换成真正的减号 `−`。
- 普通空格**原样保留**（方便中英混排），这点和 LaTeX 不同；`\命令` 后面的一个空格会被吞掉，和 LaTeX 一样。
- 不认识的 `\命令` 按原样正体输出，渲染出来一眼能看见。

宽度是按字符估算的（没有真实字体度量），只影响分式 / 根号 / 叠放上下标的位置和 `mwidth`；
个别长式子在 PNG 里看着偏了，就手动调 x。

## 自查规则

`--png` / `--check` 用无头 Chrome 打开 `deck.html?measure=1`，逐页量出每段文字的实际渲染字号
（SVG 文字乘上 viewBox 缩放），换算到 1440 画布和约 920px 手机宽度。

| 检查 | 判定 |
|---|---|
| 白卡里的正文 < 28px | ✗ 失败；元素带 `data-small-ok=""` 时只警告 |
| 上下标 < 20px | ! 警告 |
| 文字超出白卡 | ✗ 失败 |
| 两个 `<text>` 外框交叠超过小的那个的 25% | ✗ 失败（压字） |
| 标题一行放不下 | ✗ 失败 |
| `文案.md` 超过 1000 字符（换行不计） | ✗ 失败 |
| 「0X ·」段号和图片张数对不上 | ! 警告 |

压字检查只比较 SVG `<text>` 的外框，线、框和文字之间的遮挡看不出来，所以出图后仍要打开 PNG 看一眼。
