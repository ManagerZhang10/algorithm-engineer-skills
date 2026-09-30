"""draw.io 模型架构图生成库（paper-arch-figure 技能）。版式不限：原语自由排，三段放大只是现成模板之一。

样式规则见本技能 references/style.md。
两套配色（可替换的默认值，改 PALETTES 即可）：
  paper —— STYLE.md 的五色语义（灰 IO / 蓝 Norm·注入 / 紫 时间步·条件 / 橙 注意力 / 绿 FFN）
  deck  —— 单一强调色版式：全灰块 + 强调蓝，和 keynote 风 deck 其他页一致
两套都遵守同一约定：hl=True 的块画蓝框，表示「这个模型独有的做法」。
"""
import html
import re


def _md(s):
    """转义后把 x_{t-1} / ℝ^{d} 转成真正的下标 / 上标；不带花括号的 _ 和 ^ 原样保留。"""
    s = html.escape(s)
    s = re.sub(r"_\{([^{}]*)\}", r"<sub>\1</sub>", s)
    return re.sub(r"\^\{([^{}]*)\}", r"<sup>\1</sup>", s)

FONT = "PingFang SC, Helvetica"   # 可替换：中文字体放第一位
STATE = {"frozen": " ❄️", "train": " 🔥"}   # 冻结 / 可训练标记，可替换
TRAP = {"top": "east", "bottom": "west", "right": "south", "left": "north"}   # 窄边 → draw.io direction

PALETTES = {
    "paper": {
        "io": "#E4E4E4", "norm": "#CFE0F7", "inject": "#CFE0F7", "cond": "#E2D3F5",
        "attn": "#FDE6C6", "core": "#F7C57A", "ffn": "#C8E6C4", "mod": "#E2D3F5",
        "white": "#FFFFFF", "seg_txt": "#D9D9D9", "seg_ref": "#CFE0F7", "seg_x": "#E2D3F5",
        "text": "#333333", "sub": "#777777", "edge": "#333333", "note_hot": "#E8931D",
        "panel_main": ("#F8F8F8", "#222222"), "panel_sub": ("#F5F5F5", "#9A9A9A"),
        "hl_stroke": "#0071E3", "hl_text": None,
    },
    "deck": {
        "io": "#F5F5F7", "norm": "#F5F5F7", "inject": "#F5F5F7", "cond": "#F5F5F7",
        "attn": "#F5F5F7", "core": "#E8E8ED", "ffn": "#F5F5F7", "mod": "#F5F5F7",
        "white": "#FFFFFF", "seg_txt": "#E8E8ED", "seg_ref": "#E8E8ED", "seg_x": "#E8E8ED",
        "text": "#1D1D1F", "sub": "#6E6E73", "edge": "#8E8E93", "note_hot": "#0071E3",
        "panel_main": ("#FBFBFD", "#1D1D1F"), "panel_sub": ("#FBFBFD", "#A1A1A6"),
        "hl_stroke": "#0071E3", "hl_text": "#0071E3", "hl_fill": "#E8F0FE",
    },
}


