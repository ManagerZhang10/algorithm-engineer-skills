#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pypdf>=5"]
# ///
"""quiz-drill：把任意知识库变成选择题库，本地网页刷题，记录作答，出薄弱点报告。

  quiz-drill build  <路径...> --name 名字 --out 题库目录 [--glob '**/*.md'] [--dry-run]
  quiz-drill more   <名字|目录> [--weak 5] [--n 4]     给最薄弱的知识点加题
  quiz-drill serve  <名字|目录> [--port 8765]          开本地刷题页
  quiz-drill report <名字|目录>                        写 report.md 并打印摘要
  quiz-drill list                                      列出已登记的题库

模型走任意 OpenAI 兼容接口，配置见 SKILL.md「模型与密钥」。
每道题过四关：结构、选项长度、检查模型带题干作答（必须答对且无争议）、遮题干盲猜（单选两次都猜中=选项漏答案）。
不过关的带着原因让出题模型重出，最多 --rounds 轮。
"""
import argparse, hashlib, html, json, math, os, random, re, socket, sys, threading, time, urllib.error, urllib.request, webbrowser
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY = Path.home() / ".local/share/quiz-drill/banks.json"
EXTS = {".md", ".markdown", ".txt", ".html", ".htm", ".pdf"}
LETTERS = "ABCD"
HEAD, HEND = "\x00H\x00", "\x00E\x00"   # HTML 标题标记，切知识点用


# ---------------------------------------------------------------- 模型

def _settings():
    env = {}
    f = os.environ.get("QUIZ_DRILL_ENV_FILE")
    if f and Path(f).expanduser().exists():
        for line in Path(f).expanduser().read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    env.update(os.environ)
    pick = lambda *ks, default=None: next((env[k] for k in ks if env.get(k)), default)
    s = {"key": pick("QUIZ_DRILL_API_KEY", "DEEPSEEK_API_KEY"),
         "base": pick("QUIZ_DRILL_BASE_URL", "DEEPSEEK_BASE_URL", default="https://api.deepseek.com/v1"),
         "gen": pick("QUIZ_DRILL_MODEL", "DEEPSEEK_PRO_MODEL", default="deepseek-v4-pro")}
    s["check"] = pick("QUIZ_DRILL_CHECK_MODEL", "DEEPSEEK_MODEL", default=s["gen"])
    if not s["key"]:
        sys.exit("没有找到 API 密钥：设置 QUIZ_DRILL_API_KEY（或 DEEPSEEK_API_KEY），或用 QUIZ_DRILL_ENV_FILE 指向存密钥的 env 文件")
    return s


S = None
_NO_JSON_MODE = False


