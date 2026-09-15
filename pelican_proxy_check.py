#!/usr/bin/env python3
"""鹈鹕骑自行车：让若干条「模型 x 通道」画同一张 SVG，并量出各通道的元数据指纹。

同题、同 prompt、同 max_tokens，横着看差距。每条泳道每轮只打这一发，
判读全部来自它的响应：服务端自己报回来的 input token 数、思考 token、响应 id
和 usage 字段 —— 中转层若塞了隐藏上下文或关掉了思考，最先从这几个数字漏出来。

全程流式：reasoning 模型思考几分钟不吐字是常态，非流式会直接读超时。
思考段一律丢掉，只留正文里的 <svg>。凭证只从配置文件读，任何输出里都不写 key。

用法 / Usage:
    pelican_eval.py proxy-check                 跑一轮并刷新看板 / run one round, refresh the board
    pelican_eval.py proxy-check render          只用已有快照重出看板 / rebuild from snapshots, no API spend
    pelican_eval.py proxy-check --open          跑完顺手打开看板 / open the board when done
    pelican_eval.py proxy-check --config PATH   泳道配置路径 / lanes config
                                           (默认 default: ~/.config/pelican-bicycle-eval/lanes.env)
    pelican_eval.py proxy-check --out DIR       快照与看板目录 / snapshot + board dir
                                           (默认 default: ~/.local/share/pelican-bicycle-eval/proxy-check)
    pelican_eval.py proxy-check --keep N        保留最近 N 轮 / keep the last N rounds (默认 default: 3)
    pelican_eval.py proxy-check --anonymize     通道名抹成「中转 A/B」，便于外发 / anonymise channel names
    pelican_eval.py proxy-check --lang en       看板语言 / board language: zh (默认 default) | en
    pelican_eval.py proxy-check --help          打印本帮助 / print this help

入 token 的差值只在**同一个 model** 的泳道之间算（基线由 PB_<名>_BASELINE=true 指定，
未指定时回退到 channel 名里带「直连」/ direct 的那条）。跨 model 不比：各家分词器不同。
Input-token deltas are computed only between lanes on the SAME model — tokenizers differ
across vendors, so a cross-model delta is meaningless.
"""
import base64
import concurrent.futures as cf
import difflib
import html
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

NEW_ENV_FILE = Path.home() / ".config/pelican-bicycle-eval/lanes.env"
LEGACY_ENV_FILE = Path.home() / ".config/pelican-proxy-check/lanes.env"
ENV_FILE = NEW_ENV_FILE if NEW_ENV_FILE.exists() or not LEGACY_ENV_FILE.exists() else LEGACY_ENV_FILE
NEW_ROOT = Path.home() / ".local/share/pelican-bicycle-eval/proxy-check"
LEGACY_ROOT = Path.home() / ".local/share/pelican-proxy-check"
ROOT = NEW_ROOT if NEW_ROOT.exists() or not LEGACY_ROOT.exists() else LEGACY_ROOT
RUNS = ROOT / "runs"
LOCK = ROOT / "run.lock"
KEEP = 3


LANG = "zh"

# 已知的命令行词表。写错一个字母就静默忽略是不行的：--anonymise（英式拼写）曾经
# 让看板照出、服务商真名原样留在 HTML 里 —— 隐私开关静默失败等于没有这个开关。
VALUE_FLAGS = ("--config", "--out", "--keep", "--lang")
BOOL_FLAGS = ("--open", "--anonymize", "--help", "-h")
POSITIONALS = ("render",)
KNOWN = VALUE_FLAGS + BOOL_FLAGS + POSITIONALS


def bad_arg(a):
    near = difflib.get_close_matches(a, KNOWN, n=2, cutoff=0.5)
    hint = ("，你是不是想写 / did you mean: " + " / ".join(near)) if near else ""
    sys.exit(f"不认识的参数 / unknown argument: {a}{hint}\n"
             f"可用 / available: {' '.join(KNOWN)}\n"
             f"完整帮助 / full help: {Path(sys.argv[0]).name} --help")


def need_value(flag, rest):
    if not rest:
        sys.exit(f"{flag} 后面要跟一个值 / {flag} needs a value\n"
                 f"例如 / e.g.: {flag} "
                 + {"--config": "~/.config/pelican-bicycle-eval/lanes.env",
                    "--out": "~/.local/share/pelican-bicycle-eval/proxy-check",
                    "--keep": "3", "--lang": "en"}[flag])
    return rest.pop(0)