class Fig:
    def __init__(self, palette="paper"):
        self.P = PALETTES[palette]
        self.pal = palette
        self.cells = []
        self.n = 0
        self.geo = {}

    def _id(self):
        self.n += 1
        return f"c{self.n}"

    # ---------- 基本元素 ----------
    def box(self, x, y, w, h, label, role="io", sub=None, bold=False, hl=False,
            fs=13, stroke=None, sw=1.5, arc=18, dashed=False, id=None, fill=None, state=None, shape=None):
        """state="frozen" / "train" 在主文字后加 ❄️ / 🔥（冻结 / 可训练）；shape 是额外的 draw.io 形状样式前缀。"""
        P = self.P
        i = id or self._id()
        f = fill or P[role]
        col = P["text"]
        if hl and self.pal == "deck":
            f = P["hl_fill"]
            col = P["hl_text"]
        v = _md(label) + STATE.get(state, "")
        if bold or hl:
            v = f"<b>{v}</b>"
        if sub:
            sc = P["hl_text"] if (hl and P.get("hl_text")) else P["sub"]
            v += f'<br><font style="font-size:{max(fs-3,10)}px" color="{sc}">{_md(sub)}</font>'
        st_col = P["hl_stroke"] if hl else (stroke or "none")
        st_w = 2.2 if hl else sw
        st = ((shape or f"rounded=1;arcSize={arc};") + f"whiteSpace=wrap;html=1;strokeColor={st_col};strokeWidth={st_w};"
              f"fillColor={f};fontSize={fs};fontFamily={FONT};fontColor={col};")
        if dashed:
            st += "dashed=1;dashPattern=5 4;"
        self._v(i, v, st, x, y, w, h)
        self.geo[i] = (x, y, w, h)
        return i

    def text(self, x, y, w, h, label, fs=12, color=None, bold=False, align="center", id=None):
        i = id or self._id()
        c = color or self.P["sub"]
        v = _md(label).replace("\n", "<br>")
        if bold:
            v = f"<b>{v}</b>"
        st = (f"text;html=1;align={align};verticalAlign=middle;whiteSpace=wrap;fontSize={fs};"
              f"fontFamily={FONT};fontColor={c};")
        self._v(i, v, st, x, y, w, h)
        return i

    def plus(self, cx, cy, r=11, sym="+", id=None, fs=15):
        """白底黑边的运算圆：⊕ 默认，sym 可换成 × · © σ tanh 等。"""
        i = id or self._id()
        st = (f"ellipse;html=1;strokeColor={self.P['text']};strokeWidth=1.5;fillColor=#FFFFFF;"
              f"fontSize={fs};fontColor={self.P['text']};fontFamily=Helvetica;")
        self._v(i, sym, st, cx - r, cy - r, 2 * r, 2 * r)
        self.geo[i] = (cx - r, cy - r, 2 * r, 2 * r)
        return i

    def op(self, cx, cy, sym, r=11):
        """逐元素运算节点（× + σ tanh …），plus 的别名；文字长时自动缩字号。"""
        return self.plus(cx, cy, r, sym, fs=min(15, max(9, int(3.2 * r / len(sym)))))

    def node(self, cx, cy, r, label, role="io", sub=None, hl=False, fs=13, state=None):
        """填色圆：变量 / 张量（z、μ、σ、h_t）、神经元、图节点。"""
        return self.box(cx - r, cy - r, 2 * r, 2 * r, label, role, sub=sub, hl=hl, fs=fs, state=state, shape="ellipse;")

    def trap(self, x, y, w, h, label, role="io", narrow="top", ratio=0.3, sub=None, hl=False, fs=13, state=None):
        """梯形：降维 / 升维投影（LoRA 的 A、B，Adapter，自编码器）。narrow 是窄边在哪侧，ratio 是每侧收进的比例。"""
        return self.box(x, y, w, h, label, role, sub=sub, hl=hl, fs=fs, state=state,
                        shape=f"shape=trapezoid;perimeter=trapezoidPerimeter;size={ratio};direction={TRAP[narrow]};"
                              "anchorPointDirection=0;")  # 否则 sx/ex 连接点会跟着 direction 旋转

    def cuboid(self, x, y, w, h, depth=14, label="", role="io", below=None, fs=12):
        """立体特征图（CNN 的 C×H×W）：w 表示通道厚度、h 表示空间尺寸；below 写在底下（如 "6@28×28"）。"""
        i = self._id()
        st = (f"shape=cube;size={depth};darkOpacity=0.06;darkOpacity2=0.14;html=1;whiteSpace=wrap;strokeColor=#FFFFFF;"
              f"strokeWidth=1;fillColor={self.P[role]};fontSize={fs};fontFamily={FONT};fontColor={self.P['text']};")
        self._v(i, html.escape(label), st, x, y, w, h)
        self.geo[i] = (x, y, w, h)
        if below:
            self.text(x - 30, y + h + 4, w + 60, 16, below, fs=10.5)
        return i

    def fmaps(self, x, y, w, h, n=3, off=6, role="io", below=None, label=""):
        """一叠特征图（LeNet / AlexNet 原图那种错开叠放的方块）：(x, y) 是最前一张的左上角，后面的往右上错开。
        返回最前一张的 id，连线接它。"""
        for k in range(n - 1, 0, -1):
            self.box(x + k * off, y - k * off, w, h, "", role, arc=4, stroke="#FFFFFF", sw=1)
        i = self.box(x, y, w, h, label, role, arc=4, stroke="#FFFFFF", sw=1, fs=11)
        if below:
            self.text(x - 30, y + h + 4, w + (n - 1) * off + 60, 16, below, fs=10.5)
        return i

    def grid(self, x, y, rows, cols, cs, role_at, hl_at=None, label_at=None, gap=2, arc=10, fs=10):
        """格子矩阵：注意力 / mask / 相似度矩阵、patch 网格、窗口划分。
        role_at(r, c) 返回 role 或 None（None 画浅灰描边空格）；hl_at(r, c) 为真画蓝框；label_at(r, c) 返回格内文字。
        返回 ids[r][c]。"""
        ids = []
        for r in range(rows):
            row = []
            for c in range(cols):
                role = role_at(r, c)
                row.append(self.box(x + c * cs + gap / 2, y + r * cs + gap / 2, cs - gap, cs - gap,
                                    label_at(r, c) if label_at else "", role or "white", arc=arc, fs=fs,
                                    stroke=None if role else "#E0E0E0", sw=1, hl=bool(hl_at and hl_at(r, c))))
            ids.append(row)
        return ids

    def neurons(self, x, cy, layers, dx=90, dy=34, r=11, roles=None, labels=None):
        """神经元示意（MLP / 感知机）：layers=[3, 4, 2] 每层几个，自左向右，相邻层全连接细灰线。返回每层 id 列表。"""
        cols = []
        for k, n in enumerate(layers):
            role = roles[k] if roles else "io"
            ys = [cy + (j - (n - 1) / 2) * dy for j in range(n)]
            cols.append([self.node(x + k * dx, yy, r, labels[k][j] if labels else "", role, fs=11) for j, yy in enumerate(ys)])
        for a, b in zip(cols, cols[1:]):
            for s in a:
                for d in b:
                    self.edge(s, d, sx=1, sy=.5, ex=0, ey=.5, arrow=False, color="#B0B0B0", w=0.9)
        return cols

    def image(self, x, y, w, h, path):
        """嵌入一张真图（PNG / JPEG），用于扩散链、ViT 输入、编辑前后对比。图会写进 .drawio。"""
        import base64, pathlib
        pth = pathlib.Path(path)
        mime = "jpeg" if pth.suffix.lower() in (".jpg", ".jpeg") else "png"
        data = base64.b64encode(pth.read_bytes()).decode()
        i = self._id()
        self._v(i, "", f"shape=image;html=1;imageAspect=0;aspect=fixed;image=data:image/{mime},{data};", x, y, w, h)
        self.geo[i] = (x, y, w, h)
        return i

    def panel(self, x, y, w, h, main=True):
        f, s = self.P["panel_main" if main else "panel_sub"]
        st = f"rounded=1;arcSize=3;html=1;strokeColor={s};strokeWidth={2 if main else 1.8};fillColor={f};"
        self._v(self._id(), "", st, x, y, w, h)

    def seq(self, x, y, w, h, title, segs, fs=11):
        """一条序列：segs = [(label, role, weight, hl)]，role 取 seg_txt / seg_ref / seg_x / cond"""
        P = self.P
        c = self._id()
        st = f"rounded=1;arcSize=10;html=1;strokeColor=#9A9A9A;strokeWidth=1.3;fillColor=#FAFAFA;"
        self._v(c, "", st, x, y, w, h)
        self.geo[c] = (x, y, w, h)
        self.text(x, y + 2, w, 18, title, fs=11, color=P["sub"])
        tot = sum(s[2] for s in segs)
        gx, iw = x + 8, w - 16 - 5 * (len(segs) - 1)
        ids = []
        for seg in segs:
            lab, role, wt, hl = seg[:4]
            sub = seg[4] if len(seg) > 4 else None
            sw = iw * wt / tot
            ids.append(self.box(gx, y + 22, sw, h - 30, lab, role, sub=sub, fs=fs, arc=12, hl=hl))
            gx += sw + 5
        return c, ids

    def edge(self, src=None, tgt=None, pts=(), dashed=False, arrow=True, sx=None, sy=None,
             ex=None, ey=None, start=None, end=None, color=None, label=None, w=1.4):
        i = self._id()
        col = color or self.P["edge"]
        st = (f"edgeStyle=none;html=1;strokeColor={col};strokeWidth={w};endArrow={'block' if arrow else 'none'};"
              f"endFill=1;endSize=5;fontSize=11;fontFamily={FONT};fontColor={self.P['sub']};")
        if dashed:
            st += "dashed=1;dashPattern=6 5;"
        if sx is not None:
            st += f"exitX={sx};exitY={sy};exitDx=0;exitDy=0;"
        if ex is not None:
            st += f"entryX={ex};entryY={ey};entryDx=0;entryDy=0;"
        a = (f' source="{src}"' if src else "") + (f' target="{tgt}"' if tgt else "")
        v = f' value="{html.escape(label, quote=True)}"' if label else ""
        g = '<mxGeometry relative="1" as="geometry">'
        if start:
            g += f'<mxPoint x="{start[0]}" y="{start[1]}" as="sourcePoint"/>'
        if end:
            g += f'<mxPoint x="{end[0]}" y="{end[1]}" as="targetPoint"/>'
        if pts:
            g += '<Array as="points">' + "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in pts) + "</Array>"
        g += "</mxGeometry>"
        self.cells.append(f'<mxCell id="{i}"{v} style="{st}" edge="1" parent="1"{a}>{g}</mxCell>')

    def up(self, a, b):
        """a 在下、b 在上，竖直向上连"""
        self.edge(a, b, sx=.5, sy=0, ex=.5, ey=1)

    def zoom(self, src_box, panel_rect, side="right"):
        """放大关系，虚线。side="right"：块右侧两角 → 面板左边；"left"：块左侧两角 → 面板右边；
        "down"：块底边两角 → 面板顶边；"up"：块顶边两角 → 面板底边。"""
        x, y, w, h = self.geo[src_box]
        px, py, pw, ph = panel_rect
        kw = dict(arrow=False, dashed=True, color="#555555", w=1.2)
        if side in ("right", "left"):
            sx, ex = (x + w, px) if side == "right" else (x, px + pw)
            self.edge(start=(sx, y), end=(ex, py + 2), **kw)
            self.edge(start=(sx, y + h), end=(ex, min(py + ph - 2, y + h + 44)), **kw)
        else:
            sy, ey = (y + h, py) if side == "down" else (y, py + ph)
            self.edge(start=(x, sy), end=(px + 2, ey), **kw)
            self.edge(start=(x + w, sy), end=(min(px + pw - 2, x + w + 44), ey), **kw)

    def right(self, a, b):
        """a 在左、b 在右，水平向右连"""
        self.edge(a, b, sx=1, sy=.5, ex=0, ey=.5)

    def group(self, x, y, w, h, title=None, dashed=True, fs=12):
        """带标题的分组框（编码器 / 解码器 / 一个 stage / 训练 vs 推理）。要先画，才在子块下面。"""
        st = (f"rounded=1;arcSize=4;html=1;strokeColor=#9A9A9A;strokeWidth=1.3;fillColor=none;"
              + ("dashed=1;dashPattern=5 4;" if dashed else ""))
        i = self._id()
        self._v(i, "", st, x, y, w, h)
        self.geo[i] = (x, y, w, h)
        if title:
            self.text(x + 10, y + 4, w - 20, 18, title, fs=fs, color=self.P["sub"], bold=True, align="left")
        return i

    # ---------- 组合 ----------
    def stack(self, cx, w, y_bottom, items, gap=18, first_from=None, y_top=None):
        """自下而上堆叠。items: dict(label, role, sub, h, bold, hl, w, kind='box'|'plus', key)
        返回 {key: id}，并自动连竖直箭头。"""
        if y_top is not None:  # 自动撑满 [y_top, y_bottom]
            H = sum(22 if it.get("kind") == "plus" else it.get("h", 30) for it in items)
            J = sum(1 for it in items[1:] if it.get("join"))
            T = len(items) - 1
            gap = max(12, min(40, (y_bottom - y_top - H - 2 * J) / max(T - J, 1)))
        ids, prev, y = {}, None, y_bottom
        for it in items:
            if it.get("join"):
                y += gap - 2
            if it.get("kind") == "plus":
                r = 11
                cy = y - r
                i = self.plus(cx, cy, r)
                y = cy - r - gap
            else:
                h = it.get("h", 30)
                bw = it.get("w", w)
                i = self.box(cx - bw / 2, y - h, bw, h, it["label"], it.get("role", "io"), sub=it.get("sub"),
                             bold=it.get("bold", False), hl=it.get("hl", False), fs=it.get("fs", 13),
                             stroke=it.get("stroke"), dashed=it.get("dashed", False))
                y = y - h - gap
            if prev and not it.get("join"):
                self.up(prev, i)
            elif prev is None and first_from:
                src, fx = first_from
                self.edge(src, i, sx=fx, sy=0, ex=.5, ey=1)
            prev = i
            ids[it.get("key", f"k{len(ids)}")] = i
        return ids

    def row(self, x_left, cy, items, gap=28, h=44):
        """自左向右排一行，竖直居中在 cy。items 同 stack（每项可带 w，默认 120），自动连水平箭头。返回 {key: id}。"""
        ids, prev, x = {}, None, x_left
        for it in items:
            if it.get("kind") == "plus":
                r = 11
                i = self.plus(x + r, cy, r)
                x += 2 * r + gap
            else:
                bw, bh = it.get("w", 120), it.get("h", h)
                i = self.box(x, cy - bh / 2, bw, bh, it["label"], it.get("role", "io"), sub=it.get("sub"),
                             bold=it.get("bold", False), hl=it.get("hl", False), fs=it.get("fs", 13),
                             stroke=it.get("stroke"), dashed=it.get("dashed", False))
                x += bw + gap
            if prev and not it.get("join"):
                self.right(prev, i)
            prev = i
            ids[it.get("key", f"k{len(ids)}")] = i
        return ids

    def residual(self, from_id, plus_id, x_side):
        """从 from_id 顶边中点上方分出，沿 x_side 竖直上行，水平进入 ⊕（左侧或右侧自动判断）。"""
        fx, fy, fw, fh = self.geo[from_id]
        px, py, pw, ph = self.geo[plus_id]
        sy = fy - 8
        right = x_side > px
        self.edge(tgt=plus_id, ex=1 if right else 0, ey=.5, start=(fx + fw / 2, sy),
                  pts=[(x_side, sy), (x_side, py + ph / 2)])

    def bus(self, src_id, targets, x_bus, labels=None):
        """调制总线：从 src 顶边出发沿 x_bus 上行，逐个水平箭头进入 targets 的侧边，灰色。"""
        sx, sy, sw, sh = self.geo[src_id]
        col = "#9A9A9A"
        ys = []
        for k, t in enumerate(targets):
            tx, ty, tw, th = self.geo[t]
            cy = ty + th / 2
            right = x_bus > tx + tw / 2
            self.edge(tgt=t, ex=1 if right else 0, ey=.5, start=(x_bus, cy), color=col, w=1.2)
            if labels and labels[k]:
                lx = x_bus + 3 if right else x_bus - 43
                self.text(lx, cy - 16, 40, 14, labels[k], fs=10, color="#8A8A8A", align="left" if right else "right")
            ys.append(cy)
        top = min(ys)
        self.edge(arrow=False, start=(sx + sw / 2, sy), end=(x_bus, top),
                  pts=[(sx + sw / 2, sy - 10), (x_bus, sy - 10)], color=col, w=1.2)

    def inject(self, src_id, tgt_id, side="right"):
        """侧向注入：从 src 的左/右边中点水平进入 tgt"""
        if side == "right":
            self.edge(src_id, tgt_id, sx=0, sy=.5, ex=1, ey=.5)
        else:
            self.edge(src_id, tgt_id, sx=1, sy=.5, ex=0, ey=.5)

    def _v(self, i, v, st, x, y, w, h):
        v = html.escape(v, quote=True)
        self.cells.append(f'<mxCell id="{i}" value="{v}" style="{st}" vertex="1" parent="1">'
                          f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')

    def xml(self, name="fig"):
        return ('<mxfile host="paper-arch-figure"><diagram id="d" name="' + name + '"><mxGraphModel grid="0" page="0" '
                'background="#FFFFFF"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
                + "".join(self.cells) + "</root></mxGraphModel></diagram></mxfile>")


# ======================================================================
# 现成版式。三段放大（左 整体 / 中 一个 block / 右 独有做法，画布约 1460 × 740）只是其中一种组合：
# 下面的常量是三段模板的默认位置；overall / *_block 都能用 x0 / dy / rect 放到任意位置，
# 也可以完全不用它们，只用 Fig 的原语（box / stack / row / group / edge / zoom）自由排。
# 三段模板的常量可以在 spec 里改：import figlib; figlib.P2 = (...)
# ======================================================================
X0, W1 = 24, 470                      # 左段
P2 = (550, 36, 470, 664)              # 中段面板
P3 = (1068, 96, 412, 604)             # 右段面板
CAP_Y = 712


def caption(f, x, w, t, y=None):
    """段落底部说明；y 默认 CAP_Y（三段模板），自由版式里传面板底边 + 12。"""
    f.text(x, CAP_Y if y is None else y, w, 26, t, fs=15, color=f.P["text"])


def src(f, t, rect=None):
    """出处行，贴在 rect（默认右段 P3）底部。"""
    x, y, w, h = rect or P3
    f.text(x, y + h - 26, w, 20, t, fs=9.5, color="#9A9A9A")


# ---------------------------------------------------------------- 左段：整体
def overall(f, lanes, seq_title, segs, blocks, tops, cap, cross=None, zoom_idx=-1,
            x0=None, w=None, dy=0, zoom_to=None, zoom_side="right"):
    """lanes: [dict(inp=(label, role, sub, hl), enc=(...), enc2=(...)|None)]
    blocks: [(label, sub, hl)] 自下而上；tops: [[(label, role, sub, hl), ...], ...] 自下而上
    x0 / w / dy：整段平移和改宽（默认左段 X0、W1、不平移）；zoom_to：放大到哪个面板，默认 P2，False 不画放大线。"""
    X0 = globals()["X0"] if x0 is None else x0
    W1 = globals()["W1"] if w is None else w
    n = len(lanes)
    g = 12
    lw = (W1 - g * (n - 1)) / n
    cxs = [X0 + i * (lw + g) + lw / 2 for i in range(n)]
    lasts, inps, encs = [], [], []
    for i, ln in enumerate(lanes):
        x = cxs[i] - lw / 2
        fs0 = 13 if n < 4 else 12
        a = f.box(x, dy + 652, lw, 44, ln["inp"][0], ln["inp"][1], sub=ln["inp"][2], hl=ln["inp"][3], fs=fs0)
        b = f.box(x, dy + 578, lw, 50, ln["enc"][0], ln["enc"][1], sub=ln["enc"][2], hl=ln["enc"][3], fs=fs0 - .5)
        f.up(a, b)
        last = b
        if ln.get("enc2"):
            wht = ln["enc2"][1] == "white"
            c = f.box(x, dy + 506, lw, 50, ln["enc2"][0], ln["enc2"][1], sub=ln["enc2"][2], hl=ln["enc2"][3], fs=fs0 - 1,
                      stroke="#A1A1A6" if wht else None, dashed=wht)
            f.up(b, c)
            last = c
        lasts.append(last)
        inps.append(a)
        encs.append(b)
    if cross:  # (from_lane, to_lane) 参考图也喂给文本编码器，蓝色虚线
        fa, ta = cross
        # 直角走线：从输入块顶边靠近目标一侧出发，在输入行和编码器行之间的空隙里横走，再竖直进目标编码器底边
        ax, ay, aw, ah = f.geo[inps[fa]]
        toward = 1 if ta > fa else -1
        sx = ax + aw / 2 + toward * aw * 0.38
        ex = round(0.5 - toward * 0.38, 3)
        gy = dy + 640
        tx = cxs[ta] - lw / 2 + lw * ex
        f.edge(tgt=encs[ta], ex=ex, ey=1, start=(sx, ay), pts=[(sx, gy), (tx, gy)],
               dashed=True, color=f.P["hl_stroke"], w=1.4)
    seq, segids = f.seq(X0, dy + 412, W1, 66, seq_title, segs, fs=11.5)
    for i, last in enumerate(lasts):
        f.edge(last, seq, sx=.5, sy=0, ex=round((cxs[i] - X0) / W1, 3), ey=1)
    # blocks
    bids = []
    if len(blocks) == 1:
        lab, sub, hl = blocks[0]
        b = f.box(X0 + 80, dy + 318, W1 - 160, 62, lab, "white", sub=sub, hl=hl, fs=17, stroke="#222222", sw=2, arc=12)
        bids.append(b)
        top_y = dy + 318
    else:
        y = dy + 350
        for lab, sub, hl in blocks:
            b = f.box(X0 + 80, y, W1 - 160, 44, lab, "white", sub=sub, hl=hl, fs=15, stroke="#222222", sw=2, arc=12)
            bids.append(b)
            y -= 64
        top_y = y + 64
    f.up(seq, bids[0])
    for a, b in zip(bids, bids[1:]):
        f.up(a, b)
    # tops
    prev = [bids[-1]]
    y = top_y - 30
    for row in tops:
        h = 44 if any(r[2] for r in row) else 38
        y -= h
        k = len(row)
        gw = 20
        bw = (W1 - 60 - gw * (k - 1)) / k if k > 1 else W1 - 180
        ids = []
        for j, (lab, role, sub, hl) in enumerate(row):
            bx = X0 + 30 + j * (bw + gw) if k > 1 else X0 + 90
            ids.append(f.box(bx, y, bw, h, lab, role, sub=sub, hl=hl, fs=13))
        if len(prev) == len(ids):
            for a, b in zip(prev, ids):
                f.up(a, b)
        else:
            px, py, pw, ph = f.geo[prev[0]]
            for b in ids:
                bx, by, bw2, bh = f.geo[b]
                f.edge(prev[0], b, sx=round((bx + bw2 / 2 - px) / pw, 3), sy=0, ex=.5, ey=1)
        prev = ids
        y -= 26
    caption(f, X0, W1, cap, CAP_Y + dy if dy else None)
    if zoom_to is not False:
        f.zoom(bids[zoom_idx], zoom_to or P2, zoom_side)
    return segids


# ---------------------------------------------------------------- 中段：单流 block
def single_block(f, items, bus_label=None, bus_keys=(), bus_labels=None, residuals=(), injects=(),
                 gap=20, cap="", note=None, w=236, rect=None):
    """items 同 Fig.stack；residuals=[(from_key, plus_key)]；injects=[(label, sub, target_key, hl)]
    rect=(x, y, w, h) 把整个面板放到任意位置，默认中段 P2。"""
    x, y, pw, ph = rect or P2
    cy_ = None if rect is None else y + ph + 12
    f.panel(x, y, pw, ph, main=True)
    cx = x + 225
    yb = y + ph - (54 if bus_label else 16)
    ids = f.stack(cx, w, yb, items, y_top=y + 84)
    left = cx - w / 2
    for a, b in residuals:
        f.residual(ids[a], ids[b], left - 16)
    if bus_label:
        m = f.box(left - 94, y + ph - 40, 150, 28, bus_label[0], "mod", sub=None, hl=bus_label[1], fs=11)
        # 调制源放左下角：总线沿最左侧上行
        f.bus(m, [ids[k] for k in bus_keys], left - 34, bus_labels)
    for lab, sub, key, hl in injects:
        tx, ty, tw, th = f.geo[ids[key]]
        bw = x + pw - 14 - (tx + tw + 26)
        b = f.box(tx + tw + 26, ty + th / 2 - 15, bw, 30, lab, "inject", hl=hl, fs=11.5)
        f.inject(b, ids[key])
        if sub:
            f.text(tx + tw + 20, ty + th / 2 + 17, bw + 12, 14 * (sub.count("\n") + 1) + 2, sub, fs=10)
    if note:
        f.text(x + pw - 150, y + 20, 140, 40, note[0], fs=12, color=f.P["note_hot"], bold=True)
        if len(note) > 1:
            f.text(x + pw - 150, y + 52, 140, 20, note[1], fs=10.5)
    caption(f, x, pw, cap, cy_)
    return ids


# ---------------------------------------------------------------- 中段：并行单流 block（FLUX 系）
def parallel_block(f, in_label, fused, attn, mlp, cat, bus, top_note, cap, rect=None):
    """fused: None 或 (label, sub, hl)；attn / mlp: (label, sub)；cat: (label, sub, hl)；bus: (label, hl)"""
    x, y, pw, ph = rect or P2
    cy_ = None if rect is None else y + ph + 12
    f.panel(x, y, pw, ph)
    cx, w = x + 225, 236
    yb, bw, bh = y + ph - 54, 124, 86
    lower = [dict(label=in_label, role="io", h=28, key="in"),
             dict(label="LayerNorm", role="norm", h=26, key="n1"),
             dict(label="Scale & Shift", role="mod", h=26, key="m1", join=True)]
    if fused:
        lower.append(dict(label=fused[0], role="attn", h=40, key="fz", sub=fused[1], hl=fused[2]))
    ids = f.stack(cx, w, yb, lower, gap=30)
    last = ids["fz" if fused else "m1"]
    ly = f.geo[last][1]
    a = f.box(cx - bw - 8, ly - 40 - bh, bw, bh, attn[0], "core", bold=True, sub=attn[1], fs=13)
    m = f.box(cx + 8, ly - 40 - bh, bw, bh, mlp[0], "ffn", sub=mlp[1], fs=13)
    f.edge(last, a, sx=.3, sy=0, ex=.5, ey=1)
    f.edge(last, m, sx=.7, sy=0, ex=.5, ey=1)
    top = f.stack(cx, w, ly - 40 - bh - 40, [
        dict(label=cat[0], role="attn", h=40, key="cat", sub=cat[1], hl=cat[2]),
        dict(label="Gate", role="mod", h=26, key="g"),
        dict(kind="plus", key="p"),
        dict(label="下一层", role="io", h=26, key="out"),
    ], y_top=y + 90)
    f.edge(a, top["cat"], sx=.5, sy=0, ex=.3, ey=1)
    f.edge(m, top["cat"], sx=.5, sy=0, ex=.7, ey=1)
    f.residual(ids["in"], top["p"], cx - w / 2 - 16)
    mo = f.box(cx - w / 2 - 94, y + ph - 40, 150, 28, bus[0], "mod", hl=bus[1], fs=11)
    f.bus(mo, [ids["m1"], top["g"]], cx - w / 2 - 34)
    f.text(x + 20, y + 16, pw - 40, 40, top_note, fs=11)
    caption(f, x, pw, cap, cy_)


# ---------------------------------------------------------------- 中段：双流 block（MMDiT 系）
def dual_block(f, streams=("文本 token", "图像 token"), attn=("Joint Attention · [ 文本, 图像 ]", "各自 QKV → QK-RMSNorm → RoPE"),
               ffn="FFN · GELU", mods=(("txt_mod(t)", False), ("img_mod(t)", False)), top_note="", cap="", rect=None):
    """两个流各一列：Norm → Scale&Shift → 共用 Joint Attention → Gate → ⊕ → Norm → Scale&Shift → FFN → Gate → ⊕。
    mods: 两个流的调制源 (label, hl)；残差走外侧，调制总线在残差再外侧。"""
    x, y, pw, ph = rect or P2
    cy_ = None if rect is None else y + ph + 12
    f.panel(x, y, pw, ph)
    colw, cxT, cxI = 150, x + 125, x + 345
    yb = y + ph - 54
    span = cxI - cxT + colw
    fl, fr = round(colw / 2 / span, 3), round(1 - colw / 2 / span, 3)

    def col(cx, lab):
        return f.stack(cx, colw, yb, [
            dict(label=lab, role="io", h=28, key="in", fs=12),
            dict(label="LayerNorm", role="norm", h=26, key="n1", fs=12),
            dict(label="Scale & Shift", role="mod", h=26, key="m1", join=True, fs=12),
        ], gap=26)
    T, I = col(cxT, streams[0]), col(cxI, streams[1])
    ay = f.geo[T["m1"]][1] - 26 - 44
    att = f.box(cxT - colw / 2, ay, span, 44, attn[0], "core", bold=True, sub=attn[1], fs=13)
    f.edge(T["m1"], att, sx=.5, sy=0, ex=fl, ey=1)
    f.edge(I["m1"], att, sx=.5, sy=0, ex=fr, ey=1)

    def upper(cx, fx):
        return f.stack(cx, colw, ay - 24, [
            dict(label="Gate", role="mod", h=26, key="g1", fs=12),
            dict(kind="plus", key="p1"),
            dict(label="LayerNorm", role="norm", h=26, key="n2", fs=12),
            dict(label="Scale & Shift", role="mod", h=26, key="m2", join=True, fs=12),
            dict(label=ffn, role="ffn", h=30, key="ff", fs=12),
            dict(label="Gate", role="mod", h=26, key="g2", fs=12),
            dict(kind="plus", key="p2"),
            dict(label="下一层", role="io", h=26, key="out", fs=12),
        ], first_from=(att, fx), y_top=y + 60)
    TU, IU = upper(cxT, fl), upper(cxI, fr)
    for lo, up, side in ((T, TU, cxT - colw / 2 - 14), (I, IU, cxI + colw / 2 + 14)):
        f.residual(lo["in"], up["p1"], side)
        f.residual(up["p1"], up["p2"], side)
    mt = f.box(cxT - colw / 2 - 40, y + ph - 40, 110, 28, mods[0][0], "mod", hl=mods[0][1], fs=11)
    mi = f.box(cxI + colw / 2 - 70, y + ph - 40, 110, 28, mods[1][0], "mod", hl=mods[1][1], fs=11)
    f.bus(mt, [T["m1"], TU["g1"], TU["m2"], TU["g2"]], cxT - colw / 2 - 30)
    f.bus(mi, [I["m1"], IU["g1"], IU["m2"], IU["g2"]], cxI + colw / 2 + 30)
    if top_note:
        f.text(x + 20, y + 16, pw - 40, 20, top_note, fs=10.5)
    caption(f, x, pw, cap, cy_)
    return dict(txt=T | TU, img=I | IU, attn=att)
