#!/usr/bin/env python3
"""鹈鹕骑自行车：让若干条「模型 x 通道」画同一张 SVG，并量出各通道的元数据指纹。

同题、同 prompt、同 max_tokens，横着看差距。每条泳道每轮只打这一发，
判读全部来自它的响应：服务端自己报回来的 input token 数、思考 token、响应 id
和 usage 字段 —— 中转层若塞了隐藏上下文或关掉了思考，最先从这几个数字漏出来。

全程流式：reasoning 模型思考几分钟不吐字是常态，非流式会直接读超时。
思考段一律丢掉，只留正文里的 <svg>。凭证只从配置文件读，任何输出里都不写 key。

用法:
    pelican_proxy_check.py                 跑一轮并刷新看板
    pelican_proxy_check.py render          只用已有快照重出看板
    pelican_proxy_check.py --open          跑完顺手打开看板
    pelican_proxy_check.py --config PATH   指定泳道配置（默认 ~/.config/pelican-proxy-check/lanes.env）
    pelican_proxy_check.py --out DIR       指定快照与看板目录（默认 ~/.local/share/pelican-proxy-check）
    pelican_proxy_check.py --keep N        保留最近 N 轮（默认 3）
    pelican_proxy_check.py --anonymize     看板里把通道名抹成「中转 A/B」，便于截图外发
"""
import concurrent.futures as cf
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

ENV_FILE = Path.home() / ".config/pelican-proxy-check/lanes.env"
ROOT = Path.home() / ".local/share/pelican-proxy-check"
RUNS = ROOT / "runs"
LOCK = ROOT / "run.lock"
KEEP = 3


def apply_cli(argv):
    """路径和保留轮数都可以从命令行改，好让同一份脚本服务多套配置。"""
    global ENV_FILE, ROOT, RUNS, LOCK, KEEP
    args, rest = [], list(argv)
    while rest:
        a = rest.pop(0)
        if a == "--config":
            ENV_FILE = Path(rest.pop(0)).expanduser()
        elif a == "--out":
            ROOT = Path(rest.pop(0)).expanduser()
        elif a == "--keep":
            KEEP = max(1, int(rest.pop(0)))
        else:
            args.append(a)
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
    out = []
    for slot in lane_order(E):
        def g(k, d=None, _s=slot):
            return E.get(f"PB_{_s}_{k}", d)
        base, api_key, model = g("BASE_URL"), g("API_KEY"), g("MODEL")
        if not (base and api_key and model):
            continue
        proto = g("PROTO", "openai")
        extra = json.loads(g("EXTRA", "{}"))
        lane = dict(key=slot.lower(), name=model, channel=g("CHANNEL", ""),
                    model=model, proto=proto, proxy=g("EGRESS_PROXY") or g("PROXY"),
                    effort=g("EFFORT", ""), extra=extra)
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
           "ok": False, "error": None}
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
        rec["svg_invalid"] = True
        return rec, None
    hits = cheats(svg)
    if hits:
        rec["error"] = "用了绕过作图的手段：" + "、".join(hits)
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
    for old in sorted((d for d in RUNS.iterdir() if d.is_dir()), reverse=True)[KEEP:]:
        shutil.rmtree(old, ignore_errors=True)


ANON = False  # --anonymize：出图给外人看时把通道名抹成「中转 A/B」，别点名服务商


def anon_channels(runs):
    """把各条通道的显示名映射成匿名标签；直连保留，其余按首次出现编号。"""
    mapping, nth = {}, 0
    for run in runs:
        for rec in run["lanes"]:
            ch = rec.get("channel") or ""
            if ch in mapping:
                continue
            if "直连" in ch or "direct" in ch.lower():
                mapping[ch] = "官方直连"
            else:
                mapping[ch] = f"中转 {chr(ord('A') + nth)}"
                nth += 1
    return mapping


def load_runs():
    out = []
    for d in sorted((d for d in RUNS.iterdir() if d.is_dir()), reverse=True)[:KEEP]:
        if (d / "run.json").is_file():
            out.append(json.loads((d / "run.json").read_text(encoding="utf-8")))
    return out