def apply_cli(argv):
    """路径和保留轮数都可以从命令行改，好让同一份脚本服务多套配置。
    -h/--help 在这里就拦下来 —— 帮助不能被后面的「没有泳道配置」挡住。"""
    global ENV_FILE, ROOT, RUNS, LOCK, KEEP, LANG
    args, rest = [], list(argv)
    while rest:
        a = rest.pop(0)
        if a in ("-h", "--help"):
            print(__doc__.strip())
            sys.exit(0)
        elif a == "--config":
            ENV_FILE = Path(need_value(a, rest)).expanduser()
        elif a == "--out":
            ROOT = Path(need_value(a, rest)).expanduser()
        elif a == "--keep":
            v = need_value(a, rest)
            try:
                KEEP = max(1, int(v))
            except ValueError:
                sys.exit(f"--keep 要一个整数 / --keep wants an integer, got: {v}")
        elif a == "--lang":
            v = need_value(a, rest).lower()
            if v not in LABELS:
                sys.exit(f"--lang 只支持 / only supports: {', '.join(LABELS)}（got: {v}）")
            LANG = v
        elif a in BOOL_FLAGS or a in POSITIONALS:
            args.append(a)
        else:
            bad_arg(a)
    RUNS, LOCK = ROOT / "runs", ROOT / "run.lock"
    return args
TIMEOUT = 900          # 流式下这是「两个 chunk 之间」的上限，不是整轮上限
MAX_TOKENS = 32000     # reasoning 模型给小了会被思考吃光；16000 时 deepseek 的 svg 画到一半被截断
CST = timezone(timedelta(hours=8))

# usage 里这些是各家都有的标准字段；此外冒出来的都记下来，那是中转站的指纹
STANDARD_USAGE = {
    "prompt_tokens", "completion_tokens", "total_tokens",
    "prompt_tokens_details", "completion_tokens_details",
    "input_tokens", "output_tokens", "output_tokens_details",
    "cache_creation_input_tokens", "cache_read_input_tokens", "cache_creation",
    "service_tier", "inference_geo",
}


def usage_fingerprint(usage):
    """从 usage 里挑出非标准字段 —— 那是中转站的指纹。"""
    usage = usage or {}
    extra = sorted(k for k in usage if k not in STANDARD_USAGE)
    values = {k: usage[k] for k in extra if isinstance(usage[k], (int, float, str))}
    return extra, values

# 原版题面，逐字不改：满世界流传的对比图都是拿它跑的，改了就没法跟公开语料横着比。
# 只说 pelican，模型默认画白鹈鹕 —— 那正是这个梗通行的样子。
# 末尾那句「只回 SVG」是我们加的，纯为机器能抽出代码，不构成额外约束。
PROMPT_VERSION = "original"
PROMPT = ("Generate an SVG of a pelican riding a bicycle. "
          "Respond with the raw SVG markup only — no prose, no markdown fences.")

# 题面没禁这些，但它们等于绕过作图：贴位图、用文字/emoji 冒充、引外部素材、塞脚本
CHEAT_TAGS = ("image", "text", "tspan", "script", "foreignobject")
CHEAT_HREF = re.compile(r'(?:xlink:)?href\s*=\s*["\']\s*(?:https?:)?//', re.I)


def cheats(svg):
    """返回命中的作弊手段列表；空列表表示这张是老老实实画出来的。"""
    hits = [tag for tag in CHEAT_TAGS
            if re.search(rf"<{tag}\b", svg, re.I)]
    if CHEAT_HREF.search(svg):
        hits.append("外部引用")
    return hits


ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def check_perms(path):
    """配置文件里是明文密钥。比 600 宽就拒跑 —— 公开工具不能靠一句注释提醒。"""
    if os.name == "nt":
        return
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        sys.exit(f"{path} 权限是 {mode:04o}，组和其他用户可读，而里面是明文密钥。\n"
                 f"先执行：chmod 600 {path}")


def load_env():
    """读泳道配置。值里的 ${VAR} 展开成同名环境变量 ——
    key 已经在 shell 环境里的人不用再抄一遍，配置文件里也就不必落明文。"""
    check_perms(ENV_FILE)
    cfg, missing = {}, []

    def expand(v, key):
        def sub(m):
            got = os.environ.get(m.group(1))
            if got is None:
                missing.append(f"{key} 引用了 ${{{m.group(1)}}}，但该环境变量没设")
                return ""
            return got
        return ENV_REF.sub(sub, v)

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        cfg[k] = expand(v.strip().strip('"').strip("'"), k)
    if missing:
        sys.exit("配置里有引用不到的环境变量：\n  " + "\n  ".join(missing))
    return cfg