def chat(system, user, pro=False, max_tokens=16000, temperature=0.3):
    """OpenAI 兼容 chat/completions，返回解析后的 JSON。reasoning 模型只取 content。"""
    global S, _NO_JSON_MODE
    S = S or _settings()
    body = {"model": S["gen"] if pro else S["check"], "max_tokens": max_tokens, "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    for wait in (10, 20, 30, None):
        if not _NO_JSON_MODE:
            body["response_format"] = {"type": "json_object"}
        else:
            body.pop("response_format", None)
        req = urllib.request.Request(
            S["base"].rstrip("/") + "/chat/completions", json.dumps(body).encode(),
            {"Content-Type": "application/json", "Authorization": "Bearer " + S["key"]})
        try:
            with urllib.request.urlopen(req, timeout=1800) as r:
                text = json.load(r)["choices"][0]["message"]["content"] or ""
            text = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
            if not text:
                raise ValueError("空正文（reasoning 模型可能把 max_tokens 用光了）")
            m = re.search(r"\{.*\}", text, re.S)
            return json.loads(m.group(0) if m else text)
        except urllib.error.HTTPError as e:
            if e.code == 400 and not _NO_JSON_MODE:   # 不支持 response_format 的接口
                _NO_JSON_MODE = True
                continue
            if wait is None or e.code in (401, 403, 404):
                raise
            time.sleep(wait)
        except Exception:
            if wait is None:
                raise
            time.sleep(wait)


# ---------------------------------------------------------------- 读知识库

class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript"}
    BLOCK = {"section", "p", "li", "div", "h3", "h4", "tr", "br", "td", "th", "pre", "text", "tspan"}
    HEADS = {"h1", "h2"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip, self.title, self.h1, self._in = [], 0, "", "", None

    def handle_starttag(self, tag, attrs):
        if tag in ("title", "h1"):
            self._in = tag
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.HEADS:
            self.parts.append("\n" + HEAD)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == self._in:
            self._in = None
        if tag in self.SKIP:
            self.skip -= 1
        elif tag in self.HEADS:
            self.parts.append(HEND)

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
            return
        if self._in == "h1" and not self.skip:
            self.h1 += data
        if not self.skip:
            self.parts.append(data)


def _norm(text):
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def read_doc(path: Path, title_sep=None):
    """返回 (标题, 全文, 小节列表[(小节标题或 None, 小节正文)])。"""
    suf = path.suffix.lower()
    sections = []
    if suf in (".html", ".htm"):
        p = _Text()
        p.feed(path.read_text(errors="ignore"))
        raw = html.unescape("".join(p.parts))
        title = html.unescape(p.title).strip() or html.unescape(p.h1).strip()
        text = _norm(raw.replace(HEAD, "").replace(HEND, ""))
        cur_h, buf = None, []
        for line in raw.replace(HEND, "\n").split("\n"):
            if line.startswith(HEAD):
                if buf:
                    sections.append((cur_h, _norm("\n".join(buf))))
                cur_h, buf = line[len(HEAD):].strip(), [line[len(HEAD):]]
            else:
                buf.append(line)
        if buf:
            sections.append((cur_h, _norm("\n".join(buf))))
    elif suf == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            sys.exit("读 PDF 需要 pypdf：pip install pypdf，或用 uv run 运行本脚本")
        text = _norm("\n".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages))
        title = ""
        sections = [(None, text)]
    else:
        raw = path.read_text(errors="ignore")
        m = re.search(r"^#\s+(.+)$", raw, re.M)
        title = m.group(1).strip() if m else ""
        text = _norm(raw)
        cur_h, buf = None, []
        for line in raw.split("\n"):
            h = re.match(r"^#{2,3}\s+(.+?)\s*#*$", line)
            if h:
                if buf:
                    sections.append((cur_h, _norm("\n".join(buf))))
                cur_h, buf = h.group(1).strip(), [line]
            else:
                buf.append(line)
        if buf:
            sections.append((cur_h, _norm("\n".join(buf))))
    if title_sep and title_sep in title:
        title = title.split(title_sep)[-1].strip()
    return title or path.stem, text, [s for s in sections if s[1]]


def collect(paths, glob):
    out = []
    for p in paths:
        p = Path(p).expanduser().resolve()
        if p.is_file():
            out.append((p.parent, p))
            continue
        files = p.glob(glob) if glob else p.rglob("*")
        for f in sorted(files):
            rel = f.relative_to(p).parts
            if f.is_file() and f.suffix.lower() in EXTS and not any(x.startswith(".") or x == "node_modules" for x in rel):
                out.append((p, f))
    return out


def split_text(text, max_chars):
    if len(text) <= max_chars:
        return [text]
    parts, cur = [], ""
    for para in text.split("\n"):
        if cur and len(cur) + len(para) > max_chars:
            parts.append(cur)
            cur = ""
        cur += para + "\n"
    if cur.strip():
        parts.append(cur)
    return parts


def topics_of(title, text, sections, split, max_chars, min_section):
    """把一份文件划成知识点：短文件整份一个；长文件（或 --split always）按二、三级标题切，过短的小节并进前一节。"""
    if split == "never" or (split == "auto" and len(text) <= max_chars) or sum(1 for h, _ in sections if h) < 2:
        return [(title, text)]
    merged = []
    for h, body in sections:
        if merged and (h is None or len(body) < min_section or len(merged[-1][1]) < min_section):
            merged[-1] = (merged[-1][0], merged[-1][1] + "\n" + body)
        else:
            merged.append((h, body))
    return [(f"{title} › {h}" if h else title, body) for h, body in merged]


def make_chunks(paths, o):
    """o: glob / split / max_chars / min_section / title_sep。"""
    chunks = []
    single = {Path(p).expanduser().resolve() for p in paths if Path(p).expanduser().is_file()}
    for root, f in collect(paths, o["glob"]):
        title, text, sections = read_doc(f, o.get("title_sep"))
        if len(text) < 200:
            continue
        rel = f.relative_to(root)
        module = rel.parts[0] if len(rel.parts) > 1 else (title if Path(f) in single else root.name)
        for topic, body in topics_of(title, text, sections, o["split"], o["max_chars"], o["min_section"]):
            if module == title and topic.startswith(title + " › "):
                topic = topic[len(title) + 3:]
            for i, piece in enumerate(split_text(body, o["max_chars"])):
                cid = hashlib.sha1(f"{f}\n{piece}".encode()).hexdigest()[:12]
                chunks.append({"id": cid, "file": str(f), "module": module, "topic": topic,
                               "part": i, "chars": len(piece), "text": piece})
    return chunks


# ---------------------------------------------------------------- 出题

def detect_lang(text):
    cjk = sum(1 for ch in text[:5000] if "一" <= ch <= "鿿")
    return "中文" if cjk > 0.1 * len(text[:5000]) else "English"


def gen_sys(o):
    style = f"\n出题风格：{o['style']}" if o.get("style") else ""
    return f"""你是一位出题老师，要依据用户给的一份学习材料出选择题，用来帮学习者巩固记忆、暴露薄弱点。
只依据材料原文出题，不凭记忆补充材料里没有的事实。题目、选项、解析一律用{o['lang']}书写。{style}

硬性要求：
1. 每题考一个材料里明确讲过的知识点，优先考「为什么」「会怎样」「区别在哪」「哪一步」，少考纯记忆的数字和名字。各题考点不要重复，尽量覆盖材料的不同部分。
2. 题型：单选是 1 个正确项 + 3 个干扰项；多选是 2~3 个正确项，凑满共 4 个选项，题干末尾注明是多选。单选和多选的数量按用户要求。
3. 干扰项必须是真实学习者常见的误解或半对的说法：术语正确、听起来合理、和题目同一话题。最好是「本身正确但没回答本题问的点」或「在另一种设定/另一种方法里成立」的说法。遮住题干只看选项时，必须无法判断哪个是答案。
4. 四个选项长度接近（字数相差不超过 20%），句式和信息量对齐；正确项不能是最长、最具体、最严谨的那个；正确项不得复用题干关键词「对暗号」。
5. 禁止「以上都对 / 以上都不对 / 都有可能」，禁止「不正确的是」这类否定题干。答案依据材料无争议。
6. 题干自成一体，不出现「材料中」「讲义里」「上文」这类指代。
7. 不用 LaTeX，公式用纯文本（如 softmax(QKᵀ/√d_k)）。
8. why_correct 一句话（40 字内）说正确项为什么对；why_wrong 与 distractors 一一对应，各一句话说错在哪，不复述选项；quote 摘一句材料原文作依据（60 字内，照抄）。

只输出 JSON：
{{"items":[{{"type":"single 或 multi","stem":"题干","correct":["正确项"],"distractors":["干扰项"],"why_correct":"...","why_wrong":["..."],"point":"考点（12 字内）","quote":"原文依据"}}]}}"""


def n_for(chunk, per_topic):
    return per_topic or max(2, min(10, round(chunk["chars"] / 600)))


def clen(s):
    return len(re.sub(r"\s", "", s))


BANNED = r"以上都|都有可能|不正确的是|错误的是|all of the above|none of the above|both a and b|which of the following (?:is|are) (?:not|incorrect|false)"
SELF_REF = r"材料|讲义|上文|文中|according to the (?:text|passage|material)|the (?:passage|material|text) (?:says|states|mentions)"


def check_struct(it):
    c, d = it.get("correct") or [], it.get("distractors") or []
    if isinstance(c, str):
        c = it["correct"] = [c]
    t = it.get("type")
    if len(c) + len(d) != 4 or len(set(c + d)) != 4:
        return "选项必须正好 4 个且互不相同"
    if t == "single" and len(c) != 1 or t == "multi" and not 2 <= len(c) <= 3 or t not in ("single", "multi"):
        return f"题型 {t} 与正确项数 {len(c)} 不符"
    if len(it.get("why_wrong") or []) != len(d):
        return "why_wrong 与干扰项数量不一致"
    if re.search(BANNED, it.get("stem", "") + " " + " ".join(c + d), re.I):
        return "出现了禁用句式"
    if re.search(SELF_REF, it.get("stem", ""), re.I):
        return "题干引用了「材料/讲义」，没有自成一体"
    return None


def check_length(it):
    ls = [clen(x) for x in it["correct"] + it["distractors"]]
    lo, hi = min(ls), max(ls)
    if hi and (hi - lo) / hi > 0.3:
        return f"四个选项字数 {ls} 相差超过 30%"
    if it["type"] == "single" and ls[0] == hi and ls.count(hi) == 1 and hi - sorted(ls)[-2] > 2:
        return "正确项明显比其他选项都长"
    return None


def shuffled(it, seed):
    opts = [(x, True) for x in it["correct"]] + [(x, False) for x in it["distractors"]]
    random.Random(seed).shuffle(opts)
    return [o for o, _ in opts], "".join(sorted(LETTERS[i] for i, (_, ok) in enumerate(opts) if ok))


def fmt(opts):
    return "\n".join(f"{LETTERS[i]}. {o}" for i, o in enumerate(opts))


def check_answer(it):
    opts, ans = shuffled(it, 7)
    r = chat("你在做一道选择题（可能单选也可能多选）。只输出 JSON：{\"answer\":\"正确项字母，多选按字母顺序连写如 AC\",\"disputed\":false,\"note\":\"若认为题目有歧义、多个答案或没有正确答案，disputed 为 true 并说明\"}",
             f"{it['stem']}\n{fmt(opts)}", max_tokens=8000)
    got = "".join(sorted(re.sub(r"[^A-D]", "", str(r.get("answer", "")).upper())))
    if r.get("disputed"):
        return f"作答模型认为有争议：{r.get('note', '')}"
    if got != ans:
        return f"作答模型选了 {got}，标准答案 {ans}（题目可能不严谨或答案有误）"
    return None


def check_blind(it):
    if it["type"] != "single":
        return None
    hits, cue = 0, ""
    for seed in (1, 2):
        opts, ans = shuffled(it, seed)
        r = chat("你在做一道单选题，但题干被遮住了，只能看到四个选项。根据选项措辞、长度、严谨程度等线索猜最可能正确的一项。只输出 JSON：{\"answer\":\"A\",\"cue\":\"靠什么线索，一句话\"}",
                 fmt(opts), max_tokens=4000)
        if str(r.get("answer", "")).strip()[:1].upper() == ans:
            hits += 1
            cue = r.get("cue", "")
    return f"遮住题干也能猜中（{cue}）" if hits == 2 else None


def even_out(it):
    """长度不齐时让检查模型改写选项到长度接近、意思不变，再复检。"""
    r = chat("把一道选择题的选项改写成长度接近（字数相差不超过 20%）、句式对齐，**每个选项的意思和对错不变**，语言与原文一致，正确项不能是最长或最严谨的那个。"
             "只输出 JSON：{\"correct\":[与输入同序],\"distractors\":[与输入同序]}",
             json.dumps({"stem": it["stem"], "correct": it["correct"], "distractors": it["distractors"]}, ensure_ascii=False), max_tokens=8000)
    c, d = r.get("correct") or [], r.get("distractors") or []
    if len(c) == len(it["correct"]) and len(d) == len(it["distractors"]):
        it["correct"], it["distractors"] = c, d


def audit(it):
    if check_struct(it) is None and check_length(it):
        try:
            even_out(it)
        except Exception:
            pass
    for f in (check_struct, check_length, check_answer, check_blind):
        try:
            why = f(it)
        except Exception as e:
            why = f"质检调用失败：{e}"
        if why:
            return why
    return None


def gen_chunk(chunk, n, o, avoid=()):
    passed, rejected, need, feedback = [], [], n, ""
    cap_total = math.ceil(n * o["multi"]) if o["multi"] > 0 else 0
    n_multi = lambda: sum(p["type"] == "multi" for p in passed)
    for rnd in range(o["rounds"]):
        cap = cap_total - n_multi()
        ask = need + max(2, need // 2)
        user = (f"# 材料：{chunk['topic']}\n\n{chunk['text']}\n\n---\n请出 {ask} 道题" +
                (f"，其中多选约 {cap} 道、不超过 {cap} 道，其余单选。" if cap > 0 else "，全部出单选。"))
        if avoid or passed:
            user += "\n不要与下列已有题目考同一个点：\n" + "\n".join(f"- {s}" for s in list(avoid) + [p["stem"] for p in passed])
        if feedback:
            user += "\n上一批有题没过质检，原因如下，这次避免：\n" + feedback
        try:
            items = chat(gen_sys(o), user, pro=True).get("items", [])
        except Exception as e:
            rejected.append({"round": rnd, "reason": f"出题调用失败：{e}"})
            continue
        with ThreadPoolExecutor(4) as ex:
            verdicts = list(ex.map(audit, items))
        reasons = []
        for it, why in zip(items, verdicts):
            if why:
                rejected.append({"round": rnd, "reason": why, "item": it})
                reasons.append(f"- 「{it.get('stem', '')[:40]}」：{why}")
            elif len(passed) < n and (it["type"] == "single" or n_multi() < cap_total):
                passed.append(it)
        need = n - len(passed)
        if need <= 0:
            break
        feedback = "\n".join(reasons)
    return passed, rejected


def qid(stem):
    return hashlib.sha1(stem.strip().encode()).hexdigest()[:10]


def assemble(out: Path):
    meta = json.loads((out / "bank_meta.json").read_text())
    names = meta.get("module_names", {})
    qs, seen = [], set()
    for cid in meta["chunks"]:
        g = out / "gen" / f"{cid}.json"
        if not g.exists():
            continue
        rec = json.loads(g.read_text())
        for it in rec["items"]:
            q = {"id": qid(it["stem"]), "module": names.get(rec["module"], rec["module"]), "topic": rec["topic"], "file": rec["file"],
                 "type": it["type"], "stem": it["stem"], "point": it.get("point", ""), "quote": it.get("quote", ""),
                 "options": [{"text": t, "ok": True, "why": it["why_correct"]} for t in it["correct"]] +
                            [{"text": t, "ok": False, "why": w} for t, w in zip(it["distractors"], it["why_wrong"])]}
            if q["id"] not in seen:
                seen.add(q["id"])
                qs.append(q)
    bank = {"name": meta["name"], "built_at": datetime.now().isoformat(timespec="seconds"), "questions": qs}
    (out / "bank.json").write_text(json.dumps(bank, ensure_ascii=False, indent=1))
    return bank


def register(name, out):
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    reg = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    reg[name] = str(out)
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=1))


