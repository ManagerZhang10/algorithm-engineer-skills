#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lecture-cut —— ScreenKite 录屏（屏幕 / 摄像头 / 麦克风三轨）讲解视频的 ffmpeg 剪辑流水线。
只依赖 Python ≥ 3.9 标准库 + ffmpeg（需带 libass；macOS 上优先用 h264_videotoolbox 硬编码）。

流程：
  1. analyze：从 skbundle 取三条原始轨（屏幕 / 摄像头 / 麦克风）+ whisper 词级转写，
     在麦克风轨上做静音检测，加上用文字锚点定位的手工删除清单，产出
       <workdir>/edl.json   保留区间 + 删除区间（原始时间域）
       <workdir>/review.md  按句列出全文、保留/删除标记，给人过目
  2. render：按 edl.json 裁三轨、拼接、叠圆形摄像头、烧逐字高亮 ASS 字幕，
     输出 1920x1080 30fps H.264 + AAC。

用法：
  lecture-cut analyze --bundle <x.skbundle> --words <whisper.json> --out <workdir> [--cuts cuts.json]
  lecture-cut render  --workdir <workdir> --out <mp4> [--preview 30] [--jobs 4]
详细参数看 `lecture-cut <子命令> --help`。
"""

import argparse
import array
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor

# ffmpeg 查找顺序：环境变量 LECTURE_CUT_FFMPEG → PATH 里的 ffmpeg → ~/.local/bin/ffmpeg
FFMPEG = (os.environ.get("LECTURE_CUT_FFMPEG") or shutil.which("ffmpeg")
          or os.path.expanduser("~/.local/bin/ffmpeg"))

# 输出规格
# 输出规格（默认值为 1080p 基准；render 按 --profile / --size / --fps 在运行时改写，
# 所有 UI 元素按 UI_K = 输出宽 / 1920 等比缩放，保证高分辨率下字幕、摄像头、光标不变小）
OUT_W, OUT_H, OUT_FPS = 1920, 1080, 30
UI_K = 1.0
CAM_RATIO, CAM_MARGIN, CAM_BORDER = 0.10, 24, 3
PROFILES = {
    "draft": {"size": (1280, 720), "fps": 30, "bitrate": "3M", "desc": "草片：720p30、低码率，追求快"},
    "final": {"size": None, "fps": None, "bitrate": None, "desc": "正式片：分辨率与帧率跟屏幕源一致，不缩放不加黑边，码率按像素数换算"},
}

# whisper 转写里残留的误识别术语，读入时顺手修掉（跨词短语也能替换）。
# 默认为空；用 analyze --term-fixes <json> 传入 {"错写": "正写"} 字典，示例见 references/。
TERM_FIXES = {}

# 句末 / 句中标点（用于分句和字幕分行）
SENT_END = "。！？!?"
CLAUSE = "，,、；;：:"
ALL_PUNCT = SENT_END + CLAUSE + "…"


# ---------------------------------------------------------------- 通用工具

def die(msg, code=2):
    sys.stderr.write("错误：%s\n" % msg)
    sys.exit(code)


def log(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def run(cmd, **kw):
    """跑一个外部命令，失败直接退出并把 stderr 打出来。"""
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw)
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-4000:])
        die("命令失败：%s" % " ".join(cmd[:6]) + " ...")
    return p


def mmss(t):
    t = max(0.0, t)
    m = int(t // 60)
    s = t - m * 60
    return "%02d:%05.2f" % (m, s)


def mmss_short(t):
    t = max(0.0, t)
    return "%02d:%02d" % (int(t // 60), int(t % 60))


def ass_time(t):
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return "%d:%02d:%05.2f" % (h, m, s)


def norm_text(s):
    """锚点匹配用：去掉标点、空白、下划线，转小写。"""
    return re.sub(r"[\s\W_]+", "", s).lower()


def ffprobe_duration(path):
    """没有 ffprobe，用 `ffmpeg -i` 的 Duration 行代替。"""
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", path], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", p.stderr)
    if not m:
        die("读不到时长：%s" % path)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def ffprobe_video_size(path):
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", path], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", p.stderr)
    return (int(m.group(1)), int(m.group(2))) if m else None


def ffprobe_fps(path):
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", path], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
    m = re.search(r"Video:.*?([\d.]+) fps", p.stderr)
    return float(m.group(1)) if m else None


def find_media(bundle):
    """在 skbundle/media 里定位三条轨。"""
    media = os.path.join(bundle, "media")
    if not os.path.isdir(media):
        die("找不到 media 目录：%s" % media)

    def pick(patterns, sub=""):
        d = os.path.join(media, sub) if sub else media
        if not os.path.isdir(d):
            return None
        for f in sorted(os.listdir(d)):
            for pat in patterns:
                if re.match(pat, f):
                    return os.path.join(d, f)
        return None

    screen = pick([r"screen_display_\d+\.(mp4|mov)$"], "raw") or pick([r"screen.*\.(mp4|mov)$"])
    camera = pick([r"camera.*\.(mov|mp4)$"])
    mic = pick([r"microphone.*\.(m4a|wav|aac)$"])
    if not (screen and camera and mic):
        die("三条轨没找齐：screen=%s camera=%s mic=%s" % (screen, camera, mic))
    return {"screen": screen, "camera": camera, "mic": mic}


# ---------------------------------------------------------------- 词与术语

def load_words(path):
    d = json.load(open(path, encoding="utf-8"))
    words = d["sourceWords"] if isinstance(d, dict) and "sourceWords" in d else d.get("words", d)
    out = []
    for w in words:
        t = w.get("text") or w.get("word") or ""
        if t == "":
            continue
        out.append({"start": float(w["start"]), "end": float(w["end"]), "text": t})
    out.sort(key=lambda w: w["start"])
    return out


def apply_term_fixes(words, fixes):
    """跨词替换：把连续若干词拼起来能匹配到的错误术语改成正确写法。
    改法：正确文本放进第一个词，其余词文本清空（时间保留，随后被丢弃）。"""
    if not fixes:
        return words, 0
    n_fixed = 0
    for bad, good in fixes.items():
        i = 0
        while i < len(words):
            acc = ""
            j = i
            hit = False
            while j < len(words) and len(acc) < len(bad) + 6:
                acc += words[j]["text"]
                if bad in acc:
                    hit = True
                    break
                j += 1
            if hit and words[i]["text"] and acc.find(bad) < len(words[i]["text"]):
                merged = acc.replace(bad, good, 1)
                words[i]["text"] = merged
                words[i]["end"] = words[j]["end"]
                for k in range(i + 1, j + 1):
                    words[k]["text"] = ""
                n_fixed += 1
                i = j + 1
            else:
                i += 1
    words = [w for w in words if w["text"]]
    return words, n_fixed


class Anchors:
    """把词表拼成一条归一化的长串，支持「短语 → 词下标」的定位。"""

    def __init__(self, words):
        self.words = words
        self.chars = []       # 每个归一化字符对应的词下标
        parts = []
        for i, w in enumerate(words):
            n = norm_text(w["text"])
            parts.append(n)
            self.chars.extend([i] * len(n))
        self.text = "".join(parts)

    def find(self, phrase, occurrence="first", context=40):
        n = norm_text(phrase)
        if not n:
            die("锚点为空：%r" % phrase)
        hits = [m.start() for m in re.finditer(re.escape(n), self.text)]
        if not hits:
            # 找不到就报错并列出最相近的一段文本，方便改锚点
            near = self._nearest(n, context)
            die("锚点找不到：%r\n  最接近的文本：%s" % (phrase, near))
        if occurrence == "first":
            k = 0
        elif occurrence == "last":
            k = len(hits) - 1
        elif isinstance(occurrence, int):
            k = occurrence - 1
            if not (0 <= k < len(hits)):
                die("锚点 %r 只有 %d 处，取不到第 %d 处" % (phrase, len(hits), occurrence))
        else:
            die("occurrence 只能是 first / last / 正整数：%r" % occurrence)
        if len(hits) > 1 and occurrence == "first":
            log("提示：锚点 %r 出现 %d 次，按 first 取第一次（%s）；如需其它请写 occurrence" %
                (phrase, len(hits), mmss(self.words[self.chars[hits[0]]]["start"])))
        pos = hits[k]
        first_word = self.chars[pos]
        last_word = self.chars[pos + len(n) - 1]
        return first_word, last_word, len(hits)

    def _nearest(self, n, context):
        # 用最长公共前缀的位置做粗略提示（够用，不引入第三方包）
        best_len, best_pos = 0, 0
        for L in range(min(len(n), 12), 1, -1):
            pos = self.text.find(n[:L])
            if pos >= 0:
                best_len, best_pos = L, pos
                break
        i = self.words[self.chars[best_pos]]["start"] if self.chars else 0
        return "…%s…（约 %s，与锚点前 %d 个字相同）" % (
            self.text[max(0, best_pos - context):best_pos + context], mmss(i), best_len)


# ---------------------------------------------------------------- 静音检测

def detect_silence(mic, noise_db, min_dur, pad):
    cmd = [FFMPEG, "-hide_banner", "-nostats", "-i", mic, "-af",
           "silencedetect=noise=%sdB:d=%s" % (noise_db, min_dur), "-f", "null", "-"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", p.stderr)]
    segs = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        if e is None:
            continue
        a, b = s + pad, e - pad
        if b - a >= 0.10:
            segs.append((a, b))
    return segs


def snap_silence_to_words(silence, words, pad, min_dur):
    """静音删除区间不得与任何 whisper 词重叠：把每段静音减去所有词的 [start-pad, end+pad]，
    剩下的碎片短于 min_dur 的丢弃。whisper 常把停顿算进相邻词的跨度，这样做会少删一些静音，
    但保证不会切到词、字幕也不会跨接缝丢字。返回 (新区间列表, 被吸附/丢弃统计)。"""
    spans = sorted((w["start"] - pad, w["end"] + pad) for w in words)
    out, n_shrunk, n_dropped = [], 0, 0
    j = 0
    for a, b in silence:
        pieces = [(a, b)]
        # 只看可能重叠的词
        while j > 0 and spans[j - 1][1] > a:
            j -= 1
        k = j
        changed = False
        while k < len(spans) and spans[k][0] < b:
            ws, we = spans[k]
            if we > a:
                new = []
                for pa, pb in pieces:
                    if we <= pa or ws >= pb:
                        new.append((pa, pb))
                    else:
                        changed = True
                        if ws > pa:
                            new.append((pa, ws))
                        if we < pb:
                            new.append((we, pb))
                pieces = new
            k += 1
        kept = [(pa, pb) for pa, pb in pieces if pb - pa >= min_dur]
        if changed:
            if kept:
                n_shrunk += 1
            else:
                n_dropped += 1
        out.extend(kept)
    return out, {"shrunk": n_shrunk, "dropped": n_dropped}


# ---------------------------------------------------------------- 区间运算

def merge_intervals(ivs):
    ivs = sorted((a, b) for a, b in ivs if b > a)
    out = []
    for a, b in ivs:
        if out and a <= out[-1][1] + 1e-6:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def invert(deleted, total):
    keep, cur = [], 0.0
    for a, b in deleted:
        if a > cur + 1e-6:
            keep.append((cur, a))
        cur = max(cur, b)
    if total > cur + 1e-6:
        keep.append((cur, total))
    return keep


# ---------------------------------------------------------------- 分句（review 用）

def split_sentences(words, gap=0.8):
    sents, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end_punct = w["text"].rstrip()[-1:] in SENT_END
        big_gap = nxt is not None and nxt["start"] - w["end"] > gap
        if end_punct or big_gap or nxt is None:
            sents.append(cur)
            cur = []
    return sents


# ---------------------------------------------------------------- analyze

def cmd_analyze(a):
    bundle = a.bundle.rstrip("/")
    media = find_media(bundle)
    os.makedirs(a.out, exist_ok=True)

    durs = {k: ffprobe_duration(v) for k, v in media.items()}
    total = min(durs.values())
    spread = max(durs.values()) - total
    if spread > 0.5:
        log("警告：三轨时长不一致（%s），按最短 %.2fs 对齐到开头" %
            (", ".join("%s=%.2f" % kv for kv in durs.items()), total))

    words = load_words(a.words)
    fixes = dict(TERM_FIXES)
    if a.term_fixes:
        fixes.update(json.load(open(a.term_fixes, encoding="utf-8")))
    words, n_fixed = apply_term_fixes(words, fixes)
    if n_fixed:
        log("术语修正 %d 处（%s）" % (n_fixed, "、".join("%s→%s" % kv for kv in fixes.items())))
    shutil.copy(a.words, os.path.join(a.out, "words.src.json"))

    # 1) 静音
    silence_raw = detect_silence(media["mic"], a.silence_db, a.silence_min, a.silence_pad)
    raw_total = sum(b - s for s, b in silence_raw)
    silence, snap = snap_silence_to_words(silence_raw, words, a.silence_pad, a.silence_min)
    log("静音段 %d 个，合计 %.1fs；吸附词边界后 %d 个，合计 %.1fs（收缩 %d、丢弃 %d）" % (
        len(silence_raw), raw_total, len(silence), sum(b - s for s, b in silence), snap["shrunk"], snap["dropped"]))

    # 2) 手工删除（文字锚点）
    anchors = Anchors(words)
    manual = []
    if a.cuts:
        cuts = json.load(open(a.cuts, encoding="utf-8"))
        for c in cuts:
            if c.get("skip_if_missing") and not re.search(re.escape(norm_text(c["from"])), anchors.text):
                log("跳过（锚点不存在，已声明可跳过）：%r" % c["from"])
                continue
            f0, f1, _ = anchors.find(c["from"], c.get("from_occurrence", "first"))
            if "to_before" in c:
                t0, t1, _ = anchors.find(c["to_before"], c.get("to_occurrence", "first"))
                if t0 <= f0:
                    die("删除区间终点在起点之前：%r → %r" % (c["from"], c["to_before"]))
                last = t0 - 1
            elif "to" in c:
                t0, t1, _ = anchors.find(c["to"], c.get("to_occurrence", "first"))
                if t1 < f0:
                    die("删除区间终点在起点之前：%r → %r" % (c["from"], c["to"]))
                last = t1
            else:
                last = f1  # 只给 from：删这个短语本身
            s = words[f0]["start"]
            e = words[last]["end"] if last + 1 >= len(words) else min(words[last]["end"] + 0.05, words[last + 1]["start"])
            text = "".join(w["text"] for w in words[f0:last + 1])
            manual.append({"start": round(s, 3), "end": round(e, 3), "type": "manual",
                           "reason": c.get("reason", ""), "text": text,
                           "word_from": f0, "word_to": last})
            log("手工删除 %s–%s（%d 词）：%s… 原因：%s" %
                (mmss(s), mmss(e), last - f0 + 1, text[:30], c.get("reason", "")))

    # 3) 合并成保留区间
    deleted_all = merge_intervals([(m["start"], m["end"]) for m in manual] + silence)
    keep = invert(deleted_all, total)
    keep = [(s, e) for s, e in keep if e - s >= 0.05]
    kept_total = sum(e - s for s, e in keep)

    # 词的去留：落在手工删除区间里的词删除；静音区间不含词，不影响
    manual_ivs = merge_intervals([(m["start"], m["end"]) for m in manual])
    reasons = {}
    for m in manual:
        for i in range(m["word_from"], m["word_to"] + 1):
            reasons[i] = m["reason"]
    word_status = []
    for i, w in enumerate(words):
        mid = (w["start"] + w["end"]) / 2
        deleted = any(s <= mid < e for s, e in manual_ivs) or i in reasons
        word_status.append(reasons.get(i, "") if deleted else None)

    cuts_out = manual + [{"start": round(s, 3), "end": round(e, 3), "type": "silence",
                          "reason": "静音", "text": ""} for s, e in silence]
    cuts_out.sort(key=lambda c: c["start"])
    edl = {
        "version": 1,
        "bundle": bundle,
        "media": media,
        "durations": durs,
        "source_duration": total,
        "params": {"silence_db": a.silence_db, "silence_min": a.silence_min, "silence_pad": a.silence_pad},
        "keep": [{"start": round(s, 4), "end": round(e, 4)} for s, e in keep],
        "cuts": cuts_out,
        "words": [{"start": w["start"], "end": w["end"], "text": w["text"],
                   "deleted": (word_status[i] is not None),
                   "reason": word_status[i] or ""} for i, w in enumerate(words)],
    }
    json.dump(edl, open(os.path.join(a.out, "edl.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # 4) review.md
    sil_total = sum(b - s for s, b in silence)
    lines = ["# 剪辑清单（review）", "",
             "- 素材：`%s`" % bundle,
             "- 原始时长 %s，保留 %s，删除 %s（其中静音 %d 段共 %.1fs，手工 %d 段共 %.1fs）" % (
                 mmss(total), mmss(kept_total), mmss(total - kept_total), len(silence), sil_total,
                 len(manual), sum(m["end"] - m["start"] for m in manual)),
             "- 静音检测：阈值 %sdB、最短 %.2fs、两端各留 %.2fs；静音段不逐条列。" % (
                 a.silence_db, a.silence_min, a.silence_pad),
             "- 静音删除区间已吸附到词边界：与任何 whisper 词（含 %.2fs 余量）重叠的部分不删，"
             "剩余短于最短静音的整段放弃（本次原始检出 %d 段 %.1fs → 实际删 %d 段 %.1fs）。" % (
                 a.silence_pad, len(silence_raw), raw_total, len(silence), sil_total),
             "", "## 手工删除", ""]
    if manual:
        for m in manual:
            lines.append("- %s–%s（%.1fs）%s：%s" % (mmss(m["start"]), mmss(m["end"]),
                                                  m["end"] - m["start"], m["reason"], m["text"]))
    else:
        lines.append("（无）")
    lines += ["", "## 全文（按句，原始时间码）", "",
              "标记：`保留` / `删除（原因）` / `部分删除（原因）`。", ""]
    for sent in split_sentences(words):
        t0 = words[sent[0]]["start"]
        txt = "".join(words[i]["text"] for i in sent)
        st = [word_status[i] for i in sent]
        n_del = sum(1 for s in st if s is not None)
        if n_del == 0:
            mark = "保留"
        elif n_del == len(sent):
            mark = "删除（%s）" % (next(s for s in st if s) or "手工")
        else:
            rs = next(s for s in st if s) or "手工"
            kept_txt = "".join(words[i]["text"] for i in sent if word_status[i] is None)
            mark = "部分删除（%s）→ 留：%s" % (rs, kept_txt)
        lines.append("- `%s` %s — %s" % (mmss_short(t0), mark, txt))
    open(os.path.join(a.out, "review.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    log("写出 %s/edl.json 与 review.md；保留 %s / 原始 %s" % (a.out, mmss(kept_total), mmss(total)))


# ---------------------------------------------------------------- 字幕

def char_width(s):
    """每行 22 字的计数：CJK 算 1，其它字符算 0.5。"""
    w = 0.0
    for ch in s:
        w += 1.0 if ord(ch) > 0x2E7F else 0.5
    return w


def strip_punct(s):
    return "".join(ch for ch in s if ch not in "。，、；：…,;:" and ch != " ")


def build_lines(words, src2out, max_chars, gap_break=1.0):
    """把（保留的）词按时间和字数分成字幕行。每行是 [(out_start, out_end, text), ...]。"""
    lines, cur, cur_w = [], [], 0.0
    prev_out_end = None
    for w in words:
        txt = strip_punct(w["text"])
        if not txt:
            continue
        s, e = src2out(w["start"]), src2out(w["end"])
        if e < s:
            e = s
        item = (s, max(e, s + 0.02), txt)
        w_txt = char_width(txt)
        need_break = False
        if cur:
            if cur_w + w_txt > max_chars:
                need_break = True
            elif prev_out_end is not None and s - prev_out_end > gap_break:
                need_break = True
            elif cur[-1][3][-1:] in SENT_END:
                need_break = True
            elif cur_w >= max_chars * 0.55 and cur[-1][3][-1:] in CLAUSE:
                need_break = True
        if need_break:
            if cur_w + w_txt > max_chars:
                # 超长时优先回溯到最近的标点或停顿处断行，避免把一个词切成两半
                cut_at = None
                acc_w = 0.0
                for j, (_, e_j, _, raw_j) in enumerate(cur):
                    acc_w += char_width(strip_punct(raw_j))
                    nxt_s = cur[j + 1][0] if j + 1 < len(cur) else s
                    if acc_w >= max_chars * 0.4 and (raw_j[-1:] in ALL_PUNCT or nxt_s - e_j >= 0.25):
                        cut_at = j + 1
                if cut_at is not None and cut_at < len(cur):
                    lines.append(cur[:cut_at])
                    cur = cur[cut_at:]
                    cur_w = sum(char_width(t) for _, _, t, _ in cur)
                    need_break = cur_w + w_txt > max_chars
            if need_break:
                lines.append(cur)
                cur, cur_w = [], 0.0
        cur.append((s, item[1], txt, w["text"]))
        cur_w += w_txt
        prev_out_end = item[1]
    if cur:
        lines.append(cur)
    # 每行末尾若是句末标点（？！）保留，其它去掉
    out = []
    for ln in lines:
        out.append([(s, e, t) for s, e, t, _ in ln])
    return out


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: %(w)d
PlayResY: %(h)d
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,%(font)s,%(size)d,&H004AD5FF,&H00FFFFFF,&H00141414,&H90000000,1,0,0,0,100,100,%(sp).1f,0,1,%(ol).1f,%(sh).1f,2,%(ml)d,%(ml)d,%(mv)d,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass(path, lines, offset, clip_start, clip_end, font, size, hold=0.6):
    """把字幕行写成 ASS。offset：把输出时间减去多少（chunk 起点）；clip 区间外的行不写。
    \\k 是相对事件起点的累计时长，所以事件被 chunk 起点截断时，已说过的词 k=0 立刻变黄。"""
    ev = []
    for idx, ln in enumerate(lines):
        st = ln[0][0]
        en = ln[-1][1] + hold
        if idx + 1 < len(lines):
            en = min(en, lines[idx + 1][0][0] - 0.02)
        en = max(en, ln[-1][1])
        if en <= clip_start or st >= clip_end:
            continue
        ev_start = max(st, clip_start)
        ev_end = min(en, clip_end)
        parts, cursor = [], ev_start  # cursor：已经分配到的时间点
        for j, (s, e, t) in enumerate(ln):
            nxt = ln[j + 1][0] if j + 1 < len(ln) else e
            seg_end = max(nxt, e)     # 这个词的高亮持续到下一个词开始
            k_cs = int(round(max(0.0, seg_end - cursor) * 100))
            cursor = max(cursor, seg_end)
            parts.append("{\\k%d}%s" % (k_cs, t.replace("{", "").replace("}", "")))
        ev.append("Dialogue: 0,%s,%s,Sub,,0,0,0,,%s" % (
            ass_time(ev_start - offset), ass_time(ev_end - offset), "".join(parts)))
    with open(path, "w", encoding="utf-8") as f:
        f.write(ASS_HEADER % {"w": OUT_W, "h": OUT_H, "font": font, "size": int(round(size * UI_K)),
                              "mv": int(round(56 * UI_K)), "ml": int(round(80 * UI_K)),
                              "sp": 0.5 * UI_K, "ol": 3.5 * UI_K, "sh": 1.5 * UI_K})
        f.write("\n".join(ev) + "\n")
    return len(ev)


# ---------------------------------------------------------------- PNG 生成（标准库，带超采样抗锯齿）

def write_png(path, w, h, rows, gray=False):
    """rows：每行 bytes（RGBA 4 字节/像素，或灰度 1 字节/像素）。"""
    import struct
    import zlib

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + r for r in rows)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0 if gray else 6, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
                chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


SS = 4  # 每个像素 4x4 超采样


def raster(w, h, sample, gray=False):
    """sample(x, y) → 灰度 0..1 或 (r,g,b,a)（a 0..1），在像素内 SS×SS 个采样点上平均。"""
    rows = []
    inv = 1.0 / (SS * SS)
    for y in range(h):
        row = bytearray()
        for x in range(w):
            if gray:
                acc = 0.0
                for sy in range(SS):
                    for sx in range(SS):
                        acc += sample(x + (sx + 0.5) / SS, y + (sy + 0.5) / SS)
                row.append(int(round(min(1.0, acc * inv) * 255)))
            else:
                r = g = b = a = 0.0
                for sy in range(SS):
                    for sx in range(SS):
                        cr, cg, cb, ca = sample(x + (sx + 0.5) / SS, y + (sy + 0.5) / SS)
                        r += cr * ca
                        g += cg * ca
                        b += cb * ca
                        a += ca
                if a > 0:
                    r, g, b = r / a, g / a, b / a
                a *= inv
                row += bytes((int(round(r * 255)), int(round(g * 255)), int(round(b * 255)),
                              int(round(min(1.0, a) * 255))))
        rows.append(bytes(row))
    return rows


def make_masks(workdir, d, border):
    """摄像头圆形遮罩（灰度）与白色圆环（RGBA），超采样抗锯齿。"""
    mask = os.path.join(workdir, "cam_mask.png")
    ring = os.path.join(workdir, "cam_ring.png")
    c = d / 2.0
    r = d / 2.0

    def m(x, y):
        return 1.0 if (x - c) ** 2 + (y - c) ** 2 <= r * r else 0.0

    write_png(mask, d, d, raster(d, d, m, gray=True), gray=True)
    D = d + 2 * border
    C = D / 2.0
    R = D / 2.0

    def rg(x, y):
        inside = (x - C) ** 2 + (y - C) ** 2 <= R * R
        return (1.0, 1.0, 1.0, 1.0 if inside else 0.0)

    write_png(ring, D, D, raster(D, D, rg))
    return mask, ring


def _poly_contains(pts, x, y):
    inside = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def _poly_dist(pts, x, y):
    best = 1e9
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / L2))
        px, py = x1 + t * dx, y1 + t * dy
        best = min(best, math.hypot(x - px, y - py))
    return best


def make_cursor_sprites(workdir, scale, halo_d, halo_alpha, flash_frames):
    """自绘光标（找不到系统 PNG 光标时的回退）：黑色填充 + 白色描边。
    返回 dict：arrow/ibeam → (png, hotx, hoty)，halo → png，flash → [png...]。"""
    out = {}
    outline = 1.6 * scale
    pad = int(math.ceil(outline)) + 2

    def shape_png(name, pts_1x, hot_1x):
        pts = [(x * scale + pad, y * scale + pad) for x, y in pts_1x]
        w = int(math.ceil(max(p[0] for p in pts) + pad))
        h = int(math.ceil(max(p[1] for p in pts) + pad))

        def s(x, y):
            if _poly_contains(pts, x, y):
                return (0.0, 0.0, 0.0, 1.0)
            if _poly_dist(pts, x, y) <= outline:
                return (1.0, 1.0, 1.0, 1.0)
            return (0.0, 0.0, 0.0, 0.0)

        path = os.path.join(workdir, "cursor_%s.png" % name)
        write_png(path, w, h, raster(w, h, s))
        return (path, hot_1x[0] * scale + pad, hot_1x[1] * scale + pad)

    # macOS 箭头轮廓（1x 点坐标，热点在尖端）
    arrow = [(0, 0), (0, 16.5), (4.6, 12.6), (7.6, 19.4), (10.6, 18.0), (7.6, 11.4), (13.0, 11.4)]
    out["arrow"] = shape_png("arrow", arrow, (0, 0))
    # I 型光标（1x，宽 9、高 18，热点在中心）
    ib = [(0, 0), (9, 0), (9, 1.6), (5.4, 2.4), (5.4, 15.6), (9, 16.4), (9, 18), (0, 18),
          (0, 16.4), (3.6, 15.6), (3.6, 2.4), (0, 1.6)]
    out["ibeam"] = shape_png("ibeam", ib, (4.5, 9))

    def halo_png(name, d, alpha):
        D = int(math.ceil(d)) + 2
        c = D / 2.0
        r = d / 2.0

        def s(x, y):
            dist = math.hypot(x - c, y - c)
            if dist >= r:
                return (1.0, 0.84, 0.29, 0.0)
            # 内 70% 恒定，外圈平滑衰减
            k = 1.0 if dist <= 0.7 * r else (r - dist) / (0.3 * r)
            return (1.0, 0.84, 0.29, alpha * k)

        path = os.path.join(workdir, "cursor_%s.png" % name)
        write_png(path, D, D, raster(D, D, s))
        return (path, D)

    out["halo"] = halo_png("halo", halo_d, halo_alpha)
    out["flash"] = []
    for i in range(flash_frames):
        f = (i + 1) / float(flash_frames + 1)
        out["flash"].append(halo_png("flash%d" % i, halo_d * (1.0 + 0.6 * f), halo_alpha * (1.0 - f)))
    return out


# ---------------------------------------------------------------- 光标轨迹

def load_pointer_track(bundle):
    """读 metadata/pointer-track.jsonl；返回 (events, points_per_px)。坐标单位「点」。"""
    path = os.path.join(bundle, "metadata", "pointer-track.jsonl")
    if not os.path.exists(path):
        return None, None
    ev = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            loc = d.get("captureSpaceLocation") or d.get("absoluteLocation")
            if not loc:
                continue
            ev.append((float(d["timestamp"]), float(loc["x"]), float(loc["y"]),
                       d.get("action", "move"), d.get("cursorIdentifier", "arrow"),
                       d.get("isWithinCapture", True)))
    ev.sort(key=lambda e: e[0])
    sess = os.path.join(bundle, "metadata", "session.json")
    rec_scale = 2.0
    cap = None
    if os.path.exists(sess):
        s = json.load(open(sess, encoding="utf-8"))
        rec_scale = float(s.get("recordingScale") or s.get("pixelScale") or 2.0)
        cf = s.get("captureFrame", {}).get("size")
        if cf:
            cap = (float(cf["width"]), float(cf["height"]))
    return ev, {"scale": rec_scale, "capture": cap}


class CursorSampler:
    """按时间线性插值光标位置；顺便给出该时刻的光标类型。"""

    def __init__(self, events):
        self.t = [e[0] for e in events]
        self.ev = events
        import bisect
        self._bisect = bisect.bisect_right

    def at(self, t):
        if not self.ev:
            return None
        i = self._bisect(self.t, t)
        if i == 0:
            e = self.ev[0]
            return e[1], e[2], e[4]
        if i >= len(self.ev):
            e = self.ev[-1]
            return e[1], e[2], e[4]
        a, b = self.ev[i - 1], self.ev[i]
        dt = b[0] - a[0]
        # 两个事件间隔太久（>0.5s）就不插值，停在前一个位置
        if dt <= 0 or dt > 0.5:
            return a[1], a[2], a[4]
        k = (t - a[0]) / dt
        return a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k, a[4]


def write_cursor_cmds(path, chunk, fps, sampler, clicks, geom, sprites, canvas, flash_n):
    """为一个 chunk 写 sendcmd 文件：每帧移动光标精灵；类型切换 / 点击闪光只在变化时发命令。
    geom: (scale_px→out, off_x, off_y, pt→px)。"""
    sc, ox, oy, pt2px = geom
    C = canvas // 2
    lines = []
    frame_src = []
    for s, e in chunk["segs"]:
        for f in range(s, e):
            frame_src.append(f / fps)
    click_i = 0
    cur_type = None
    active_flash = None  # (index) 上一帧显示的闪光层
    n_click = 0
    for k, ts in enumerate(frame_src):
        t_out = k / fps
        pos = sampler.at(ts)
        if pos is None:
            continue
        px, py, ctype = pos
        x = ox + px * pt2px * sc
        y = oy + py * pt2px * sc
        cmds = ["overlay@cur x %d" % int(round(x - C)), "overlay@cur y %d" % int(round(y - C))]
        ctype = ctype if ctype in ("arrow", "ibeam") else "arrow"
        if ctype != cur_type:
            for name in ("arrow", "ibeam"):
                _, hx, hy = sprites[name]
                if name == ctype:
                    cmds += ["overlay@%s x %d" % (name, int(round(C - hx))),
                             "overlay@%s y %d" % (name, int(round(C - hy)))]
                else:
                    cmds += ["overlay@%s x -500" % name, "overlay@%s y -500" % name]
            cur_type = ctype
        # 点击闪光：源时间落在 [click, click + flash_n/fps) 的帧显示对应帧的闪光层
        while click_i < len(clicks) and clicks[click_i] + flash_n / fps <= ts:
            click_i += 1
        fl = None
        if click_i < len(clicks) and clicks[click_i] <= ts:
            fl = int((ts - clicks[click_i]) * fps)
            fl = min(max(fl, 0), flash_n - 1)
        if fl != active_flash:
            if active_flash is not None:
                cmds += ["overlay@flash%d x -500" % active_flash, "overlay@flash%d y -500" % active_flash]
            if fl is not None:
                fd = sprites["flash"][fl][1]
                cmds += ["overlay@flash%d x %d" % (fl, C - fd // 2), "overlay@flash%d y %d" % (fl, C - fd // 2)]
                if fl == 0:
                    n_click += 1
            active_flash = fl
        lines.append("%.4f %s;" % (t_out, ", ".join(cmds)))
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return n_click


# ---------------------------------------------------------------- 字幕审阅文件

def srt_time(t):
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    sec = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        ms = 999
    return "%02d:%02d:%02d,%03d" % (h, m, sec, ms)


def line_span(lines, idx, hold=0.6):
    ln = lines[idx]
    st = ln[0][0]
    en = ln[-1][1] + hold
    if idx + 1 < len(lines):
        en = min(en, lines[idx + 1][0][0] - 0.02)
    return st, max(en, ln[-1][1])


def write_review_files(out_path, lines, keep_f, fps, edl, min_silence=1.5):
    """在成片旁写 <out>.srt 和 <out>-字幕.md：后者按句一行并标出剪切接缝，方便扫读判断接得通不通。"""
    base = os.path.splitext(out_path)[0]
    srt = base + ".srt"
    with open(srt, "w", encoding="utf-8") as f:
        for i in range(len(lines)):
            st, en = line_span(lines, i)
            f.write("%d\n%s --> %s\n%s\n\n" % (i + 1, srt_time(st), srt_time(en),
                                              "".join(t for _, _, t in lines[i])))
    # 接缝：相邻两个保留段之间
    cuts = edl.get("cuts", [])
    seams = []
    acc = 0
    for i, (s_f, e_f) in enumerate(keep_f):
        if i > 0:
            prev_end = keep_f[i - 1][1] / fps
            nxt_start = s_f / fps
            gap = nxt_start - prev_end
            reasons = []
            for c in cuts:
                if c["start"] < nxt_start + 1e-6 and c["end"] > prev_end - 1e-6:
                    if c["type"] == "manual":
                        reasons.append("手工:%s" % (c.get("reason") or "").split("（")[0])
            seams.append({"out": acc / fps, "src_a": prev_end, "src_b": nxt_start, "gap": gap,
                          "manual": bool(reasons), "reason": "、".join(sorted(set(reasons))) or "静音"})
        acc += e_f - s_f
    shown = [x for x in seams if x["manual"] or x["gap"] >= min_silence]
    hidden = [x for x in seams if not (x["manual"] or x["gap"] >= min_silence)]
    md = ["# 字幕审阅（成片时间域）", "",
          "- 成片：`%s`" % os.path.basename(out_path),
          "- 字幕 %d 句；剪切接缝 %d 处，其中标出 %d 处（手工删除 + ≥%.1fs 的静音），另有 %d 处短静音剪切未逐条标出，共删 %.1fs。" % (
              len(lines), len(seams), len(shown), min_silence, len(hidden), sum(x["gap"] for x in hidden)),
          "- 看法：接缝行上下两句连起来读，通顺就没问题；不通就回 review.md 找原始时间码调 cuts.json。", ""]
    si = 0
    for i in range(len(lines)):
        st, en = line_span(lines, i)
        while si < len(shown) and shown[si]["out"] <= st + 1e-6:
            x = shown[si]
            md.append("--- 剪切点（原始 %s → %s，删了 %.1f 秒，原因：%s）---" % (
                mmss_short(x["src_a"]), mmss_short(x["src_b"]), x["gap"], x["reason"]))
            si += 1
        # 接缝落在句内（说到一半被剪掉一段）：句后补一条提示
        word_end = lines[i][-1][1]
        inner = [x for x in shown[si:] if st < x["out"] < word_end]
        md.append("%s  %s" % (mmss_short(st), "".join(t for _, _, t in lines[i])))
        for x in inner:
            md.append("--- 剪切点（句内，原始 %s → %s，删了 %.1f 秒，原因：%s）---" % (
                mmss_short(x["src_a"]), mmss_short(x["src_b"]), x["gap"], x["reason"]))
            si += 1
    for x in shown[si:]:
        md.append("--- 剪切点（原始 %s → %s，删了 %.1f 秒，原因：%s）---" % (
            mmss_short(x["src_a"]), mmss_short(x["src_b"]), x["gap"], x["reason"]))
    mdp = base + "-字幕.md"
    open(mdp, "w", encoding="utf-8").write("\n".join(md) + "\n")
    return srt, mdp


# ---------------------------------------------------------------- render

def quantize_keep(keep, fps):
    """保留区间对齐到帧格（1/fps），保证每段帧数是整数，拼接不漂移。"""
    out = []
    for s, e in keep:
        qs = round(s * fps)
        qe = round(e * fps)
        if qe - qs >= 1:
            if out and qs <= out[-1][1]:
                out[-1] = (out[-1][0], max(out[-1][1], qe))
            else:
                out.append((qs, qe))
    return out  # 单位：帧


def select_expr(segs_frames, fps, base_frame):
    """select 表达式：帧时间 t（相对 chunk 起点）落在任一保留段内。用 1/(2fps) 的余量避开浮点边界。"""
    eps = 1.0 / (2 * fps)
    terms = []
    for s, e in segs_frames:
        a = (s - base_frame) / fps - eps
        b = (e - base_frame) / fps - eps
        terms.append("gte(t,%.5f)*lt(t,%.5f)" % (a, b))
    return "+".join(terms)


def ff_escape(path):
    return path.replace("\\", "\\\\").replace("'", r"\'").replace(":", r"\:")


def render_chunk(job):
    ci, chunk, media, workdir, mask, ring, ass_path, cam_d, cam_x, cam_y, encoder, bitrate, cursor = job
    fps = OUT_FPS
    src_start = chunk["src_start"] / fps
    src_end = chunk["src_end"] / fps
    n_frames = chunk["n_frames"]
    expr = select_expr(chunk["segs"], fps, chunk["src_start"])
    out = os.path.join(workdir, "chunk_%03d.mp4" % ci)
    inputs = ["-ss", "%.4f" % src_start, "-to", "%.4f" % src_end, "-i", media["screen"],
              "-ss", "%.4f" % src_start, "-to", "%.4f" % src_end, "-i", media["camera"],
              "-loop", "1", "-i", mask, "-loop", "1", "-i", ring]
    fc = (
        "[0:v]fps=%(fps)d,select='%(expr)s',setpts=N/(%(fps)d*TB),"
        "scale=%(W)d:%(H)d:force_original_aspect_ratio=decrease:flags=bicubic,"
        "pad=%(W)d:%(H)d:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p[bg];"
        "[1:v]fps=%(fps)d,select='%(expr)s',setpts=N/(%(fps)d*TB),"
        "crop='min(iw,ih)':'min(iw,ih)',scale=%(d)d:%(d)d:flags=lanczos,format=rgba[camsq];"
        "[camsq][2:v]alphamerge[cam];"
        "[bg][3:v]overlay=%(rx)d:%(ry)d:format=auto[bg2];"
        "[bg2][cam]overlay=%(cx)d:%(cy)d:format=auto[bg3];"
    ) % {"fps": fps, "expr": expr, "W": OUT_W, "H": OUT_H, "d": cam_d,
         "cx": cam_x, "cy": cam_y, "rx": cam_x - CAM_BORDER, "ry": cam_y - CAM_BORDER}
    last = "[bg3]"
    if cursor:
        # 光标精灵：在小画布上合成光圈 + 闪光帧 + 两种光标，再整体按帧移动叠到画面上
        canvas = cursor["canvas"]
        sprites = cursor["sprites"]
        C = canvas // 2
        idx = 4
        names = []
        inputs += ["-loop", "1", "-i", sprites["halo"][0]]
        names.append(("halo", idx))
        idx += 1
        for i, (fpng, _) in enumerate(sprites["flash"]):
            inputs += ["-loop", "1", "-i", fpng]
            names.append(("flash%d" % i, idx))
            idx += 1
        for nm in ("arrow", "ibeam"):
            inputs += ["-loop", "1", "-i", sprites[nm][0]]
            names.append((nm, idx))
            idx += 1
        fc += ("color=black@0:s=%dx%d:r=%d,format=rgba,sendcmd=f='%s'[cv0];"
               % (canvas, canvas, fps, ff_escape(cursor["cmd_files"][ci])))
        prev = "[cv0]"
        for j, (nm, ii) in enumerate(names):
            if nm == "halo":
                hd = sprites["halo"][1]
                fc += "%s[%d:v]overlay=%d:%d:format=auto[cv%d];" % (prev, ii, C - hd // 2, C - hd // 2, j + 1)
            else:
                # 闪光帧与两种光标默认挪到画布外，由 sendcmd 按帧挪进来
                fc += "%s[%d:v]overlay@%s=x=-500:y=-500:format=auto[cv%d];" % (prev, ii, nm, j + 1)
            prev = "[cv%d]" % (j + 1)
        fc += "[bg3]%soverlay@cur=x=-500:y=-500:format=auto:eof_action=pass[bg4];" % prev
        last = "[bg4]"
    fc += "%sass=filename='%s'[v]" % (last, ff_escape(ass_path))
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostats", "-y"] + inputs + [
        "-filter_complex", fc, "-map", "[v]", "-an",
        "-r", str(fps), "-fps_mode", "cfr", "-frames:v", str(n_frames),
        "-c:v", encoder] + (["-b:v", bitrate] if encoder.endswith("videotoolbox") else ["-crf", "20", "-preset", "veryfast"]) + [
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    t0 = time.time()
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        return (ci, None, p.stderr[-3000:] + "\nfilter_complex:\n" + fc, 0)
    return (ci, out, "", time.time() - t0)


def count_frames(path):
    p = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", path, "-map", "0:v:0", "-c", "copy",
                        "-f", "null", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    m = re.findall(r"frame=\s*(\d+)", p.stderr)
    return int(m[-1]) if m else -1


def render_audio(mic, keep_frames, fps, workdir, fade_ms=6):
    """麦克风 → PCM → 按保留区间逐采样切出来（边界做几毫秒淡入淡出防爆音）→ AAC。"""
    sr = 48000
    pcm = os.path.join(workdir, "mic_48k.wav")
    if not os.path.exists(pcm):
        run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", mic,
             "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", pcm])
    wf = wave.open(pcm, "rb")
    assert wf.getnchannels() == 1 and wf.getsampwidth() == 2
    total = wf.getnframes()
    raw = wf.readframes(total)
    wf.close()
    samples = array.array("h")
    samples.frombytes(raw)
    out = array.array("h")
    fade = int(sr * fade_ms / 1000)
    for s_f, e_f in keep_frames:
        a = int(round(s_f / fps * sr))
        b = int(round(e_f / fps * sr))
        a, b = max(0, min(a, total)), max(0, min(b, total))
        seg = samples[a:b]
        n = len(seg)
        if n == 0:
            continue
        f = min(fade, n // 2)
        for i in range(f):
            g = i / float(f)
            seg[i] = int(seg[i] * g)
            seg[n - 1 - i] = int(seg[n - 1 - i] * g)
        out.extend(seg)
    cut_wav = os.path.join(workdir, "audio_cut.wav")
    ww = wave.open(cut_wav, "wb")
    ww.setnchannels(1)
    ww.setsampwidth(2)
    ww.setframerate(sr)
    ww.writeframes(out.tobytes())
    ww.close()
    aac = os.path.join(workdir, "audio_cut.m4a")
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", cut_wav,
         "-c:a", "aac", "-b:a", "160k", aac])
    return aac, len(out) / float(sr)


def apply_profile(a, screen):
    """按 --profile / --size / --fps / --bitrate 确定输出规格，改写模块级 OUT_* 与 UI_K。"""
    global OUT_W, OUT_H, OUT_FPS, UI_K, CAM_MARGIN, CAM_BORDER
    prof = PROFILES[a.profile]
    sw, sh = ffprobe_video_size(screen)
    sfps = ffprobe_fps(screen) or 30.0
    size = prof["size"] or (sw, sh)
    fps = prof["fps"] or sfps
    if a.size:
        m = re.match(r"^(\d+)x(\d+)$", a.size)
        if not m:
            die("--size 格式应为 WxH，例如 1920x1080")
        size = (int(m.group(1)), int(m.group(2)))
    if a.fps:
        fps = a.fps
    w, h = size
    if w % 2 or h % 2:
        log("提示：输出尺寸 %dx%d 有奇数，向下取偶数为 %dx%d" % (w, h, w - w % 2, h - h % 2))
        w, h = w - w % 2, h - h % 2
    OUT_W, OUT_H = w, h
    OUT_FPS = int(round(fps))
    UI_K = OUT_W / 1920.0
    CAM_MARGIN = int(round(24 * UI_K))
    CAM_BORDER = max(1, int(round(3 * UI_K)))
    if a.bitrate == "auto":
        if prof["bitrate"]:
            a.bitrate = prof["bitrate"]
        else:
            # 以 3024x1900@60 ≈ 16M 为基准按像素率换算，限制在 6M~40M
            mbps = 16.0 * (OUT_W * OUT_H * OUT_FPS) / (3024.0 * 1900 * 60)
            a.bitrate = "%dM" % int(round(min(40.0, max(6.0, mbps))))
    log("输出规格 [%s]：%dx%d %dfps，码率 %s，UI 缩放 %.3f（源 %dx%d @%gfps）" % (
        a.profile, OUT_W, OUT_H, OUT_FPS, a.bitrate, UI_K, sw, sh, sfps))


def cmd_render(a):
    t_start = time.time()
    workdir = a.workdir
    edl = json.load(open(os.path.join(workdir, "edl.json"), encoding="utf-8"))
    media = edl["media"]
    for k, v in media.items():
        if not os.path.exists(v):
            die("素材不存在：%s=%s" % (k, v))
    apply_profile(a, media["screen"])
    fps = OUT_FPS
    keep = [(k["start"], k["end"]) for k in edl["keep"]]
    keep_f = quantize_keep(keep, fps)

    # 预览：只取输出时间轴上 [preview_start, preview_start+preview) 的那一截
    if a.preview:
        p0 = int(round(a.preview_start * fps))
        p1 = p0 + int(round(a.preview * fps))
        acc, sel = 0, []
        for s, e in keep_f:
            n = e - s
            lo, hi = max(acc, p0), min(acc + n, p1)
            if hi > lo:
                sel.append((s + (lo - acc), s + (hi - acc)))
            acc += n
        keep_f = sel
        if not keep_f:
            die("预览区间超出成片长度")

    total_frames = sum(e - s for s, e in keep_f)
    log("保留段 %d 个，输出 %d 帧 = %s" % (len(keep_f), total_frames, mmss(total_frames / fps)))

    # 原始时间 → 输出时间（考虑预览偏移）
    bounds = []
    acc = 0
    for s, e in keep_f:
        bounds.append((s / fps, e / fps, acc / fps))
        acc += e - s

    def src2out(t):
        for s, e, o in bounds:
            if t < s:
                return o  # 落在被删区间：贴到下一段开头
            if t <= e:
                return o + (t - s)
        return bounds[-1][2] + (bounds[-1][1] - bounds[-1][0]) if bounds else 0.0

    # 字幕行：只用未被手工删除的词；只要词的时间跨度与任一保留段有重叠就进字幕，
    # 不因为一部分落在静音删除区间里就丢（whisper 常把停顿算进词的跨度）
    kept_words = []
    for w in edl["words"]:
        if w["deleted"]:
            continue
        if any(w["start"] < e and w["end"] > s for s, e, _ in bounds):
            kept_words.append(w)
    lines = build_lines(kept_words, src2out, a.max_chars)
    log("字幕 %d 行" % len(lines))

    # 摄像头几何
    cam_d = int(round(OUT_W * CAM_RATIO))
    cam_x = OUT_W - CAM_MARGIN - cam_d
    cam_y = OUT_H - CAM_MARGIN - cam_d
    mask, ring = make_masks(workdir, cam_d, CAM_BORDER)

    # 分 chunk：按源时间跨度切，方便并行；chunk 边界一定在保留段边界上
    chunks, cur = [], None
    for s, e in keep_f:
        if cur is None or (e - cur["src_start"]) / fps > a.chunk_seconds:
            if cur:
                chunks.append(cur)
            cur = {"src_start": s, "src_end": e, "segs": [(s, e)], "n_frames": e - s}
        else:
            cur["src_end"] = e
            cur["segs"].append((s, e))
            cur["n_frames"] += e - s
    if cur:
        chunks.append(cur)
    acc = 0
    for c in chunks:
        c["out_start"] = acc / fps
        c["out_end"] = (acc + c["n_frames"]) / fps
        acc += c["n_frames"]

    for f in os.listdir(workdir):
        if re.match(r"chunk_\d+\.(mp4|ass|cmd)$", f):
            os.remove(os.path.join(workdir, f))

    # 光标层
    cursor = None
    if not a.no_cursor:
        events, meta = load_pointer_track(edl["bundle"])
        if not events:
            log("警告：没有 metadata/pointer-track.jsonl，成片不叠光标")
        else:
            sw, sh = ffprobe_video_size(media["screen"])
            sc = min(OUT_W / float(sw), OUT_H / float(sh))
            ox = (OUT_W - sw * sc) / 2.0
            oy = (OUT_H - sh * sc) / 2.0
            pt2px = meta["scale"]
            # 光标大小以 1080p 为基准（屏幕 fit 进 1920x1080 时的比例），再按 UI_K 放大
            sc_ref = min(1920.0 / sw, 1080.0 / sh)
            spr_scale = pt2px * sc_ref * a.cursor_scale * UI_K
            halo_px = a.halo_size * UI_K
            flash_n = int(round(0.25 * fps))
            sprites = make_cursor_sprites(workdir, spr_scale, halo_px, a.halo_alpha, flash_n)
            # 画布要装下闪光最大直径和光标本体（箭头从热点向右下延伸约 20 点）
            canvas = int(max(halo_px * 1.6 + 16, 2 * (22 * spr_scale + 8)))
            canvas = max(canvas, int(160 * UI_K))
            canvas += canvas % 2
            clicks = [e[0] for e in events if e[3] == "down"]
            # 被删区间里的点击丢掉（只保留落在保留段里的）
            clicks = [t for t in clicks if any(s <= t < e for s, e, _ in bounds)]
            sampler = CursorSampler(events)
            geom = (sc, ox, oy, pt2px)
            cmd_files, n_clicks = [], 0
            for ci, c in enumerate(chunks):
                p = os.path.join(workdir, "chunk_%03d.cmd" % ci)
                n_clicks += write_cursor_cmds(p, c, fps, sampler, clicks, geom, sprites, canvas, flash_n)
                cmd_files.append(p)
            cursor = {"sprites": sprites, "cmd_files": cmd_files, "canvas": canvas}
            from collections import Counter
            cnt = Counter(e[3] for e in events)
            log("光标：%d 个事件（%s），保留段内点击 %d 次，精灵画布 %dpx，光标放大 %.2f 倍（%.1f px/点）" % (
                len(events), ", ".join("%s=%d" % kv for kv in sorted(cnt.items())), n_clicks, canvas,
                a.cursor_scale, spr_scale))

    jobs = []
    for ci, c in enumerate(chunks):
        ass_path = os.path.join(workdir, "chunk_%03d.ass" % ci)
        write_ass(ass_path, lines, c["out_start"], c["out_start"], c["out_end"], a.font, a.font_size)
        jobs.append((ci, c, media, workdir, mask, ring, ass_path, cam_d, cam_x, cam_y,
                     a.encoder, a.bitrate, cursor))
    # 也写一份全片 ASS 留档
    write_ass(os.path.join(workdir, "subtitles.ass"), lines, 0.0, 0.0, 1e9, a.font, a.font_size)

    log("视频：%d 个 chunk，%d 路并行，编码器 %s" % (len(chunks), a.jobs, a.encoder))
    outs = [None] * len(chunks)
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for ci, out, err, dt in ex.map(render_chunk, jobs):
            if out is None:
                sys.stderr.write(err)
                die("chunk %d 渲染失败" % ci)
            outs[ci] = out
            got = count_frames(out)
            want = chunks[ci]["n_frames"]
            flag = "" if got == want else "  ← 帧数不符（期望 %d）" % want
            log("  chunk %03d 完成 %.1fs，%d 帧%s" % (ci, dt, got, flag))

    # 拼接视频（无重编码）
    lst = os.path.join(workdir, "concat.txt")
    with open(lst, "w") as f:
        for o in outs:
            f.write("file '%s'\n" % os.path.abspath(o).replace("'", r"'\''"))
    video = os.path.join(workdir, "video_cut.mp4")
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", lst, "-c", "copy", video])

    # 音频
    log("音频：按采样切分并编码 AAC")
    aac, a_dur = render_audio(media["mic"], keep_f, fps, workdir)
    log("  音频 %s，视频 %s" % (mmss(a_dur), mmss(total_frames / fps)))

    out_path = a.out
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", video, "-i", aac,
         "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-shortest", "-movflags", "+faststart", out_path])
    srt, mdp = write_review_files(out_path, lines, keep_f, fps, edl)
    log("字幕审阅：%s、%s" % (srt, mdp))
    dt = time.time() - t_start
    log("完成：%s（%s，耗时 %.0fs）" % (out_path, mmss(ffprobe_duration(out_path)), dt))
    if not a.keep_temp:
        for o in outs:
            os.remove(o)


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(prog="lecture-cut", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    an = sub.add_parser("analyze", help="静音检测 + 手工锚点删除 → edl.json / review.md",
                        formatter_class=argparse.RawDescriptionHelpFormatter,
                        description="""在麦克风轨上找静音，叠加 --cuts 里用文字锚点写的手工删除清单，