def join(base, suffix):
    """把 base_url 归一到带 suffix 的完整端点，base 自己带了就不重复补。"""
    base = base.rstrip("/")
    head = suffix.split("/")[0]
    if base.endswith("/" + head):
        base = base[: -len(head) - 1]
    return f"{base}/{suffix}"


# 泳道名和行序都从配置里推，不写死在代码里 ——
# 加一条泳道只改配置文件，脚本不动，这样同一份脚本能服务多套配置。
LANE_NAME_RE = re.compile(r"^PB_(.+)_BASE_URL$")


def lane_order(E):
    """显式 PB_LANE_ORDER 优先；否则按配置文件里 BASE_URL 出现的先后排。"""
    explicit = E.get("PB_LANE_ORDER", "").strip()
    if explicit:
        return tuple(s.strip() for s in explicit.split(",") if s.strip())
    out = []
    for key in E:
        m = LANE_NAME_RE.match(key)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return tuple(out)


def lanes(E):
    """泳道全部由 lanes.env 里的 PB_<名>_* 描述，换模型换通道只改那个文件，不动代码。"""
    out, broken = [], []
    for slot in lane_order(E):
        def g(k, d=None, _s=slot):
            return E.get(f"PB_{_s}_{k}", d)
        base, api_key, model = g("BASE_URL"), g("API_KEY"), g("MODEL")
        # 缺一行就静默跳过是不行的：「基线 + 被测中转」成对配置里丢一条，结论直接作废
        lack = [f"PB_{slot}_{k}" for k, v in
                (("BASE_URL", base), ("API_KEY", api_key), ("MODEL", model)) if not v]
        if lack:
            broken.append(f"泳道 {slot} 缺少 / lane {slot} is missing: " + "、".join(lack))
            continue
        proto = g("PROTO", "openai")
        extra = json.loads(g("EXTRA", "{}"))
        lane = dict(key=slot.lower(), name=model, channel=g("CHANNEL", ""),
                    model=model, proto=proto, proxy=g("EGRESS_PROXY") or g("PROXY"),
                    effort=g("EFFORT", ""), extra=extra,
                    baseline=str(g("BASELINE", "")).strip().lower() in ("1", "true", "yes", "on"))
        if proto == "anthropic":
            lane.update(
                url=join(base, "v1/messages"),
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                body={"model": model, "max_tokens": MAX_TOKENS, "stream": True,
                      "messages": [{"role": "user", "content": PROMPT}], **extra})
        else:
            cap = g("TOKEN_CAP", "max_tokens")
            lane.update(
                url=join(base, "v1/chat/completions"),
                headers={"Authorization": "Bearer " + api_key},
                body={"model": model, cap: MAX_TOKENS, "stream": True,
                      "stream_options": {"include_usage": True},
                      "messages": [{"role": "user", "content": PROMPT}], **extra})
        out.append(lane)
    if broken:
        sys.exit("泳道配置不完整（每条泳道至少要 BASE_URL / API_KEY / MODEL 三行）：\n"
                 "Incomplete lane config (each lane needs BASE_URL / API_KEY / MODEL):\n  "
                 + "\n  ".join(broken)
                 + f"\n配置文件 / config: {ENV_FILE}")
    if not out:
        sys.exit(f"{ENV_FILE} 里没有可用的泳道 / no usable lane found.\n"
                 f"照着 lanes.env.example 至少配一条 PB_<名>_BASE_URL / _API_KEY / _MODEL。")
    return out