def resolve(name_or_dir):
    p = Path(name_or_dir).expanduser()
    if (p / "bank_meta.json").exists():
        return p.resolve()
    reg = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    if name_or_dir in reg:
        return Path(reg[name_or_dir])
    sys.exit(f"找不到题库 {name_or_dir}；用 quiz-drill list 看已登记的题库")


def run_jobs(out, jobs, o):
    """jobs: [(chunk, n, avoid)]；结果追加进 gen/<cid>.json。"""
    (out / "gen").mkdir(exist_ok=True)
    done = [0]
    lock = threading.Lock()

    def one(job):
        chunk, n, avoid = job
        passed, rejected = gen_chunk(chunk, n, o, avoid)
        g = out / "gen" / f"{chunk['id']}.json"
        with lock:
            rec = json.loads(g.read_text()) if g.exists() else {k: chunk[k] for k in ("id", "file", "module", "topic", "chars")} | {"items": [], "rejected": []}
            rec["items"] += passed
            rec["rejected"] += rejected
            g.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
            done[0] += 1
            print(f"[{done[0]}/{len(jobs)}] {chunk['topic'][:40]}：通过 {len(passed)}/{n}，淘汰 {len(rejected)}", flush=True)

    with ThreadPoolExecutor(o["workers"]) as ex:
        list(ex.map(one, jobs))