生成保留区间清单 edl.json 和给人过目的 review.md。

cuts.json 是一个数组，每条：
  {"from": "起始短语", "to_before": "结束短语（不含）", "reason": "..."}
  {"from": "起始短语", "to": "结束短语（含）", "reason": "..."}
  {"from": "短语", "reason": "..."}                       # 只删这个短语本身
可选字段：
  "from_occurrence" / "to_occurrence": "first"（默认）| "last" | 正整数（第几次出现）
  "skip_if_missing": true                                  # 起始短语不存在时跳过而不是报错
锚点匹配：去掉标点和空格、不分大小写后做子串匹配；找不到会报错并打印附近文本。""")
    an.add_argument("--bundle", required=True, help="ScreenKite 的 .skbundle 目录（只读）")
    an.add_argument("--words", required=True, help="whisper 词级转写 json（sourceWords[]，秒）")
    an.add_argument("--out", required=True, help="工作目录，写 edl.json / review.md")
    an.add_argument("--cuts", help="手工删除清单 cuts.json")
    an.add_argument("--term-fixes", help="术语修正字典 json：{\"错写\": \"正写\"}，读入转写时先替换再匹配锚点")
    an.add_argument("--silence-db", type=float, default=-35, help="静音阈值 dB（默认 -35）")
    an.add_argument("--silence-min", type=float, default=0.35, help="最短静音秒数（默认 0.35）")
    an.add_argument("--silence-pad", type=float, default=0.12, help="静音两端各保留的呼吸余量秒数（默认 0.12）")
    an.set_defaults(func=cmd_analyze)

    rd = sub.add_parser("render", help="按 edl.json 裁剪拼接、叠摄像头、烧字幕 → mp4",
                        formatter_class=argparse.RawDescriptionHelpFormatter,
                        description="""输出 H.264 + AAC。规格由 --profile 决定：draft（默认）1280x720 30fps 低码率，看草片、审清单用；