def stream(lane):
    """跑一条泳道，返回正文和用量。ttft 记的是第一个正文字符，不是第一个 chunk ——
    reasoning 模型先吐几千 token 思考，那段不该算进「多久开始干活」。"""
    req = urllib.request.Request(
        lane["url"], data=json.dumps(lane["body"]).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream",
                 **lane["headers"]})
    proxy = lane.get("proxy")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {}))
    started = time.time()
    parts, ttft, pt, ct, echoed, rt = [], None, None, None, None, None
    resp_id, usage_seen = None, {}
    with opener.open(req, timeout=TIMEOUT) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            piece = ""
            if lane["proto"] == "anthropic":
                kind = ev.get("type")
                if kind == "message_start":
                    msg = ev.get("message") or {}
                    echoed = msg.get("model")
                    resp_id = resp_id or msg.get("id")
                    # anthropic 把 usage 拆在 message_start 和 message_delta 两处，合起来看
                    usage_seen.update(msg.get("usage") or {})
                    pt = (msg.get("usage") or {}).get("input_tokens")
                elif kind == "content_block_delta":
                    piece = (ev.get("delta") or {}).get("text") or ""
                elif kind == "message_delta":
                    u = ev.get("usage") or {}
                    usage_seen.update(u)
                    ct = u.get("output_tokens", ct)
                    rt = (u.get("output_tokens_details") or {}).get("thinking_tokens", rt)
            else:
                echoed = ev.get("model") or echoed
                resp_id = resp_id or ev.get("id")
                u = ev.get("usage")
                if u:
                    usage_seen.update(u)
                    pt = u.get("prompt_tokens", pt)
                    ct = u.get("completion_tokens", ct)
                    rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens", rt)
                for ch in ev.get("choices") or []:
                    piece += (ch.get("delta") or {}).get("content") or ""
            if piece:
                if ttft is None:
                    ttft = round((time.time() - started) * 1000)
                parts.append(piece)
    extra, values = usage_fingerprint(usage_seen)
    return {"text": "".join(parts), "prompt_tokens": pt, "completion_tokens": ct,
            "reasoning_tokens": rt, "model_echoed": echoed, "ttft_ms": ttft,
            "latency_ms": round((time.time() - started) * 1000),
            "response_id": str(resp_id or "")[:24],
            "usage_extra": extra, "usage_extra_values": values}


SVG_RE = re.compile(r"<svg\b.*?</svg>", re.S | re.I)
SHAPE_RE = re.compile(r"<(path|circle|ellipse|rect|polygon|polyline|line)\b", re.I)


def run_lane(lane):
    rec = {"key": lane["key"], "name": lane["name"], "channel": lane["channel"],
           "model": lane["model"], "effort": lane.get("effort", ""),
           "baseline": bool(lane.get("baseline")), "ok": False, "error": None}
    started = time.time()
    try:
        res = stream(lane)
    except urllib.error.HTTPError as e:
        rec.update(error=f"HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}",
                   latency_ms=round((time.time() - started) * 1000))
        return rec, None
    except Exception as e:
        rec.update(error=f"{type(e).__name__}: {e}"[:200],
                   latency_ms=round((time.time() - started) * 1000))
        return rec, None
    text = res["text"]
    rec.update({k: v for k, v in res.items() if k != "text"}, text_chars=len(text))
    svg = SVG_RE.search(text)
    if not svg:
        cut = "<svg" in text.lower()
        rec["error"] = (f"SVG 被 max_tokens 截断（正文 {len(text)} 字）" if cut
                        else f"响应里没有 <svg> 元素（正文 {len(text)} 字）")
        # error_code/args 让看板能用别的语言重述同一条错误；error 始终保留中文原文
        rec["error_code"] = "truncated" if cut else "no_svg"
        rec["error_args"] = [len(text)]
        rec["truncated"] = cut
        rec["raw_text"] = text[:4000]
        return rec, None
    svg = svg.group(0)
    rec.update(svg_bytes=len(svg.encode()), path_count=len(SHAPE_RE.findall(svg)))
    # <img> 走严格 XML 解析，属性重复、标签没闭合都会整张渲染不出来 —— 这算模型没画出来
    try:
        ET.fromstring(svg)
    except ET.ParseError as e:
        rec["error"] = f"SVG 不是合法 XML，浏览器渲染不出来：{e}"
        rec["error_code"], rec["error_args"] = "svg_invalid", [str(e)]
        rec["svg_invalid"] = True
        return rec, None
    hits = cheats(svg)
    if hits:
        rec["error"] = "用了绕过作图的手段：" + "、".join(hits)
        rec["error_code"], rec["error_args"] = "cheats", ["、".join(hits)]
        rec["cheats"] = hits
        return rec, None
    rec["ok"] = True
    return rec, svg