OPT_KEYS = ("glob", "split", "max_chars", "min_section", "title_sep", "lang", "style", "multi", "per_topic", "rounds")


def cmd_build(a):
    out = Path(a.out).expanduser().resolve()
    meta_p = out / "bank_meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {"name": a.name, "sources": [], "chunks": [], "options": {}}
    o = {k: getattr(a, k) for k in OPT_KEYS}
    chunks = make_chunks(a.paths, o)
    if a.limit:
        chunks = chunks[:a.limit]
    if not chunks:
        sys.exit("没读到任何材料（支持 .md .txt .html .pdf；检查路径和 --glob）")
    if o["lang"] == "auto":
        o["lang"] = detect_lang("\n".join(c["text"] for c in chunks[:5]))
    done = lambda c: (out / "gen" / f"{c['id']}.json").exists() and json.loads((out / "gen" / f"{c['id']}.json").read_text())["items"]
    todo = [c for c in chunks if not done(c)]
    by_topic = Counter((c["module"], c["topic"]) for c in chunks)
    print(f"材料 {len(collect(a.paths, a.glob))} 个文件 → {len(by_topic)} 个知识点、{len(chunks)} 块；待出题 {len(todo)} 块；出题语言：{o['lang']}", flush=True)
    if a.dry_run:
        for c in chunks:
            print(f"  [{c['module']}] {c['topic']}  {c['chars']} 字 → 约 {n_for(c, o['per_topic'])} 题{'' if c in todo else '（已出过）'}")
        return
    out.mkdir(parents=True, exist_ok=True)
    meta["name"] = a.name
    meta["sources"] = sorted(set(meta["sources"]) | {str(Path(p).expanduser().resolve()) for p in a.paths})
    meta["chunks"] = list(dict.fromkeys(meta["chunks"] + [c["id"] for c in chunks]))
    meta["options"] = o
    if a.module_names:
        meta["module_names"] = json.loads(Path(a.module_names).read_text())
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    register(a.name, out)
    run_jobs(out, [(c, n_for(c, o["per_topic"]), ()) for c in todo], o | {"workers": a.workers})
    bank = assemble(out)
    print(f"题库：{out / 'bank.json'}，共 {len(bank['questions'])} 题")


