"""draw.io 模型架构图生成库（paper-arch-figure 技能）。

样式规则见本技能 references/style.md。
两套配色（可替换的默认值，改 PALETTES 即可）：
  paper —— STYLE.md 的五色语义（灰 IO / 蓝 Norm·注入 / 紫 时间步·条件 / 橙 注意力 / 绿 FFN）
  deck  —— 单一强调色版式：全灰块 + 强调蓝，和 keynote 风 deck 其他页一致
两套都遵守同一约定：hl=True 的块画蓝框，表示「这个模型独有的做法」。
"""
import html

FONT = "PingFang SC, Helvetica"   # 可替换：中文字体放第一位

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
            fs=13, stroke=None, sw=1.5, arc=18, dashed=False, id=None, fill=None):
        P = self.P
        i = id or self._id()
        f = fill or P[role]
        col = P["text"]
        if hl and self.pal == "deck":
            f = P["hl_fill"]
            col = P["hl_text"]
        v = html.escape(label)
        if bold or hl:
            v = f"<b>{v}</b>"
        if sub:
            sc = P["hl_text"] if (hl and P.get("hl_text")) else P["sub"]
            v += f'<br><font style="font-size:{max(fs-3,10)}px" color="{sc}">{html.escape(sub)}</font>'
        st_col = P["hl_stroke"] if hl else (stroke or "none")
        st_w = 2.2 if hl else sw
        st = (f"rounded=1;arcSize={arc};whiteSpace=wrap;html=1;strokeColor={st_col};strokeWidth={st_w};"
              f"fillColor={f};fontSize={fs};fontFamily={FONT};fontColor={col};")
        if dashed:
            st += "dashed=1;dashPattern=5 4;"
        self._v(i, v, st, x, y, w, h)
        self.geo[i] = (x, y, w, h)
        return i

    def text(self, x, y, w, h, label, fs=12, color=None, bold=False, align="center", id=None):
        i = id or self._id()
        c = color or self.P["sub"]
        v = html.escape(label).replace("\n", "<br>")
        if bold:
            v = f"<b>{v}</b>"
        st = (f"text;html=1;align={align};verticalAlign=middle;whiteSpace=wrap;fontSize={fs};"
              f"fontFamily={FONT};fontColor={c};")
        self._v(i, v, st, x, y, w, h)
        return i

    def plus(self, cx, cy, r=11, sym="+", id=None):
        i = id or self._id()
        st = (f"ellipse;html=1;strokeColor={self.P['text']};strokeWidth=1.5;fillColor=#FFFFFF;"
              f"fontSize=15;fontColor={self.P['text']};fontFamily=Helvetica;")
        self._v(i, sym, st, cx - r, cy - r, 2 * r, 2 * r)
        self.geo[i] = (cx - r, cy - r, 2 * r, 2 * r)
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

    def zoom(self, src_box, panel_rect):
        """被放大块的右侧两个角 → 放大面板左侧两个角，虚线"""
        x, y, w, h = self.geo[src_box]
        px, py, pw, ph = panel_rect
        self.edge(arrow=False, dashed=True, start=(x + w, y), end=(px, py + 2), color="#555555", w=1.2)
        self.edge(arrow=False, dashed=True, start=(x + w, y + h), end=(px, min(py + ph - 2, y + h + 44)), color="#555555", w=1.2)

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
# 版式：三段放大（左 整体 / 中 一个 block / 右 独有做法），画布约 1460 × 740
# 坐标常量可以在 spec 里改：import figlib; figlib.P2 = (...)
# ======================================================================
X0, W1 = 24, 470                      # 左段
P2 = (550, 36, 470, 664)              # 中段面板
P3 = (1068, 96, 412, 604)             # 右段面板
CAP_Y = 712


def caption(f, x, w, t):
    f.text(x, CAP_Y, w, 26, t, fs=15, color=f.P["text"])


def src(f, t):
    f.text(P3[0], P3[1] + P3[3] - 26, P3[2], 20, t, fs=9.5, color="#9A9A9A")


