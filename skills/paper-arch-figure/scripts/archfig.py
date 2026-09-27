#!/usr/bin/env python3
"""archfig —— 从 Python spec 生成可编辑的 draw.io 模型架构图，并导出 SVG / PNG。

  archfig doctor                          检查 draw.io 桌面版是否可用
  archfig build SPEC.py [选项]            生成 .drawio 并导出
  archfig new NAME.py                     复制一个最小 spec 模板到当前目录

build 选项：
  --out DIR          输出目录（默认 SPEC 同级的 figs/）
  --fmt svg,png      导出格式，逗号分隔（默认 svg,png；只要 .drawio 就写 none）
  --palette paper    paper | deck | both（默认 paper）
  --only k1,k2       只生成这些 key
  --fit-width 1664   报告：图缩放到这个宽度（px）时的实际字号
  --gallery          额外写 index.html，逐张并排查看，可切配色

SPEC 约定：定义 FIGURES = [(key, 标题, fn), ...]，fn(palette) 返回 figlib.Fig。
draw.io 路径：环境变量 DRAWIO，其次 macOS 应用默认路径，再其次 PATH 里的 drawio / draw.io。
"""
import argparse, html, importlib.util, os, pathlib, re, shutil, subprocess, sys

HERE = pathlib.Path(os.path.realpath(__file__)).parent
sys.path.insert(0, str(HERE))

MAC = ["/Applications/draw.io.app/Contents/MacOS/draw.io", "/Applications/drawio.app/Contents/MacOS/drawio"]


def find_drawio():
    for c in [os.environ.get("DRAWIO", "")] + MAC:
        if c and pathlib.Path(c).exists():
            return c
    return shutil.which("drawio") or shutil.which("draw.io")


def clean_svg(path):
    """draw.io 的 SVG：删掉每个文字块的 PNG 兜底图（体积 ~10×），light-dark(A, B) 锁成 A，保证暗色系统下仍是浅色图。"""
    t = path.read_text()
    t = re.sub(r"<image [^>]*?/>", "", t)
    out, i, key = [], 0, "light-dark("
    while True:
        j = t.find(key, i)
        if j < 0:
            out.append(t[i:])
            break
        out.append(t[i:j])
        k, depth, comma = j + len(key), 1, None
        while depth:
            c = t[k]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            elif c == "," and depth == 1 and comma is None:
                comma = k
            k += 1
        out.append(t[j + len(key):comma].strip())
        i = k
    path.write_text("".join(out).replace("color-scheme: light dark;", "color-scheme: light;"))