def do_run():
    E = load_env()
    ls = lanes(E)
    stamp = datetime.now(CST).strftime("%Y%m%d-%H%M")
    outdir = RUNS / stamp
    outdir.mkdir(parents=True, exist_ok=True)
    records = []
    with cf.ThreadPoolExecutor(len(ls)) as ex:
        for lane, fut in [(l, ex.submit(run_lane, l)) for l in ls]:
            rec, svg = fut.result()
            if svg:
                # 目录可能被 prune 或人工清理顺手删掉，落盘前补一次
                outdir.mkdir(parents=True, exist_ok=True)
                (outdir / f"{lane['key']}.svg").write_text(svg, encoding="utf-8")
            records.append(rec)
    order = {l["key"]: i for i, l in enumerate(ls)}
    records.sort(key=lambda r: order[r["key"]])
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "run.json").write_text(json.dumps(
        {"stamp": stamp, "at": datetime.now(CST).isoformat(timespec="seconds"),
         "prompt": PROMPT, "prompt_version": PROMPT_VERSION, "lanes": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    prune()
    render()
    print(f"{stamp} {sum(1 for r in records if r['ok'])}/{len(records)} 出图 -> {ROOT/'index.html'}")
    for r in records:
        print(f"  {'ok  ' if r['ok'] else 'FAIL'} {r['name']:16} {r['latency_ms']/1000:6.1f}s "
              f"out={r.get('completion_tokens')} 形状={r.get('path_count')} {r.get('error') or ''}")


def prune():
    if not RUNS.is_dir():
        return
    for old in sorted((d for d in RUNS.iterdir() if d.is_dir()), reverse=True)[KEEP:]:
        shutil.rmtree(old, ignore_errors=True)


ANON = False  # --anonymize：出图给外人看时把通道名抹成「中转 A/B」，别点名服务商

# 看板文案。默认中文，--lang en 整页切英文 —— 与其每个格子里塞「入 tok / in」这种
# 双语短语把本来就密的证据区撑爆，不如整页只说一种语言。
LABELS = {
    "zh": {
        "title": "鹈鹕骑自行车 · 模型通道横评",
        "head_lane": "模型 / 通道",
        "ttft": "首字", "out": "出", "shapes": "形状",
        "in": "入", "think": "思考", "think_none": "未报",
        "usage_extra": "usage 非标 {n} 项", "usage_title": "usage 里的非标准字段：{names}",
        "baseline": "基线", "baseline_title": "这条是同模型的入 token 基线",
        "delta_title": "相对同模型基线「{base}」的入 token 差：{d:+d}",
        "id": "响应 id", "id_title": "响应 id 前缀跟同模型基线（{base}）不一致：{a} vs {b}",
        "echo": "回显", "fail": "失败",
        "anon_direct": "官方直连", "anon_proxy": "中转 {x}",
        "think_zero_title": "服务端回传了这个字段，值是 0：思考被关掉了",
        "think_none_title": "该通道不回传思考 token 字段 —— 不等于没思考",
        "sub": ('保留最近 {keep} 轮，由旧到新从左往右；页面每 2 分钟自刷新。'
                '同一句 <code>{prompt}</code>，同样 {max_tokens} max_tokens，全部流式。'
                '时间为北京时间。「首字」是第一个正文字符，思考时长不计在内。'),
        "rule": ('<b>入 token 的差值只在同一个 model 的泳道之间算</b>，'
                 '基线是标了 <code>PB_&lt;名&gt;_BASELINE=true</code> 的那条'
                 '（没标就取 channel 名里带「直连」/ direct 的那条）。'
                 '跨 model 不比：各家分词器不同，比出来的数没有意义。'
                 '<code>思考 —</code> 是该通道<b>不回传</b>这个字段，'
                 '<code>思考 0</code> 是回传了、值就是 0 —— 后者才是思考被关掉。'),
        "err": {"truncated": "SVG 被 max_tokens 截断（正文 {0} 字）",
                "no_svg": "响应里没有 <svg> 元素（正文 {0} 字）",
                "svg_invalid": "SVG 不是合法 XML，浏览器渲染不出来：{0}",
                "cheats": "用了绕过作图的手段：{0}"},
    },
    "en": {
        "title": "Pelican on a bicycle · model × channel board",
        "head_lane": "Model / channel",
        "ttft": "ttft", "out": "out", "shapes": "shapes",
        "in": "in", "think": "think", "think_none": "not reported",
        "usage_extra": "{n} non-standard usage fields",
        "usage_title": "Non-standard fields in usage: {names}",
        "baseline": "baseline", "baseline_title": "input-token baseline for this model",
        "delta_title": "Input-token delta vs the same-model baseline \"{base}\": {d:+d}",
        "id": "response id",
        "id_title": "Response-id prefix differs from the same-model baseline ({base}): {a} vs {b}",
        "echo": "echoed", "fail": "failed",
        "anon_direct": "Direct", "anon_proxy": "Proxy {x}",
        "think_zero_title": "The server reported this field and its value is 0 — reasoning was off",
        "think_none_title": "This channel does not report thinking tokens — that is not proof of zero",
        "sub": ('Last {keep} rounds, oldest to newest, left to right; the page refreshes every '
                '2 minutes. Same <code>{prompt}</code>, same {max_tokens} max_tokens, all '
                'streamed. Times are Asia/Shanghai. "ttft" is the first <i>body</i> character; '
                'thinking time is excluded.'),
        "rule": ('<b>Input-token deltas are computed only between lanes on the same model.</b> '
                 'The baseline is the lane flagged <code>PB_&lt;NAME&gt;_BASELINE=true</code> '
                 '(absent that, the lane whose channel name contains "direct" / 「直连」). '
                 'Never across models: tokenizers differ, so a cross-model delta means nothing. '
                 '<code>think —</code> means the channel <b>does not report</b> the field; '
                 '<code>think 0</code> means it reported zero — only the latter is reasoning off.'),
        "err": {"truncated": "SVG cut off by max_tokens ({0} chars of body)",
                "no_svg": "No <svg> element in the response ({0} chars of body)",
                "svg_invalid": "SVG is not well-formed XML, no browser will render it: {0}",
                "cheats": "Used a shortcut instead of drawing: {0}"},
    },
}

DIRECT_RE = re.compile(r"直连|direct", re.I)
ID_PREFIX_RE = re.compile(r"^[A-Za-z]+[-_]")


def id_prefix(rid):
    """响应 id 的族前缀，如 chatcmpl- / msg_ / resp_。认不出就退回前 8 个字符。"""
    rid = rid or ""
    m = ID_PREFIX_RE.match(rid)
    return m.group(0) if m else rid[:8]


def resolve_baselines(run):
    """给这一轮的每条泳道找同模型基线：显式 PB_<名>_BASELINE 优先，否则取 channel 名里
    带「直连」/ direct 的那条。同 model 只有一条泳道、或找不到基线 → None，不瞎猜。
    差值只在同一个 model 内部算：跨 model 比入 token 没有意义（分词器不同）。"""
    by_model, out = {}, {}
    for rec in run["lanes"]:
        by_model.setdefault(rec.get("model") or rec.get("name") or "", []).append(rec)
    for recs in by_model.values():
        base = None
        if len(recs) > 1:
            base = (next((r for r in recs if r.get("baseline")), None)
                    or next((r for r in recs if DIRECT_RE.search(r.get("channel") or "")), None))
        for r in recs:
            out[r["key"]] = base
    return out


def anon_channels(runs):
    """把各条通道的显示名映射成匿名标签；直连保留，其余按首次出现编号。"""
    L = LABELS[LANG]
    mapping, nth = {}, 0
    for run in runs:
        for rec in run["lanes"]:
            ch = rec.get("channel") or ""
            if ch in mapping:
                continue
            if DIRECT_RE.search(ch):
                mapping[ch] = L["anon_direct"]
            else:
                mapping[ch] = L["anon_proxy"].format(x=chr(ord("A") + nth))
                nth += 1
    return mapping


def load_runs():
    out = []
    if not RUNS.is_dir():
        return out
    for d in sorted((d for d in RUNS.iterdir() if d.is_dir()), reverse=True)[:KEEP]:
        if (d / "run.json").is_file():
            out.append(json.loads((d / "run.json").read_text(encoding="utf-8")))
    return out


def svg_src(run, rec):
    """SVG 内联进 index.html —— 外链相对路径的话，单独把 html 发出去图全裂，
    「self-contained」就是句空话。走 data URI 而不是把 <svg> 直接写进 DOM：
    十几张图里的 gradient/clipPath id 会互相撞车，data URI 各自独立作用域。"""
    p = RUNS / run["stamp"] / f'{rec["key"]}.svg'
    try:
        b64 = base64.b64encode(p.read_bytes()).decode()
    except OSError:
        return f'runs/{run["stamp"]}/{rec["key"]}.svg'   # 快照被清了就退回外链
    return "data:image/svg+xml;base64," + b64


def localized_error(rec):
    L = LABELS[LANG]
    code = rec.get("error_code")
    if code and code in L["err"]:
        try:
            return L["err"][code].format(*(rec.get("error_args") or []))
        except (IndexError, KeyError):
            pass
    return rec.get("error") or L["fail"]


def cell(run, rec, base):
    """一格 = 一条泳道在这一轮的全部证据。图是钩子，图下面这几行才是实锤。"""
    L = LABELS[LANG]
    if not rec:
        return '<td class="miss">—</td>'
    secs = f'{rec.get("latency_ms", 0)/1000:.0f}s'
    if not rec["ok"]:
        return (f'<td class="bad"><div class="err">{html.escape(localized_error(rec))}</div>'
                f'<div class="meta">{secs}</div></td>')
    ttft = rec.get("ttft_ms")
    ttft_s = " · {} {:.0f}s".format(L["ttft"], ttft / 1000) if ttft else ""
    meta = "{}{} · {} {} tok · {} {}".format(
        secs, ttft_s, L["out"], rec.get("completion_tokens") or "?",
        rec.get("path_count", 0), L["shapes"])

    ev = []   # 证据行
    is_base = base is not None and base.get("key") == rec.get("key")
    pt = rec.get("prompt_tokens")
    if pt is not None:
        delta = ""
        bpt = (base or {}).get("prompt_tokens")
        if base is not None and not is_base and isinstance(bpt, int):
            d = pt - bpt
            if d > 0:
                t = html.escape(L["delta_title"].format(base=base.get("channel") or base["key"], d=d))
                delta = f' <span class="delta" title="{t}">(+{d})</span>'
            elif d < 0:
                t = html.escape(L["delta_title"].format(base=base.get("channel") or base["key"], d=d))
                delta = f' <span class="delta neg" title="{t}">({d})</span>'
        tag = (f' <span class="base" title="{html.escape(L["baseline_title"])}">'
               f'{L["baseline"]}</span>' if is_base else "")
        ev.append(f'<div class="ev">{L["in"]} {pt}{delta}{tag}</div>')

    rt = rec.get("reasoning_tokens")
    if rt is None:
        # null = 该通道压根不回传这个字段，跟「回传了、值是 0」是两回事，显示上必须分开
        ev.append(f'<div class="ev dim" title="{html.escape(L["think_none_title"])}">'
                  f'{L["think"]} — <span class="nb">{L["think_none"]}</span></div>')
    elif rt == 0:
        ev.append(f'<div class="ev think0" title="{html.escape(L["think_zero_title"])}">'
                  f'{L["think"]} 0</div>')
    else:
        ev.append(f'<div class="ev">{L["think"]} {rt}</div>')

    extra = rec.get("usage_extra") or []
    if extra:
        t = html.escape(L["usage_title"].format(names="、".join(extra)))
        ev.append(f'<div class="ev flag" title="{t}">'
                  f'{html.escape(L["usage_extra"].format(n=len(extra)))}</div>')

    rid = rec.get("response_id") or ""
    if base is not None and not is_base and rid:
        bp, rp = id_prefix(base.get("response_id") or ""), id_prefix(rid)
        if bp and rp != bp:   # 一致就是噪音，只在不一致时才占一行
            t = html.escape(L["id_title"].format(
                base=base.get("channel") or base["key"], a=rp, b=bp))
            ev.append(f'<div class="ev flag" title="{t}">'
                      f'{L["id"]} {html.escape(rp)}</div>')

    echoed = rec.get("model_echoed")
    if echoed and echoed != rec["model"]:
        ev.append(f'<div class="ev drift">{L["echo"]} {html.escape(echoed)}</div>')

    return (f'<td><img src="{svg_src(run, rec)}" alt="{html.escape(rec["name"])}">'
            f'<div class="meta">{meta}</div>{"".join(ev)}</td>')


def render():
    """有快照才出得了看板。返回 False 表示一张快照都没有，交给调用方报错。"""
    runs = load_runs()
    if not runs:
        return False
    runs.reverse()  # load_runs 给的是新到旧；看板按时间从左往右排
    # 基线在匿名化之前定：匿名化会重写 channel 名，别让回退规则踩到自己改出来的名字
    bases = [resolve_baselines(r) for r in runs]
    if ANON:
        mapping = anon_channels(runs)
        for run in runs:
            for rec in run["lanes"]:
                rec["channel"] = mapping.get(rec.get("channel") or "",
                                             LABELS[LANG]["anon_proxy"].format(x="?"))
    by_run = [{rec["key"]: rec for rec in r["lanes"]} for r in runs]
    keys = []
    for m in by_run:
        for k in m:
            if k not in keys:
                keys.append(k)
    rows = []
    for k in keys:
        # 行标题取**最新**那轮的记录：换了模型之后，行首还标着旧模型名、右边格子却是
        # 新模型画的，等于看板自己在撒谎。by_run 是旧→新，所以从后往前找。
        rec0 = next((m[k] for m in reversed(by_run) if k in m), None)
        cells = "".join(cell(runs[i], by_run[i].get(k), bases[i].get(k))
                        for i in range(len(runs)))
        rows.append(f'<tr><th class="lane"><div>{html.escape(rec0["name"])}</div>'
                    f'<div class="chan">{html.escape(rec0["channel"])}</div></th>{cells}</tr>')
    heads = "".join(f'<th>{html.escape(r["at"][5:16].replace("T", " "))}</th>' for r in runs)
    L = LABELS[LANG]
    sub = L["sub"].format(keep=KEEP, prompt=html.escape(PROMPT.split(".")[0]),
                          max_tokens=MAX_TOKENS)
    (ROOT / "index.html").write_text(f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(L["title"])}</title><meta http-equiv="refresh" content="120">
<style>
body{{margin:0;padding:20px;background:#f5f6f8;font:13px/1.5 -apple-system,system-ui,sans-serif;color:#1d2733}}
h1{{font-size:17px;margin:0 0 4px}}
p.sub,p.rule{{margin:0 0 10px;color:#6b7785;max-width:760px}}
p.rule{{margin-bottom:16px;background:#fff;border-left:3px solid #17374f;padding:8px 10px;border-radius:0 4px 4px 0}}
.scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
table{{border-collapse:collapse;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.08);border-radius:6px;overflow:hidden}}
th,td{{border:1px solid #e3e7ec;padding:8px;vertical-align:top;text-align:center}}
thead th{{background:#17374f;color:#fff;font-weight:600;font-size:12px}}
th.lane{{background:#fafbfc;text-align:left;min-width:120px;font-weight:600}}
th.lane .chan{{font-weight:400;color:#6b7785;font-size:11px}}
img{{width:240px;height:240px;max-width:100%;object-fit:contain;background:#fff;display:block}}
.meta{{color:#6b7785;font-size:11px;margin-top:5px}}
.ev{{font-size:11px;text-align:left;margin-top:2px;font-variant-numeric:tabular-nums}}
.ev.dim{{color:#98a3ae}}
.ev .nb{{font-size:10px}}
.delta{{color:#c0392b;font-weight:700;background:#fdecea;border-radius:3px;padding:0 3px}}
.delta.neg{{color:#1f7a5a;background:#e8f6f0}}
.base{{color:#41586b;background:#eef2f6;border-radius:3px;padding:0 4px;font-size:10px}}
.think0{{color:#c0392b;font-weight:700;background:#fdecea;border-radius:3px;padding:0 3px;display:inline-block}}
.flag{{color:#8a5a13}}
.drift{{color:#b4761f;font-size:11px}}
td.bad{{background:#fdf3f2}}
td.bad .err{{color:#b4453c;font-size:11px;max-width:240px;word-break:break-word;text-align:left}}
td.miss{{color:#b7c0c9}}
code{{background:#eef2f6;padding:1px 5px;border-radius:3px}}
</style>
<h1>{html.escape(L["title"])}</h1>
<p class="sub">{sub}</p>
<p class="rule">{L["rule"]}</p>
<div class="scroll">
<table><thead><tr><th>{html.escape(L["head_lane"])}</th>{heads}</tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</div>
""", encoding="utf-8")
    return True


if __name__ == "__main__":
    ARGS = apply_cli(sys.argv[1:])
    OPEN_AFTER = "--open" in ARGS
    ANON = "--anonymize" in ARGS

    def show():
        board = ROOT / "index.html"
        print(board)
        if OPEN_AFTER:
            import shutil
            import subprocess
            for cmd in ("open", "xdg-open"):
                if shutil.which(cmd):
                    subprocess.run([cmd, str(board)], check=False)
                    break

    if "render" in ARGS:
        if not render():
            # 以前这里打印一个并不存在的 index.html 路径、还 exit 0，等于骗人
            sys.exit(f"{RUNS} 下还没有快照，render 无图可用。\n"
                     f"No snapshot under {RUNS} — nothing to render.\n"
                     f"先不带 render 跑一轮（会调 API）/ run one round first (costs API calls):\n"
                     f"  {Path(sys.argv[0]).name}")
        show()
        sys.exit()
    if not ENV_FILE.is_file():
        sys.exit(f"没有泳道配置 {ENV_FILE}\n"
                 f"No lanes config at {ENV_FILE}\n"
                 f"照着 lanes.env.example 建一份，权限设 600（里面是密钥）。\n"
                 f"Copy lanes.env.example there and chmod 600 it (it holds API keys).\n"
                 f"只想用已有快照重出看板的话加 render / add `render` to rebuild from snapshots.")
    # 目录副作用留在校验之后：一条跑不起来的命令不该在磁盘上留下空目录
    RUNS.mkdir(parents=True, exist_ok=True)
    # 上一轮没跑完就别叠上来
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if time.time() - LOCK.stat().st_mtime < 3600:
            sys.exit("上一轮还在跑，跳过")
        LOCK.unlink()
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        do_run()
        show()
    finally:
        LOCK.unlink(missing_ok=True)