def cmd_more(a):
    out = resolve(a.bank)
    meta = json.loads((out / "bank_meta.json").read_text())
    o = {"glob": None, "split": "auto", "max_chars": 9000, "min_section": 600, "title_sep": None,
         "lang": "中文", "style": "", "multi": 0.2, "per_topic": 0, "rounds": 4} | meta.get("options", {})
    rep = stats(out)
    if a.topics:
        weak = [t.strip() for t in a.topics.split(",")]
    else:
        weak = [t["topic"] for t in rep["weak"][:a.weak]]
    if not weak:
        sys.exit("还没有足够的作答记录判断薄弱点，先刷一轮（或用 --topics 指定知识点）")
    chunks = {c["id"]: c for c in make_chunks(meta["sources"], o)}
    jobs = []
    for cid in meta["chunks"]:
        g = out / "gen" / f"{cid}.json"
        if cid in chunks and g.exists():
            rec = json.loads(g.read_text())
            if rec["topic"] in weak:
                jobs.append((chunks[cid], a.n, [it["stem"] for it in rec["items"]]))
    if not jobs:
        sys.exit("这些知识点的原文找不到了（文件改过或移动过），先重新 build")
    print("给这些知识点加题：" + "、".join(weak), flush=True)
    run_jobs(out, jobs, o | {"workers": a.workers})
    print(f"题库：{out / 'bank.json'}，共 {len(assemble(out)['questions'])} 题")