def load_spec(p):
    p = pathlib.Path(p).resolve()
    sys.path.insert(0, str(p.parent))
    spec = importlib.util.spec_from_file_location(p.stem, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    if not hasattr(m, "FIGURES"):
        sys.exit(f"{p.name} 里没有 FIGURES = [(key, 标题, fn), ...]")
    return m.FIGURES


def font_report(drawio_xml, svg_path, fit):
    sizes = sorted({float(x) for x in re.findall(r"fontSize=([\d.]+)", drawio_xml)})
    m = re.search(r'width="([\d.]+)px"', svg_path.read_text()[:2000]) if svg_path and svg_path.exists() else None
    if not (m and sizes):
        return ""
    k = fit / float(m.group(1))
    body = 13 * k
    flag = "  ← 偏小" if body < 15 else ""
    return f"缩到 {fit}px 宽（×{k:.2f}）：最小字 {sizes[0] * k:.1f}px，正文 {body:.1f}px{flag}"


def cmd_build(a):
    figs = load_spec(a.spec)
    out = pathlib.Path(a.out or pathlib.Path(a.spec).resolve().parent / "figs")
    out.mkdir(parents=True, exist_ok=True)
    pals = ["paper", "deck"] if a.palette == "both" else [a.palette]
    fmts = [] if a.fmt == "none" else a.fmt.split(",")
    only = set(a.only.split(",")) if a.only else None
    exe = find_drawio() if fmts else None
    if fmts and not exe:
        sys.exit("找不到 draw.io 桌面版。装好后重试，或用 --fmt none 只生成 .drawio，或设 DRAWIO=/path/to/draw.io")
    made = []
    for key, title, fn in figs:
        if only and key not in only:
            continue
        for pal in pals:
            f = fn(pal)
            xml = f.xml(title)
            d = out / f"{key}_{pal}.drawio"
            d.write_text(xml)
            line = [d.name]
            svg = None
            for fmt in fmts:
                o = out / f"{key}_{pal}.{fmt}"
                args = [exe, "-x", "-f", fmt, "-o", str(o), str(d)]
                if fmt == "png":
                    args[4:4] = ["--width", "1800"]
                r = subprocess.run(args, capture_output=True, text=True)
                if not o.exists():
                    line.append(f"{fmt} 失败：{r.stderr.strip()[-200:]}")
                    continue
                if fmt == "svg":
                    clean_svg(o)
                    svg = o
                line.append(o.name)
            if a.fit_width and svg:
                line.append(font_report(xml, svg, a.fit_width))
            print("  ".join(x for x in line if x))
            made.append((key, title, pal))
    if a.gallery:
        write_gallery(out, made, "svg" if "svg" in fmts else ("png" if "png" in fmts else None))


def write_gallery(out, made, ext):
    if not ext:
        print("--gallery 需要导出 svg 或 png")
        return
    keys = []
    for k, t, _ in made:
        if (k, t) not in keys:
            keys.append((k, t))
    pals = sorted({p for *_, p in made}, key=["paper", "deck"].index)
    btn = "".join(f'<button data-p="{p}"{" class=on" if i == 0 else ""}>{p}</button>' for i, p in enumerate(pals))
    secs = "".join(f'<section><h2>{html.escape(t)}</h2><img data-k="{k}" src="{k}_{pals[0]}.{ext}"></section>' for k, t in keys)
    (out / "index.html").write_text(f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>架构图</title>
<style>:root{{color-scheme:light}}body{{margin:0;padding:20px 24px 60px;background:#F5F5F7;font:15px "PingFang SC",Helvetica,sans-serif;color:#1D1D1F}}
.bar{{position:sticky;top:0;background:#F5F5F7;padding:8px 0 12px;z-index:2}}button{{font:inherit;border:0;background:#E8E8ED;padding:6px 14px;border-radius:8px;margin-right:6px;cursor:pointer}}
button.on{{background:#1D1D1F;color:#fff}}section{{background:#fff;border-radius:18px;padding:18px 22px;margin:0 auto 22px;max-width:1500px}}
h2{{margin:0 0 10px;font-size:18px}}img{{width:100%;display:block}}</style></head><body>
<div class="bar">{btn}</div>{secs}
<script>document.querySelector('.bar').onclick=e=>{{const p=e.target.dataset.p;if(!p)return;
document.querySelectorAll('.bar button').forEach(b=>b.classList.toggle('on',b.dataset.p===p));
document.querySelectorAll('img[data-k]').forEach(i=>i.src=i.dataset.k+'_'+p+'.{ext}');}}</script></body></html>''')
    print(out / "index.html")


TEMPLATE = '''"""新模型架构图 spec。先读技能里的 references/layouts.md，再照 assets/examples/six_edit_models.py 里结构最接近的函数改。"""
from figlib import *  # noqa: F401,F403


def mymodel(pal):
    f = Fig(pal)
    overall(
        f,
        lanes=[
            dict(inp=("指令", "io", None, False), enc=("文本编码器", "cond", "只读文字", False)),
            dict(inp=("参考图", "io", None, False), enc=("VAE", "io", "8× · 16 通道", False),
                 enc2=("2×2 打包", "io", "→ 64 维", False)),
            dict(inp=("目标图", "io", "训练才有", False), enc=("VAE", "io", "8× · 16 通道", False),
                 enc2=("加噪 x_t · 2×2 打包", "io", None, False)),
        ],
        seq_title="一条序列：[ 文字 | x_t | 参考图 ]",
        segs=[("文字", "seg_txt", 2, False), ("x_t 目标", "seg_x", 2, False), ("参考图", "seg_ref", 2, True)],
        blocks=[("单流 Block × N", "宽 D · H 头", False)],
        tops=[[("norm_out → proj_out", "norm", None, False)], [("取目标 token → 速度 v", "io", None, False)]],
        cap="MyModel")
    single_block(
        f,
        [dict(label="Hidden (B, S, D)", role="io", h=28, key="in"),
         dict(label="LayerNorm", role="norm", h=26, key="n1"),
         dict(label="Scale & Shift", role="mod", h=26, key="m1", join=True),
         dict(label="Self-Attention", role="core", h=34, key="att", bold=True, sub="QK-RMSNorm · RoPE"),
         dict(label="Gate", role="mod", h=26, key="g1"),
         dict(kind="plus", key="p1"),
         dict(label="LayerNorm", role="norm", h=26, key="n2"),
         dict(label="Scale & Shift", role="mod", h=26, key="m2", join=True),
         dict(label="FFN", role="ffn", h=30, key="ff"),
         dict(label="Gate", role="mod", h=26, key="g2"),
         dict(kind="plus", key="p2"),
         dict(label="下一层", role="io", h=26, key="out")],
        bus_label=("adaLN（本层）", False), bus_keys=["m1", "g1", "m2", "g2"],
        residuals=[("in", "p1"), ("p1", "p2")], cap="单流 Block（× N）")
    # 右段：这个模型独有的机制，自由排版；P3 = (x, y, w, h)
    px, py, pw, ph = P3
    f.panel(*P3, main=False)
    f.text(px + 16, py + 12, pw - 32, 24, "独有做法的标题", fs=14, color=f.P["text"], bold=True)
    src(f, "出处：仓库 @ commit · 文件:行号")
    caption(f, px, pw, "独有做法：一句话")
    return f


FIGURES = [("mymodel", "MyModel", mymodel)]
'''


def main():
    ap = argparse.ArgumentParser(prog="archfig", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("spec")
    b.add_argument("--out")
    b.add_argument("--fmt", default="svg,png")
    b.add_argument("--palette", default="paper", choices=["paper", "deck", "both"])
    b.add_argument("--only")
    b.add_argument("--fit-width", type=int)
    b.add_argument("--gallery", action="store_true")
    sub.add_parser("doctor")
    n = sub.add_parser("new")
    n.add_argument("name")
    a = ap.parse_args()
    if a.cmd == "doctor":
        exe = find_drawio()
        print(f"draw.io：{exe or '未找到（macOS 从 github.com/jgraph/drawio-desktop/releases 下 dmg 装到 /Applications）'}")
        print(f"figlib：{HERE / 'figlib.py'}")
        sys.exit(0 if exe else 1)
    if a.cmd == "new":
        p = pathlib.Path(a.name)
        if p.exists():
            sys.exit(f"{p} 已存在，不覆盖")
        p.write_text(TEMPLATE)
        print(p)
        return
    cmd_build(a)


if __name__ == "__main__":
    main()