final 分辨率与帧率直接取屏幕源（不缩放不加黑边），码率按像素率换算，正式片用。--size / --fps 可覆盖。
字幕、摄像头、边距、白环、光标、光圈全部按「输出宽 / 1920」等比缩放。
屏幕等比 fit 到画面（黑底居中，final 下恰好铺满）；摄像头圆形、直径为宽度 10%%、右下角、边距 24px、3px 白边；
字幕底部居中、逐字高亮（ASS \\k 卡拉 OK：说到的字变黄 #FFD54A，未说白色），每行最多 22 字。
鼠标光标默认叠加（自绘带白边的箭头 / I 型光标，放大 1.6 倍，背后有半透明黄色光圈，点击时光圈闪一下），--no-cursor 关闭。
先用 --preview 30 渲 30 秒试片看效果，再渲全片。""")
    rd.add_argument("--workdir", required=True, help="analyze 的输出目录（含 edl.json）")
    rd.add_argument("--out", required=True, help="输出 mp4 路径")
    rd.add_argument("--profile", choices=list(PROFILES), default="draft",
                    help="draft（默认）：720p30 低码率草片，看剪辑用；final：分辨率、帧率跟屏幕源一致，正式片用")
    rd.add_argument("--size", help="覆盖 profile 的输出尺寸，如 1920x1080")
    rd.add_argument("--fps", type=float, default=0, help="覆盖 profile 的输出帧率")
    rd.add_argument("--preview", type=float, default=0, help="只渲成片开头 N 秒（0=全片）")
    rd.add_argument("--preview-start", type=float, default=0, help="预览从成片第几秒开始（默认 0）")
    rd.add_argument("--jobs", type=int, default=4, help="并行 chunk 数（默认 4）")
    rd.add_argument("--chunk-seconds", type=float, default=150, help="每个 chunk 覆盖的源时长上限（默认 150）")
    rd.add_argument("--encoder", default="h264_videotoolbox", help="视频编码器（默认 h264_videotoolbox，可用 libx264）")
    rd.add_argument("--bitrate", default="auto", help="videotoolbox 码率（默认 auto：draft 3M，final 按像素率换算约 16M）")
    rd.add_argument("--font", default="PingFang SC", help="字幕字体名（默认 PingFang SC；备选 Hiragino Sans GB）")
    rd.add_argument("--font-size", type=int, default=50, help="字幕字号（PlayResY=1080，默认 50）")
    rd.add_argument("--max-chars", type=float, default=22, help="每行最多字数（默认 22，CJK 算 1、英文字符算 0.5）")
    rd.add_argument("--no-cursor", action="store_true", help="不叠加鼠标光标层（默认叠加，读 metadata/pointer-track.jsonl）")
    rd.add_argument("--cursor-scale", type=float, default=1.6, help="光标相对真实大小的放大倍数（默认 1.6）")
    rd.add_argument("--halo-size", type=float, default=60, help="光标后面黄色光圈直径 px（默认 60）")
    rd.add_argument("--halo-alpha", type=float, default=0.35, help="光圈不透明度 0~1（默认 0.35）")
    rd.add_argument("--keep-temp", action="store_true", help="保留 chunk 中间文件")
    rd.set_defaults(func=cmd_render)

    a = ap.parse_args()
    if not a.cmd:
        ap.print_help()
        sys.exit(1)
    if not os.path.exists(FFMPEG):
        die("找不到 ffmpeg：%s（可用环境变量 LECTURE_CUT_FFMPEG 指定）" % FFMPEG)
    a.func(a)


if __name__ == "__main__":
    main()