def cell(run, rec):
    if not rec:
        return '<td class="miss">—</td>'
    secs = f'{rec.get("latency_ms", 0)/1000:.0f}s'
    if not rec["ok"]:
        return (f'<td class="bad"><div class="err">{html.escape(rec["error"] or "失败")}</div>'
                f'<div class="meta">{secs}</div></td>')
    ttft = rec.get("ttft_ms")
    meta = (f'{secs}{f" · 首字 {ttft/1000:.0f}s" if ttft else ""} · '
            f'{rec.get("completion_tokens") or "?"} tok · {rec.get("path_count", 0)} 形状')
    echoed = rec.get("model_echoed")
    drift = ("" if not echoed or echoed == rec["model"]
             else f'<div class="drift">回显 {html.escape(echoed)}</div>')
    return (f'<td><img src="runs/{run["stamp"]}/{rec["key"]}.svg" '
            f'alt="{html.escape(rec["name"])}"><div class="meta">{meta}</div>{drift}</td>')


def render():
    runs = load_runs()
    if not runs:
        return
    runs.reverse()  # load_runs 给的是新到旧；看板按时间从左往右排
    if ANON:
        mapping = anon_channels(runs)
        for run in runs:
            for rec in run["lanes"]:
                rec["channel"] = mapping.get(rec.get("channel") or "", "中转")
    by_run = [{rec["key"]: rec for rec in r["lanes"]} for r in runs]
    keys = []
    for m in by_run:
        for k in m:
            if k not in keys:
                keys.append(k)
    rows = []
    for k in keys:
        rec0 = next((m[k] for m in by_run if k in m), None)
        cells = "".join(cell(runs[i], by_run[i].get(k)) for i in range(len(runs)))
        rows.append(f'<tr><th class="lane"><div>{html.escape(rec0["name"])}</div>'
                    f'<div class="chan">{html.escape(rec0["channel"])}</div></th>{cells}</tr>')
    heads = "".join(f'<th>{html.escape(r["at"][5:16].replace("T", " "))}</th>' for r in runs)
    (ROOT / "index.html").write_text(f"""<!doctype html><meta charset="utf-8">
<title>鹈鹕骑自行车</title><meta http-equiv="refresh" content="120">
<style>
body{{margin:0;padding:20px;background:#f5f6f8;font:13px/1.5 -apple-system,system-ui,sans-serif;color:#1d2733}}
h1{{font-size:17px;margin:0 0 4px}}
p.sub{{margin:0 0 16px;color:#6b7785;max-width:760px}}
table{{border-collapse:collapse;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.08);border-radius:6px;overflow:hidden}}
th,td{{border:1px solid #e3e7ec;padding:8px;vertical-align:top;text-align:center}}
thead th{{background:#17374f;color:#fff;font-weight:600;font-size:12px}}
th.lane{{background:#fafbfc;text-align:left;min-width:130px;font-weight:600}}
th.lane .chan{{font-weight:400;color:#6b7785;font-size:11px}}
img{{width:240px;height:240px;object-fit:contain;background:#fff;display:block}}
.meta{{color:#6b7785;font-size:11px;margin-top:5px}}
.drift{{color:#b4761f;font-size:11px}}
td.bad{{background:#fdf3f2}}
td.bad .err{{color:#b4453c;font-size:11px;max-width:240px;word-break:break-all;text-align:left}}
td.miss{{color:#b7c0c9}}
code{{background:#eef2f6;padding:1px 5px;border-radius:3px}}
</style>
<h1>鹈鹕骑自行车 · 模型通道横评</h1>
<p class="sub">保留最近 {KEEP} 轮，由旧到新从左往右；页面每 2 分钟自刷新。
同一句 <code>{html.escape(PROMPT.split(".")[0])}</code>，同样 {MAX_TOKENS} max_tokens，
全部流式。时间为北京时间。「首字」是第一个正文字符，思考时长不计在内。</p>
<table><thead><tr><th>模型 / 通道</th>{heads}</tr></thead><tbody>{''.join(rows)}</tbody></table>
""", encoding="utf-8")


if __name__ == "__main__":
    ARGS = apply_cli(sys.argv[1:])
    OPEN_AFTER = "--open" in ARGS
    ANON = "--anonymize" in ARGS
    RUNS.mkdir(parents=True, exist_ok=True)

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
        render()
        show()
        sys.exit()
    if not ENV_FILE.is_file():
        sys.exit(f"没有泳道配置 {ENV_FILE}\n"
                 f"照着 lanes.env.example 建一份，权限设 600（里面是密钥）。\n"
                 f"只想用已有快照重出看板的话加 render。")
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