# ---------------------------------------------------------------- 统计与报告

def read_jsonl(p):
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def stats(out: Path):
    bank = json.loads((out / "bank.json").read_text())
    flagged = {f["qid"] for f in read_jsonl(out / "flags.jsonl")}
    qs = {q["id"]: q for q in bank["questions"] if q["id"] not in flagged}
    log = [r for r in read_jsonl(out / "log.jsonl") if r["qid"] in qs]
    per_q = defaultdict(lambda: {"n": 0, "ok": 0, "first": None, "last": None, "wrong": Counter()})
    for r in log:
        s = per_q[r["qid"]]
        s["n"] += 1
        s["ok"] += r["correct"]
        s["first"] = r["correct"] if s["first"] is None else s["first"]
        s["last"] = r["correct"]
        if not r["correct"]:
            for t in r["chosen"]:
                if not any(o["text"] == t and o["ok"] for o in qs[r["qid"]]["options"]):
                    s["wrong"][t] += 1

    def group(key):
        g = defaultdict(lambda: {"total": 0, "seen": 0, "attempts": 0, "ok": 0, "last_ok": 0, "first_ok": 0, "wrong_points": Counter()})
        for q in qs.values():
            k = q[key] if key != "topic" else (q["module"], q["topic"])
            x = g[k]
            x["total"] += 1
            s = per_q.get(q["id"])
            if s:
                x["seen"] += 1
                x["attempts"] += s["n"]
                x["ok"] += s["ok"]
                x["last_ok"] += bool(s["last"])
                x["first_ok"] += bool(s["first"])
                if not s["last"] and q["point"]:
                    x["wrong_points"][q["point"]] += 1
        rows = []
        for k, x in g.items():
            mod, top = k if key == "topic" else (k, None)
            rows.append({"module": mod, "topic": top, "total": x["total"], "seen": x["seen"], "attempts": x["attempts"],
                         "acc": round(x["ok"] / x["attempts"], 3) if x["attempts"] else None,
                         "mastery": round(x["last_ok"] / x["seen"], 3) if x["seen"] else None,
                         "first_acc": round(x["first_ok"] / x["seen"], 3) if x["seen"] else None,
                         "wrong_points": [p for p, _ in x["wrong_points"].most_common(4)]})
        return rows

    topics = group("topic")
    modules = sorted(group("module"), key=lambda r: r["module"])
    weak = sorted([t for t in topics if t["seen"] >= 2 and t["mastery"] < 1],
                  key=lambda t: (t["mastery"], t["first_acc"], -t["seen"]))
    repeat = []
    for k, s in per_q.items():
        if s["n"] - s["ok"] >= 2 or (s["n"] >= 1 and not s["last"]):
            q = qs[k]
            repeat.append({"id": k, "topic": q["topic"], "stem": q["stem"], "point": q["point"], "wrong_n": s["n"] - s["ok"],
                           "n": s["n"], "last_ok": bool(s["last"]),
                           "answer": [o["text"] for o in q["options"] if o["ok"]],
                           "picked": [t for t, _ in s["wrong"].most_common(2)],
                           "why": next(o["why"] for o in q["options"] if o["ok"])})
    repeat.sort(key=lambda r: (r["last_ok"], -r["wrong_n"]))
    days = defaultdict(lambda: [0, 0])
    for r in log:
        d = days[r["ts"][:10]]
        d[0] += 1
        d[1] += r["correct"]
    seen = len(per_q)
    return {"name": bank["name"], "total": len(qs), "seen": seen, "attempts": len(log),
            "acc": round(sum(r["correct"] for r in log) / len(log), 3) if log else None,
            "first_acc": round(sum(bool(s["first"]) for s in per_q.values()) / seen, 3) if seen else None,
            "mastery": round(sum(bool(s["last"]) for s in per_q.values()) / seen, 3) if seen else None,
            "wrong_now": sum(1 for s in per_q.values() if not s["last"]),
            "flagged": len(flagged),
            "modules": modules, "weak": weak, "repeat": repeat[:30],
            "untouched": [t for t in topics if t["seen"] == 0],
            "days": [{"day": d, "n": v[0], "acc": round(v[1] / v[0], 3)} for d, v in sorted(days.items())]}