# ---------------------------------------------------------------- 左段：整体
def overall(f, lanes, seq_title, segs, blocks, tops, cap, cross=None, zoom_idx=-1):
    """lanes: [dict(inp=(label, role, sub, hl), enc=(...), enc2=(...)|None)]
    blocks: [(label, sub, hl)] 自下而上；tops: [[(label, role, sub, hl), ...], ...] 自下而上"""
    n = len(lanes)
    g = 12
    lw = (W1 - g * (n - 1)) / n
    cxs = [X0 + i * (lw + g) + lw / 2 for i in range(n)]
    lasts, inps = [], []
    for i, ln in enumerate(lanes):
        x = cxs[i] - lw / 2
        fs0 = 13 if n < 4 else 12
        a = f.box(x, 652, lw, 44, ln["inp"][0], ln["inp"][1], sub=ln["inp"][2], hl=ln["inp"][3], fs=fs0)
        b = f.box(x, 578, lw, 50, ln["enc"][0], ln["enc"][1], sub=ln["enc"][2], hl=ln["enc"][3], fs=fs0 - .5)
        f.up(a, b)
        last = b
        if ln.get("enc2"):
            wht = ln["enc2"][1] == "white"
            c = f.box(x, 506, lw, 50, ln["enc2"][0], ln["enc2"][1], sub=ln["enc2"][2], hl=ln["enc2"][3], fs=fs0 - 1,
                      stroke="#A1A1A6" if wht else None, dashed=wht)
            f.up(b, c)
            last = c
        lasts.append(last)
        inps.append(a)
    if cross:  # (from_lane, to_lane) 参考图也喂给文本编码器，蓝色虚线
        fa, ta = cross
        ax, ay, aw, ah = f.geo[inps[fa]]
        f.edge(tgt=lasts[ta] if False else None, start=(ax + 10, ay), end=(cxs[ta] + lw / 2 - 2, 604),
               pts=[(ax + 10, 640)], dashed=True, color=f.P["hl_stroke"], w=1.4)
    seq, segids = f.seq(X0, 412, W1, 66, seq_title, segs, fs=11.5)
    for i, last in enumerate(lasts):
        f.edge(last, seq, sx=.5, sy=0, ex=round((cxs[i] - X0) / W1, 3), ey=1)
    # blocks
    bids = []
    if len(blocks) == 1:
        lab, sub, hl = blocks[0]
        b = f.box(X0 + 80, 318, W1 - 160, 62, lab, "white", sub=sub, hl=hl, fs=17, stroke="#222222", sw=2, arc=12)
        bids.append(b)
        top_y = 318
    else:
        y = 350
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
    caption(f, X0, W1, cap)
    f.zoom(bids[zoom_idx], P2)
    return segids


# ---------------------------------------------------------------- 中段：单流 block
def single_block(f, items, bus_label=None, bus_keys=(), bus_labels=None, residuals=(), injects=(),
                 gap=20, cap="", note=None, w=236):
    """items 同 Fig.stack；residuals=[(from_key, plus_key)]；injects=[(label, sub, target_key, hl)]"""
    x, y, pw, ph = P2
    f.panel(*P2, main=True)
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
    caption(f, x, pw, cap)
    return ids


# ---------------------------------------------------------------- 中段：并行单流 block（FLUX 系）
def parallel_block(f, in_label, fused, attn, mlp, cat, bus, top_note, cap):
    """fused: None 或 (label, sub, hl)；attn / mlp: (label, sub)；cat: (label, sub, hl)；bus: (label, hl)"""
    x, y, pw, ph = P2
    f.panel(*P2)
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
    caption(f, x, pw, cap)


# ---------------------------------------------------------------- 中段：双流 block（MMDiT 系）
def dual_block(f, streams=("文本 token", "图像 token"), attn=("Joint Attention · [ 文本, 图像 ]", "各自 QKV → QK-RMSNorm → RoPE"),
               ffn="FFN · GELU", mods=(("txt_mod(t)", False), ("img_mod(t)", False)), top_note="", cap=""):
    """两个流各一列：Norm → Scale&Shift → 共用 Joint Attention → Gate → ⊕ → Norm → Scale&Shift → FFN → Gate → ⊕。
    mods: 两个流的调制源 (label, hl)；残差走外侧，调制总线在残差再外侧。"""
    x, y, pw, ph = P2
    f.panel(*P2)
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
    caption(f, x, pw, cap)
    return dict(txt=T | TU, img=I | IU, attn=att)
