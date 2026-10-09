#!/usr/bin/env python3
"""把一篇论文准备成 agent 能逐段读、按页核对的材料。

输入：arXiv ID / arXiv 链接 / 任意 PDF 直链 / 本地 PDF 路径。
输出（默认 ./paper-quick-read/<id>/）：
    paper.pdf      原文（本地 PDF 不复制，index.json 里记原路径）
    text.txt       带页码分隔行的全文：===== PAGE 3 =====
    pages/p003.png 含图表的页面渲染图（扫描件则每页都渲染）
    index.json     页码 → 行号区间、是否有图表、该页出现的图表标题、图片路径

只依赖 PyMuPDF（pip install pymupdf）和标准库。

用法：
    python3 extract_paper.py 1706.03762
    python3 extract_paper.py https://arxiv.org/abs/2505.11493v2 --out ./reading/2505.11493
    python3 extract_paper.py ./some.pdf
    python3 extract_paper.py 1706.03762 --render 5,9      # 已抽取过，再补渲染几页
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24
except ImportError:  # 旧版本只有 fitz 这个名字
    try:
        import fitz
    except ImportError:
        sys.exit("缺少 PyMuPDF：请先 pip install pymupdf（建议装在虚拟环境里）")

RENDER_DPI = 110               # 够看清坐标轴和表格数字，又不至于图太大
SCANNED_CHARS_PER_PAGE = 200   # 平均每页字符低于这个数就当扫描件
BIG_IMAGE_AREA = 80_000        # 宽 × 高，低于它的位图多半是 logo 或公式碎图
MANY_DRAWINGS = 60             # 矢量折线图/柱状图会有大量绘图指令
ARXIV_THROTTLE_SEC = 3         # arXiv 官方要求的礼貌间隔
RETRY_WAITS = (10, 20, 30)
USER_AGENT = "paper-quick-read/1.0 (single-paper reader; polite)"

# 页面里出现图表编号才可能是图表页
CAPTION_ANY = re.compile(r"(?:Figure|Fig\.?|Table|图|表)\s*\d+", re.IGNORECASE)
# 行首的图表编号，基本就是图注/表注本身，用来建「Figure N 在第几页」的索引
CAPTION_LINE = re.compile(r"^\s*((?:Figure|Fig\.?|Table)\s*\d+|[图表]\s*\d+)\s*[:.：|]",
                          re.IGNORECASE)

NEW_ARXIV = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
OLD_ARXIV = re.compile(r"([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?")


def parse_source(src):
    """返回 (kind, value, paper_id)。kind ∈ local / arxiv / url。"""
    path = Path(src).expanduser()
    if path.exists():
        return "local", path.resolve(), safe_id(path.stem)
    if "arxiv.org" in src or not src.startswith(("http://", "https://")):
        for pat in (NEW_ARXIV, OLD_ARXIV):
            m = pat.search(src)
            if m:
                aid = m.group(1) + (m.group(2) or "")
                return "arxiv", aid, safe_id(aid)
        if not src.startswith(("http://", "https://")):
            sys.exit(f"认不出输入：{src}（既不是本地文件，也不像 arXiv ID 或链接）")
    stem = Path(src.split("?")[0].rstrip("/")).stem or "paper"
    return "url", src, safe_id(stem)


def safe_id(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "paper"


def download(url, dest, throttle):
    if throttle:
        time.sleep(throttle)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_err = None
    for wait in (0,) + RETRY_WAITS:
        if wait:
            sys.stderr.write(f"下载失败（{last_err}），{wait} 秒后重试\n")
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            if not data.startswith(b"%PDF"):
                raise ValueError("返回的不是 PDF（可能是登录页或错误页）")
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
            return
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = str(e)
        except ValueError as e:
            last_err = str(e)
            break
    sys.exit(f"下载失败：{url}（{last_err}）")


def page_has_visual(page, text):
    """这一页值不值得渲染成图片：要有图表编号，并且真有大位图或大量矢量绘图。"""
    if not CAPTION_ANY.search(text):
        return False
    for img in page.get_images(full=True):
        if img[2] * img[3] > BIG_IMAGE_AREA:
            return True
    return len(page.get_drawings()) > MANY_DRAWINGS


def captions_on(text):
    seen = []
    for line in text.splitlines():
        m = CAPTION_LINE.match(line)
        if m:
            label = re.sub(r"\s+", " ", m.group(1)).replace("Fig ", "Fig. ")
            if label not in seen:
                seen.append(label)
    return seen


def guess_title(doc, first_page_text):
    meta = ((doc.metadata or {}).get("title") or "").strip()
    if len(meta) > 6 and not meta.lower().endswith(".pdf"):
        return meta[:180]
    try:  # 元数据不可信时，取首页字号最大的那一行
        best, best_size = "", 0.0
        for block in doc[0].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                size = max((s["size"] for s in line["spans"]), default=0)
                text = "".join(s["text"] for s in line["spans"]).strip()
                if size > best_size and len(text) > 6 and not text.lower().startswith("arxiv:"):
                    best, best_size = text, size
        if best:
            return best[:180]
    except Exception:
        pass
    return (first_page_text.strip().split("\n") or [""])[0][:180]


def render(doc, page_no, out_dir, dpi):
    rel = f"pages/p{page_no:03d}.png"
    (out_dir / "pages").mkdir(exist_ok=True)
    doc[page_no - 1].get_pixmap(dpi=dpi).save(str(out_dir / rel))
    return rel


def parse_pages(spec, n):
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            pages.update(range(int(a), int(b) + 1))
        else:
            pages.add(int(part))
    bad = [p for p in pages if not 1 <= p <= n]
    if bad:
        sys.exit(f"页码超出范围 1–{n}：{sorted(bad)}")
    return sorted(pages)


def main():
    ap = argparse.ArgumentParser(description="下载并抽取论文：带页码全文 + 图表页 PNG + 页索引")
    ap.add_argument("source", help="arXiv ID / arXiv 链接 / PDF 直链 / 本地 PDF 路径")
    ap.add_argument("--out", help="输出目录，默认 ./paper-quick-read/<id>/")
    ap.add_argument("--dpi", type=int, default=RENDER_DPI, help=f"渲染分辨率，默认 {RENDER_DPI}")
    ap.add_argument("--max-images", type=int, default=0,
                    help="最多渲染多少张图表页，0 表示不限（默认）；超出时保留靠前的页")
    ap.add_argument("--render", help="额外渲染指定页，如 5,9 或 3-6；可在抽取完成后单独再跑")
    args = ap.parse_args()

    kind, value, pid = parse_source(args.source)
    out_dir = Path(args.out or Path("paper-quick-read") / pid).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if kind == "local":
        pdf_path = value
    else:
        pdf_path = out_dir / "paper.pdf"
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            sys.stderr.write(f"复用已下载的 {pdf_path}\n")
        elif kind == "arxiv":
            download(f"https://arxiv.org/pdf/{value}", pdf_path, ARXIV_THROTTLE_SEC)
        else:
            download(value, pdf_path, 0)

    doc = fitz.open(str(pdf_path))
    n = len(doc)
    index_path = out_dir / "index.json"

    # 只补渲染：沿用已有 index.json，不重抽全文
    if args.render and index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        by_page = {p["page"]: p for p in index["page_index"]}
        for p in parse_pages(args.render, n):
            by_page[p]["image"] = render(doc, p, out_dir, args.dpi)
            print(f"rendered p.{p} -> {out_dir / by_page[p]['image']}")
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    texts = [page.get_text() for page in doc]
    lines_out, page_index = [], []
    for i, t in enumerate(texts, 1):
        lines_out.append(f"===== PAGE {i} =====")
        start = len(lines_out) + 1           # 1-based 行号，直接喂给按行读文件的工具
        body = t.rstrip("\n").splitlines()
        lines_out.extend(body)
        lines_out.append("")
        page_index.append({
            "page": i,
            "line_start": start - 1,         # 指向分隔行本身
            "line_end": len(lines_out),
            "chars": len(t.strip()),
            "captions": captions_on(t),
            "has_figure": False,             # 有图或有表，即渲染了 PNG
            "image": None,
        })
    (out_dir / "text.txt").write_text("\n".join(lines_out) + "\n", encoding="utf-8")

    total_chars = sum(p["chars"] for p in page_index)
    scanned = total_chars < SCANNED_CHARS_PER_PAGE * max(n, 1)
    if scanned:   # 抽不出字，只能整篇靠看图
        candidates = list(range(1, n + 1))
    else:
        # 有图（大位图/大量矢量绘图）或有行首图注表注的页都渲染：表格数字靠抽字容易错行，看图核对更稳
        candidates = [i + 1 for i, page in enumerate(doc)
                      if page_index[i]["captions"] or page_has_visual(page, texts[i])]
    if args.max_images and len(candidates) > args.max_images:
        candidates = candidates[: args.max_images]   # 方法图通常比附录图靠前、也更重要
    for p in candidates:
        entry = page_index[p - 1]
        entry["has_figure"] = True
        entry["image"] = render(doc, p, out_dir, args.dpi)
    if args.render:
        for p in parse_pages(args.render, n):
            page_index[p - 1]["image"] = render(doc, p, out_dir, args.dpi)

    caption_map = {}
    for entry in page_index:
        for c in entry["captions"]:
            caption_map.setdefault(c, entry["page"])

    index = {
        "source": str(args.source),
        "arxiv_id": value if kind == "arxiv" else None,
        "pdf": str(pdf_path),
        "title": guess_title(doc, texts[0] if texts else ""),
        "pages": n,
        "chars": total_chars,
        "scanned": scanned,
        "text_file": "text.txt",
        "text_lines": len(lines_out),
        "figure_pages": candidates,
        "caption_pages": caption_map,
        "page_index": page_index,
    }
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"out_dir={out_dir}")
    print(f"title={index['title']}")
    print(f"pages={n} chars={total_chars} text_lines={len(lines_out)} scanned={scanned}")
    print(f"figure_pages={candidates}")
    print(f"captions={len(caption_map)} (见 index.json 的 caption_pages)")


if __name__ == "__main__":
    main()