def pct(x):
    return "—" if x is None else f"{round(x * 100)}%"


def cmd_report(a):
    out = resolve(a.bank)
    s = stats(out)
    L = [f"# 刷题报告：{s['name']}", "", f"生成于 {datetime.now():%Y-%m-%d %H:%M}", ""]
    if not s["attempts"]:
        L.append("还没有作答记录。")
    else:
        top = "、".join(t["topic"] for t in s["weak"][:3]) or "暂无（做过的知识点最近一次都答对了）"
        L += [f"**一句话**：做过 {s['seen']}/{s['total']} 题，共作答 {s['attempts']} 次；第一次就答对 {pct(s['first_acc'])}，"
              f"目前最近一次答对 {pct(s['mastery'])}。最该补的：{top}。", "",
              "口径：「首答正确率」= 第一次见到就答对的比例，最能反映原本会不会；「掌握度」= 最近一次答对的比例，反映复习后的状态。", "",
              "## 薄弱知识点（至少做过 2 题，按掌握度从低到高）", "",
              "| 知识点 | 模块 | 做过/总题 | 首答正确率 | 掌握度 | 还没掌握的考点 |", "| --- | --- | ---: | ---: | ---: | --- |"]
        L += [f"| {t['topic']} | {t['module']} | {t['seen']}/{t['total']} | {pct(t['first_acc'])} | {pct(t['mastery'])} | {'、'.join(t['wrong_points'])} |" for t in s["weak"][:15]]
        L += ["", "## 各模块", "", "| 模块 | 做过/总题 | 首答正确率 | 掌握度 |", "| --- | ---: | ---: | ---: |"]
        L += [f"| {m['module']} | {m['seen']}/{m['total']} | {pct(m['first_acc'])} | {pct(m['mastery'])} |" for m in s["modules"]]
        L += ["", "## 还没答对 / 反复答错的题", ""]
        for r in s["repeat"][:20]:
            L += [f"- **{r['stem']}**（{r['topic']} · 错 {r['wrong_n']}/{r['n']} 次{'，最近一次已答对' if r['last_ok'] else ''}）",
                  f"  - 正确答案：{'；'.join(r['answer'])}", f"  - 你常选的错项：{'；'.join(r['picked']) or '—'}", f"  - 要点：{r['why']}"]
        L += ["", "## 每日", "", "| 日期 | 作答 | 正确率 |", "| --- | ---: | ---: |"]
        L += [f"| {d['day']} | {d['n']} | {pct(d['acc'])} |" for d in s["days"]]
        if s["untouched"]:
            L += ["", f"## 还没碰过的知识点（{len(s['untouched'])} 个）", "", "、".join(t["topic"] for t in s["untouched"])]
    (out / "report.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[:8]))
    print(f"\n完整报告：{out / 'report.md'}")


# ---------------------------------------------------------------- 本地刷题页

def cmd_serve(a):
    out = resolve(a.bank)
    assemble(out)
    page = (HERE / "page.html").read_text().replace("/*QUIZ_CONFIG*/", f"window.QUIZ_CONFIG = {{round: {a.round}}};")
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            b = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self._send(200, page, "text/html; charset=utf-8")
            if self.path == "/api/bank":
                return self._send(200, (out / "bank.json").read_bytes())
            if self.path == "/api/log":
                flags = [f["qid"] for f in read_jsonl(out / "flags.jsonl")]
                return self._send(200, {"log": read_jsonl(out / "log.jsonl"), "flags": flags})
            if self.path == "/api/report":
                return self._send(200, stats(out))
            self._send(404, {"error": "not found"})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            body["ts"] = datetime.now().isoformat(timespec="seconds")
            name = {"/api/answer": "log.jsonl", "/api/flag": "flags.jsonl"}.get(self.path)
            if not name:
                return self._send(404, {"error": "not found"})
            with lock, open(out / name, "a") as f:
                f.write(json.dumps(body, ensure_ascii=False) + "\n")
            self._send(200, {"ok": True})

    port = a.port
    while True:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)):
                break
        port += 1
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{port}/"
    print(f"刷题页：{url}\n题库：{out}\nCtrl+C 退出", flush=True)
    if not a.no_open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def cmd_list(a):
    reg = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    for k, v in reg.items():
        n = len(json.loads((Path(v) / "bank.json").read_text())["questions"]) if (Path(v) / "bank.json").exists() else 0
        print(f"{k}\t{n} 题\t{v}")


def main():
    ap = argparse.ArgumentParser(prog="quiz-drill", description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build", help="从知识库出题（增量，已出过的知识点跳过）")
    b.add_argument("paths", nargs="+")
    b.add_argument("--name", required=True)
    b.add_argument("--out", required=True, help="题库目录，建议放在知识库所属项目里且不进 Git")
    b.add_argument("--glob", default=None, help="只取匹配的文件，如 '**/*.md'")
    b.add_argument("--split", choices=["auto", "always", "never"], default="auto",
                   help="知识点怎么划：auto=长文件按二三级标题切、短文件整份一个；always=总按标题切；never=一个文件一个知识点")
    b.add_argument("--max-chars", type=int, default=9000, help="超过这个字数的文件 auto 模式下按标题切；单块上限也是它")
    b.add_argument("--min-section", type=int, default=600, help="短于这个字数的小节并进前一节")
    b.add_argument("--title-sep", default=None, help="HTML 标题里的分隔符，取最后一段作知识点名，如 ' · '")
    b.add_argument("--lang", default="auto", help="出题语言：auto 跟随原文，或写明如 中文 / English")
    b.add_argument("--style", default="", help="出题风格补充，如「面试官口吻，偏原理和对比」")
    b.add_argument("--multi", type=float, default=0.2, help="多选题占比上限，0 = 只出单选")
    b.add_argument("--per-topic", type=int, default=0, help="每个知识点出几题；默认按长度 2~10")
    b.add_argument("--module-names", default=None, help="JSON 文件：{目录名: 显示名}")
    b.add_argument("--limit", type=int, default=0, help="只处理前 N 块（试跑用）")
    b.add_argument("--dry-run", action="store_true", help="只列出知识点划分和计划题量，不调模型")
    m = sp.add_parser("more", help="给最薄弱的知识点加题")
    m.add_argument("bank")
    m.add_argument("--weak", type=int, default=5, help="取报告里最弱的几个知识点")
    m.add_argument("--topics", default=None, help="直接指定知识点名，逗号分隔")
    m.add_argument("--n", type=int, default=4, help="每个知识点加几题")
    for x in (b, m):
        x.add_argument("--workers", type=int, default=8)
    b.add_argument("--rounds", type=int, default=4, help="不过质检时最多重出几轮")
    s = sp.add_parser("serve", help="开本地刷题页")
    s.add_argument("bank")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--round", type=int, default=20, help="每轮几题")
    s.add_argument("--no-open", action="store_true")
    r = sp.add_parser("report", help="出薄弱点报告")
    r.add_argument("bank")
    sp.add_parser("list", help="列出题库")
    a = ap.parse_args()
    {"build": cmd_build, "more": cmd_more, "serve": cmd_serve, "report": cmd_report, "list": cmd_list}[a.cmd](a)


if __name__ == "__main__":
    main()
