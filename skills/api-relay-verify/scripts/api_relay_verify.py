#!/usr/bin/env python3
"""api-relay-verify：拿官方直连当对照，查 API 中转有没有注水。

四项检查（Anthropic 协议全做；OpenAI 兼容协议做 inject / effort / meta）：
  inject     同一请求比 input token；Claude 再用官方 count_tokens 反推塞进去的原文
  signature  把中转返回的 thinking 块拿到官方 API 回放：签名真伪、对话前缀有没有被改、是哪个模型生成的
  effort     low / high 两档比思考 token，看推理档位有没有被偷偷调低
  meta       消息 id、model 字段、usage 字段、响应头和官方比

每个结论都带对照组：官方自己的块必须通过、篡改过的签名必须 400、改过前缀的必须报不一致，
对照组不成立时该项判「无法判定」，不硬下结论。

只用 Python 标准库。key 只从环境变量读（--env-file 可加载 KEY=VALUE 文件），任何输出都不写 key。

用法 / Usage:
  api_relay_verify.py --relay-base https://relay.example --relay-key-env RELAY_KEY --model claude-opus-5-5
  api_relay_verify.py --relay-base https://relay.example/v1 --relay-key-env RELAY_KEY --model gpt-x \\
                 --protocol openai --official-key-env OPENAI_API_KEY
"""
import argparse
import concurrent.futures as cf
import copy
import datetime
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

BINDING_BETA = "thinking-binding-controls-2026-08-01"
CLAUDE_CODE = "You are Claude Code, Anthropic's official CLI for Claude."
CANDIDATES = [
    CLAUDE_CODE,
    "You are Claude Code, Anthropic's official CLI for Claude, running within the Claude Agent SDK.",
    "You are a Claude agent, built on Anthropic's Claude Agent SDK.",
    "You are a helpful assistant.",
    "You are Claude, a large language model trained by Anthropic.",
]
TINY = "Reply with exactly one word: OK"
THINK_Q = ("A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. "
           "A second ball costs twice the first. What do one bat and two of the second ball cost? "
           "Answer with just the dollar amount.")
FOLLOW_UP = "Thanks. Reply with just: done"
OUR_SYSTEM = "You are a careful assistant. Keep answers short."
EFFORT_Q = ("How many positive integers n <= 300 make n^2 + n + 41 composite? "
            "Answer with just the number.")
EFFORT_A = "90"
PROBE_MODELS = ["claude-opus-5-5", "claude-fable-5-1", "claude-opus-5", "claude-sonnet-5-5", "claude-haiku-5-5"]

OK, WARN, BAD, UNK, INFO = "✅", "⚠️", "❌", "❔", "ℹ️"


# ---------------------------------------------------------------- config

def load_env_files(paths):
    env = {}
    for p in paths or []:
        with open(os.path.expanduser(p)) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return env


def need_key(var, env):
    v = os.environ.get(var) or env.get(var)
    if not v:
        sys.exit(f"缺少 key：环境变量 {var} 未设置（可用 --env-file 指向一个 KEY=VALUE 文件）")
    return v


class Lane:
    def __init__(self, name, base, key, model, protocol, bearer):
        self.name, self.key, self.model, self.protocol, self.bearer = name, key, model, protocol, bearer
        base = base.rstrip("/")
        if protocol == "anthropic" and base.endswith("/v1"):
            base = base[:-3]
        self.base = base


# ---------------------------------------------------------------- http

def _send(url, body, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    t0 = time.monotonic()
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r, r.status, dict(r.headers), t0
    except urllib.error.HTTPError as e:
        return e, e.code, dict(e.headers), t0


def _json(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return {"_raw": raw[:1000].decode("utf-8", "replace")}


def anthropic_post(lane, path, body, beta=None, timeout=900):
    h = {"content-type": "application/json", "anthropic-version": "2023-06-01", "x-api-key": lane.key}
    if lane.bearer:
        h["authorization"] = "Bearer " + lane.key
    if beta:
        h["anthropic-beta"] = beta
    try:
        r, status, hdrs, t0 = _send(lane.base + path, body, h, timeout)
        data = _json(r.read())
    except Exception as e:  # noqa: BLE001 - network errors become a failed row, not a crash
        return {"status": None, "data": {"_raw": repr(e)}, "headers": {}, "latency_s": None}
    return {"status": status, "data": data, "headers": hdrs, "latency_s": round(time.monotonic() - t0, 2)}


def openai_chat(lane, body, timeout=900):
    """Streams (reasoning models can sit silent for minutes), falls back to non-stream if refused."""
    h = {"content-type": "application/json", "authorization": "Bearer " + lane.key}
    url = lane.base + "/chat/completions"
    sbody = {**body, "stream": True, "stream_options": {"include_usage": True}}
    try:
        r, status, hdrs, t0 = _send(url, sbody, h, timeout)
        if status != 200:
            data = _json(r.read())
            if status == 400 and "stream" in json.dumps(data).lower():
                r, status, hdrs, t0 = _send(url, body, h, timeout)
                data = _json(r.read())
            return {"status": status, "data": data, "headers": hdrs, "latency_s": round(time.monotonic() - t0, 2)}
        out = {"id": None, "model": None, "usage": None, "system_fingerprint": None, "content": "", "reasoning_chars": 0}
        for line in r:
            line = line.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            ev = _json(payload.encode())
            for k in ("id", "model", "system_fingerprint"):
                out[k] = out[k] or ev.get(k)
            if ev.get("usage"):
                out["usage"] = ev["usage"]
            for ch in ev.get("choices") or []:
                d = ch.get("delta") or {}
                out["content"] += d.get("content") or ""
                out["reasoning_chars"] += len(d.get("reasoning_content") or "")
        return {"status": 200, "data": out, "headers": hdrs, "latency_s": round(time.monotonic() - t0, 2)}
    except Exception as e:  # noqa: BLE001
        return {"status": None, "data": {"_raw": repr(e)}, "headers": {}, "latency_s": None}


def err_text(res):
    d = res["data"]
    e = d.get("error")
    if isinstance(e, dict):
        return e.get("message") or json.dumps(e, ensure_ascii=False)
    return e or d.get("_raw") or ""


def a_text(d):
    return "".join(b.get("text", "") for b in d.get("content") or [] if b.get("type") == "text")


def signed_block(content):
    return any(b.get("type") == "thinking" and b.get("signature") for b in content or [])


def tamper(content):
    c = copy.deepcopy(content)
    for b in c:
        if b.get("type") == "thinking" and b.get("signature"):
            s = b["signature"]
            i = len(s) // 2
            b["signature"] = s[:i] + ("A" if s[i] != "A" else "B") + s[i + 1:]
            break
    return c


def par(fn, items, n=8):
    with cf.ThreadPoolExecutor(n) as ex:
        return list(ex.map(fn, items))


# ---------------------------------------------------------------- audit

class Audit:
    def __init__(self, args, relay, official):
        self.a, self.relay, self.off = args, relay, official
        self.raw = {"started": datetime.datetime.now().isoformat(timespec="seconds"),
                    "relay": {"base": relay.base, "model": relay.model},
                    "official": {"base": official.base, "model": official.model},
                    "protocol": relay.protocol}
        self.verdicts = []  # (check, mark, one-line conclusion, detail lines)
        self.thinking_cfg = None
        self.injected = None  # system value that reproduces what the relay sent upstream

    def add(self, check, mark, line, details=()):
        self.verdicts.append((check, mark, line, list(details)))

    # ---- shared request builders

    def a_body(self, lane, prompt, system=None, think=None, max_tokens=2000, **extra):
        b = {"model": lane.model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}], **extra}
        if think:
            b.update(copy.deepcopy(think))
        if system is not None:
            b["system"] = system
        return b

    def tokens_in(self, res):
        u = res["data"].get("usage") or {}
        return u.get("input_tokens", u.get("prompt_tokens"))

    # ---- 1 inject + 4 meta share the tiny runs

    def run_tiny(self):
        if self.relay.protocol == "anthropic":
            job = lambda lane: anthropic_post(lane, "/v1/messages", self.a_body(lane, TINY))
        else:
            job = lambda lane: openai_chat(lane, {"model": lane.model, "messages": [{"role": "user", "content": TINY}]})
        lanes = [self.off] * 3 + [self.relay] * 3
        res = par(job, lanes, 6)
        self.tiny = {"official": res[:3], "relay": res[3:]}
        self.raw["tiny"] = {k: [{"status": r["status"], "latency_s": r["latency_s"], "id": r["data"].get("id"),
                                 "model": r["data"].get("model"), "usage": r["data"].get("usage"),
                                 "error": err_text(r) if r["status"] != 200 else None,
                                 "headers": sorted(r["headers"].keys())} for r in v]
                            for k, v in self.tiny.items()}

    def check_inject(self):
        bad = [r for v in self.tiny.values() for r in v if r["status"] != 200]
        if bad:
            self.add("inject", UNK, f"有请求失败，无法比较：{err_text(bad[0])[:160]}")
            return
        off = [self.tokens_in(r) for r in self.tiny["official"]]
        rel = [self.tokens_in(r) for r in self.tiny["relay"]]
        self.raw["inject"] = {"official_input_tokens": off, "relay_input_tokens": rel}
        if None in rel:
            self.add("inject", WARN, "中转的 usage 里没有 input token 字段，没法核对计费", [f"官方 {off}"])
            return
        o, r = statistics.median(off), statistics.median(rel)
        delta = r - o
        details = [f"同一请求 input token：官方 {off}，中转 {rel}"]
        if len(set(rel)) > 1:
            details.append("中转三次不一致：后面可能挂着多个上游池子，或注入是间歇性的")
        if delta == 0:
            self.add("inject", OK, "没有多出 input token", details)
            return
        if delta < 0:
            self.add("inject", WARN, f"中转报的比官方少 {-delta:g}：usage 被改写过，或上游分词器不同", details)
            return
        if self.relay.protocol != "anthropic":
            self.add("inject", WARN, f"每个请求多 {delta:g} 个 input token：中转往请求里加了东西", details)
            return
        # Which known system prompt reproduces the relay's count exactly? (count_tokens is free)
        matched = []
        for c in CANDIDATES + (self.a.candidate or []):
            res = anthropic_post(self.off, "/v1/messages/count_tokens",
                                 {"model": self.off.model, "messages": [{"role": "user", "content": TINY}], "system": c})
            if res["status"] == 200 and res["data"].get("input_tokens") == r:
                matched.append(c)
        self.raw["inject"]["count_matched_candidates"] = matched
        self.count_matched = matched
        if matched:
            details.append(f"加上 system「{matched[0]}」后官方计数正好是 {r:g}")
            self.add("inject", WARN, f"每个请求多 {delta:g} 个 input token，和一句已知的系统提示词吻合", details)
        else:
            self.add("inject", WARN, f"每个请求多 {delta:g} 个 input token，候选库里没有对上的原文", details)

    def check_meta(self):
        o = next((r for r in self.tiny["official"] if r["status"] == 200), None)
        r = next((r for r in self.tiny["relay"] if r["status"] == 200), None)
        if not o or not r:
            self.add("meta", UNK, "缺少成功响应，跳过元数据比对")
            return
        od, rd = o["data"], r["data"]
        lines, mark = [], INFO
        oid, rid = str(od.get("id") or ""), str(rd.get("id") or "")
        lines.append(f"消息 id：官方 `{oid[:10]}…`，中转 `{rid[:10]}…`")
        if self.relay.protocol == "anthropic":
            if rid.startswith("msg_bdrk"):
                lines.append("中转 id 是 Bedrock 格式：上游像是 AWS Bedrock")
            elif rid.startswith("msg_vrtx"):
                lines.append("中转 id 是 Vertex 格式：上游像是 Google Vertex")
            elif oid[:6] and rid[:6] != oid[:6]:
                mark = WARN
                lines.append("中转 id 前缀和官方不同：不是原样透传的官方响应")
        if rd.get("model") != self.relay.model:
            mark = WARN
            lines.append(f"model 字段不一致：请求 {self.relay.model}，返回 {rd.get('model')}")
        ok_, rk = set((od.get("usage") or {}).keys()), set((rd.get("usage") or {}).keys())
        if rk - ok_:
            lines.append(f"usage 多出字段：{sorted(rk - ok_)}（中转或上游平台的实现痕迹）")
        if ok_ - rk:
            lines.append(f"usage 缺少字段：{sorted(ok_ - rk)}")
        if self.relay.protocol == "openai" and bool(od.get("system_fingerprint")) != bool(rd.get("system_fingerprint")):
            lines.append(f"system_fingerprint：官方 {od.get('system_fingerprint')!r}，中转 {rd.get('system_fingerprint')!r}")
        oh = {k.lower() for k in o["headers"]}
        rh = {k.lower() for k in r["headers"]}
        stack = [k for k in rh if any(s in k for s in ("oneapi", "new-api", "newapi", "litellm", "openrouter", "x-powered-by"))]
        if oh != rh:
            lines.append(f"响应头：官方特有 {len(oh - rh)} 个{f'（如 {sorted(oh - rh)[:3]}）' if oh - rh else ''}，"
                         f"中转特有 {sorted(rh - oh)[:6]}")
        if stack:
            lines.append(f"中转系统痕迹：{stack}")
        if self.relay.protocol == "anthropic":
            ct = anthropic_post(self.relay, "/v1/messages/count_tokens",
                                {"model": self.relay.model, "messages": [{"role": "user", "content": TINY}]})
            lines.append(f"count_tokens 接口：中转返回 {ct['status']}")
        lat_o = [x["latency_s"] for x in self.tiny["official"]]
        lat_r = [x["latency_s"] for x in self.tiny["relay"]]
        lines.append(f"小请求耗时：官方 {lat_o}s，中转 {lat_r}s（受本机网络影响，只作参考）")
        self.add("meta", mark, "元数据有差异（见明细）" if mark == WARN else "元数据记录如下", lines)

    # ---- 2 signature replay (Anthropic only)

    def gen(self, lane, system=None):
        for _ in range(3):
            res = anthropic_post(lane, "/v1/messages", self.a_body(lane, THINK_Q, system, self.thinking_cfg, 8000))
            if res["status"] != 200 or signed_block(res["data"].get("content")):
                return res
        return res

    def pick_thinking(self):
        cfgs = [
            {"thinking": {"type": "adaptive", "display": "summarized"}, "output_config": {"effort": "high"}},
            {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}},
            {"thinking": {"type": "enabled", "budget_tokens": 2048}},
        ]
        for cfg in cfgs:
            self.thinking_cfg = cfg
            res = self.gen(self.off)
            if res["status"] == 200:
                return res
        return res

    def replay(self, content, model=None, system=None):
        cfg = copy.deepcopy(self.thinking_cfg)
        th = cfg["thinking"]
        th.pop("display", None)
        th["block_binding"] = {"prefix_mismatch_behavior": "drop_block"}
        if "output_config" in cfg:
            cfg["output_config"] = {"effort": "low"}
        body = {"model": model or self.off.model, "max_tokens": 4000, **cfg,
                "messages": [{"role": "user", "content": THINK_Q},
                             {"role": "assistant", "content": content},
                             {"role": "user", "content": FOLLOW_UP}]}
        if system is not None:
            body["system"] = system
        res = anthropic_post(self.off, "/v1/messages", body, beta=BINDING_BETA)
        tr = res["data"].get("input_transformations")
        if res["status"] != 200:
            outcome = "error"
        else:
            reasons = [t.get("reason") for t in tr or [] if t.get("path") == "messages.1.content.0"]
            outcome = "model_mismatch" if "model_binding_mismatch" in reasons else (
                "prefix_mismatch" if "prefix_binding_mismatch" in reasons else ("keep" if tr is not None else "no_report"))
        return {"outcome": outcome, "status": res["status"], "transformations": tr,
                "error": err_text(res)[:300] if res["status"] != 200 else None}

    def check_signature(self):
        o = self.pick_thinking()
        if o["status"] != 200:
            self.add("signature", UNK, f"官方请求失败，跳过：{err_text(o)[:160]}")
            return
        O = o["data"]["content"]
        if not signed_block(O):
            self.add("signature", UNK, "官方连续 3 次都没返回带签名的 thinking 块，这个模型做不了签名检查")
            return
        r = self.gen(self.relay)
        if r["status"] != 200:
            self.add("signature", UNK, f"中转请求失败：{err_text(r)[:160]}")
            return
        R = r["data"]["content"]
        if not signed_block(R):
            self.add("signature", BAD, "同样的请求官方有带签名的 thinking 块，中转连续 3 次都没有：思考被剥离，或不是真模型",
                     [f"中转返回块类型：{[b.get('type') for b in R]}"])
            return

        ctrl = dict(zip(("A", "E", "D"), par(lambda x: self.replay(*x), [
            (O, None, None), (O, None, OUR_SYSTEM), (tamper(O), None, None)], 3)))
        self.raw["signature"] = {"thinking_cfg": self.thinking_cfg, "controls": ctrl,
                                 "relay_in": self.tokens_in(r), "official_in": self.tokens_in(o)}
        details = []
        if ctrl["A"]["outcome"] != "keep" or ctrl["D"]["outcome"] != "error":
            self.add("signature", UNK, "对照组不成立（官方块回放没通过，或篡改签名没被拒），本项不下结论",
                     [f"对照：{ {k: v['outcome'] for k, v in ctrl.items()} }"])
            return
        prefix_check = ctrl["E"]["outcome"] == "prefix_mismatch"
        if not prefix_check:
            details.append("对照组显示这个模型 / 账号不做对话前缀校验：只能验真伪和模型，查不了注入原文")

        B = self.replay(R)
        if B["outcome"] == "error":
            self.add("signature", BAD if not str(r["data"].get("id", "")).startswith(("msg_bdrk", "msg_vrtx")) else UNK,
                     "官方解不开中转返回的签名：签名是伪造的，或者上游不是 Claude API（Bedrock / Vertex 的块可能跨平台解不开）",
                     [f"官方报错：{B['error']}"])
            return
        sysv = None
        if B["outcome"] == "keep":
            details.append("中转的块按原请求回放直接通过：签名真实，对话前缀没被改动")
        elif B["outcome"] == "prefix_mismatch":
            tried = (getattr(self, "count_matched", []) or []) + [c for c in CANDIDATES + (self.a.candidate or [])
                                                                   if c not in (getattr(self, "count_matched", []) or [])]
            for c in tried:
                for form in (c, [{"type": "text", "text": c}]):
                    if self.replay(R, system=form)["outcome"] == "keep":
                        sysv = form
                        break
                if sysv is not None:
                    break
            if sysv is not None:
                self.injected = sysv
                text = sysv if isinstance(sysv, str) else sysv[0]["text"]
                details.append(f"签名证实：中转在请求前面加了 system「{text}」，除此之外没改动")
            else:
                details.append("签名证实中转改过请求（system / tools / 消息），但候选库里没有对上的原文；可用 --candidate 补充猜测")
        elif B["outcome"] == "model_mismatch":
            self.add("signature", BAD, f"签名真实，但不是 {self.off.model} 生成的块（官方报模型不匹配）", details)
            return
        D2 = self.replay(tamper(R), system=sysv)
        if D2["outcome"] != "error":
            details.append("注意：篡改后的中转签名没被拒，回放结论存疑")

        # model identity: the relay block must be readable / unreadable on exactly the same models as an official block
        probes = []
        for m in [self.off.model] + (self.a.probe_models.split(",") if self.a.probe_models else PROBE_MODELS):
            if m and m not in probes:
                probes.append(m)
        jobs = [(O, m, None) for m in probes] + [(R, m, sysv) for m in probes]
        rs = par(lambda x: self.replay(*x), jobs, 8)
        read = lambda x: {"keep": "读", "prefix_mismatch": "读", "model_mismatch": "丢"}.get(x["outcome"], "错")
        po, pr = [read(x) for x in rs[:len(probes)]], [read(x) for x in rs[len(probes):]]
        usable = [i for i in range(len(probes)) if po[i] != "错"]
        table = "，".join(f"{probes[i]} 官方{po[i]}/中转{pr[i]}" for i in range(len(probes)))
        details.append(f"跨模型回放（读 = 能读，丢 = 模型不匹配被丢弃）：{table}")
        self.raw["signature"].update(relay_replay=B, tamper_relay=D2, injected_system=sysv,
                                     probes={probes[i]: {"official": rs[i], "relay": rs[len(probes) + i]} for i in range(len(probes))})
        same = all(po[i] == pr[i] for i in usable)
        informative = len({po[i] for i in usable}) > 1
        if same and informative:
            mark = WARN if sysv is not None or B["outcome"] == "prefix_mismatch" else OK
            head = f"签名真实，是 {self.off.model} 生成的" + ("，但请求被加了东西" if mark == WARN else "，请求没被改动")
            self.add("signature", mark, head, details)
        elif same:
            self.add("signature", UNK, "签名真实，但探针模型都读（或都不读）这个块，分辨不出具体模型；换 --probe-models 再试", details)
        else:
            self.add("signature", BAD, f"签名真实，但读取规律和官方 {self.off.model} 的块不一样：中转背后是别的模型", details)

    def check_system_merge(self):
        """With our own system prompt, what reaches the model? Only meaningful once the injection is known."""
        if self.injected is None:
            return
        c = self.injected if isinstance(self.injected, str) else self.injected[0]["text"]
        r = self.gen(self.relay, system=OUR_SYSTEM)
        if r["status"] != 200 or not signed_block(r["data"].get("content")):
            return
        R = r["data"]["content"]
        forms = {
            "我们的 system 原样保留，前面多插了一个块": [{"type": "text", "text": c}, {"type": "text", "text": OUR_SYSTEM}],
            "我们的 system 原样保留，后面多加了一个块": [{"type": "text", "text": OUR_SYSTEM}, {"type": "text", "text": c}],
            "和我们的 system 拼成一段（换行连接）": c + "\n" + OUR_SYSTEM,
            "和我们的 system 拼成一段（空行连接）": c + "\n\n" + OUR_SYSTEM,
            "我们的 system 被整个替换掉了": c,
        }
        for label, form in forms.items():
            if self.replay(R, system=form)["outcome"] == "keep":
                for v in self.verdicts:
                    if v[0] == "signature":
                        v[3].append(f"自带 system 时：{label}")
                self.raw["system_merge"] = label
                return
        self.raw["system_merge"] = "未识别"

    # ---- 3 effort

    def effort_job(self, x):
        lane, eff, i = x
        if lane.protocol == "anthropic":
            res = anthropic_post(lane, "/v1/messages", self.a_body(
                lane, EFFORT_Q, max_tokens=32000, thinking={"type": "adaptive"}, output_config={"effort": eff}))
            u = res["data"].get("usage") or {}
            think = (u.get("output_tokens_details") or {}).get("thinking_tokens")
            text = a_text(res["data"])
        else:
            res = openai_chat(lane, {"model": lane.model, "reasoning_effort": eff,
                                     "messages": [{"role": "user", "content": EFFORT_Q}]})
            u = res["data"].get("usage") or {}
            think = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
            text = res["data"].get("content") or ""
        return {"lane": lane.name, "effort": eff, "i": i, "status": res["status"], "think": think,
                "correct": EFFORT_A in text.replace("*", ""), "latency_s": res["latency_s"],
                "error": err_text(res)[:200] if res["status"] != 200 else None}

    def check_effort(self):
        n = self.a.effort_runs
        jobs = [(lane, eff, i) for lane in (self.off, self.relay) for eff in ("low", "high") for i in range(n)]
        rows = par(self.effort_job, jobs, 8)
        self.raw["effort"] = rows
        errs = [x for x in rows if x["status"] != 200]
        if any(x["lane"] == "official" for x in errs):
            self.add("effort", UNK, f"官方不接受这组档位参数，跳过：{errs[0]['error']}")
            return
        if errs:
            self.add("effort", WARN, f"中转拒绝了档位参数：{errs[0]['error']}")
            return

        def get(lane, eff):
            return [x["think"] for x in rows if x["lane"] == lane and x["effort"] == eff and x["think"] is not None]

        def acc(lane, eff):
            xs = [x for x in rows if x["lane"] == lane and x["effort"] == eff]
            return f"{sum(x['correct'] for x in xs)}/{len(xs)}"

        o_lo, o_hi, r_lo, r_hi = get("official", "low"), get("official", "high"), get("relay", "low"), get("relay", "high")
        details = [f"思考 token（同一道题，各 {n} 次）：官方 low {o_lo} / high {o_hi}；中转 low {r_lo} / high {r_hi}",
                   f"答对率：官方 low {acc('official', 'low')} / high {acc('official', 'high')}；"
                   f"中转 low {acc('relay', 'low')} / high {acc('relay', 'high')}"]
        if not o_hi or not o_lo:
            self.add("effort", UNK, "官方 usage 不回传思考 token，比不了", details)
            return
        if not r_hi or not r_lo:
            self.add("effort", WARN, "官方回传思考 token，中转不回传：无法核对，也可能被抹掉", details)
            return
        mo, mr = statistics.median(o_hi), statistics.median(r_hi)
        if mo > 0 and mr < 0.5 * mo:
            self.add("effort", WARN, f"high 档的思考量只有官方的 {mr / mo:.0%}：档位可能被调低了", details)
        elif statistics.median(o_lo) > 0 and statistics.median(r_lo) > 2 * statistics.median(o_lo) and mr <= 1.2 * mo:
            self.add("effort", WARN, "low 档思考量明显高于官方：中转可能把档位统一改写了", details)
        else:
            self.add("effort", OK, "两档的思考量和官方在同一区间，档位没被动", details)

    # ---- report

    def report(self):
        names = {"inject": "注入", "signature": "签名回放", "effort": "思考档位", "meta": "元数据"}
        L = [f"# api-relay-verify 报告", "",
             f"- 中转：`{self.relay.base}` · 模型 `{self.relay.model}` · 协议 {self.relay.protocol}",
             f"- 对照：`{self.off.base}` · 模型 `{self.off.model}`",
             f"- 时间：{self.raw['started']}", "", "## 结论", ""]
        for check, mark, line, _ in self.verdicts:
            L.append(f"- {mark} **{names.get(check, check)}**：{line}")
        L += ["", "## 明细", ""]
        for check, mark, line, details in self.verdicts:
            L.append(f"### {mark} {names.get(check, check)}")
            L.append("")
            L += [f"- {d}" for d in details] or ["- （无）"]
            L.append("")
        L += ["## 读法", "",
              "- 这是一次快照。中转可以随时换上游，注入也可能是间歇性的；要下结论就隔几小时多跑几轮。",
              "- 签名回放只覆盖模型、system、tools、对话内容；`max_tokens`、档位等参数靠「思考档位」一项单独查。",
              "- 没有签名的模型（OpenAI 兼容通道）查不了「背后换没换模型」，需要行为指纹类工具。"]
        return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description="拿官方直连当对照，查 API 中转有没有注水。key 只从环境变量读。")
    ap.add_argument("--relay-base", required=True, help="中转地址。Anthropic 协议给站点根（带不带 /v1 都行）；OpenAI 协议给到 /v1 这一级")
    ap.add_argument("--relay-key-env", required=True, help="存中转 key 的环境变量名")
    ap.add_argument("--model", required=True, help="要验的模型 id")
    ap.add_argument("--relay-model", help="中转上的模型名（和官方不同时用）")
    ap.add_argument("--protocol", choices=["auto", "anthropic", "openai"], default="auto",
                    help="auto：claude-* 走 Anthropic 协议，其余走 OpenAI 兼容")
    ap.add_argument("--official-base", help="对照地址。默认 Anthropic 官方 / OpenAI 官方")
    ap.add_argument("--official-key-env", help="对照 key 的环境变量名。默认 ANTHROPIC_API_KEY / OPENAI_API_KEY")
    ap.add_argument("--env-file", action="append", help="从 KEY=VALUE 文件加载环境变量，可重复")
    ap.add_argument("--checks", default="inject,signature,effort,meta", help="要跑的检查，逗号分隔")
    ap.add_argument("--effort-runs", type=int, default=2, help="档位检查每档跑几次（默认 2）")
    ap.add_argument("--candidate", action="append", help="额外猜测的注入原文，可重复")
    ap.add_argument("--probe-models", help="跨模型回放用的模型，逗号分隔（默认一组当代 Claude 模型）")
    ap.add_argument("--out", help="报告目录（默认 ~/.local/share/api-relay-verify/<时间>）")
    a = ap.parse_args()

    proto = a.protocol if a.protocol != "auto" else ("anthropic" if a.model.startswith("claude") else "openai")
    env = load_env_files(a.env_file)
    off_base = a.official_base or ("https://api.anthropic.com" if proto == "anthropic" else "https://api.openai.com/v1")
    off_env = a.official_key_env or ("ANTHROPIC_API_KEY" if proto == "anthropic" else "OPENAI_API_KEY")
    relay = Lane("relay", a.relay_base, need_key(a.relay_key_env, env), a.relay_model or a.model, proto, bearer=True)
    official = Lane("official", off_base, need_key(off_env, env), a.model, proto, bearer=False)
    checks = [c.strip() for c in a.checks.split(",") if c.strip()]
    if proto != "anthropic" and "signature" in checks:
        checks.remove("signature")
        print("OpenAI 兼容协议没有思考签名，跳过 signature。", file=sys.stderr)

    au = Audit(a, relay, official)
    print(f"api-relay-verify：{relay.model} @ {relay.base} vs 官方 {official.base}，检查 {checks}", file=sys.stderr)
    if "inject" in checks or "meta" in checks:
        au.run_tiny()
    if "inject" in checks:
        au.check_inject()
    if "signature" in checks:
        au.check_signature()
        au.check_system_merge()
    if "effort" in checks:
        au.check_effort()
    if "meta" in checks:
        au.check_meta()

    out = os.path.expanduser(a.out or os.path.join("~/.local/share/api-relay-verify",
                                                   datetime.datetime.now().strftime("%Y%m%d-%H%M%S")))
    os.makedirs(out, exist_ok=True)
    au.raw["verdicts"] = [{"check": c, "mark": m, "line": l, "details": d} for c, m, l, d in au.verdicts]
    with open(os.path.join(out, "raw.json"), "w") as f:
        json.dump(au.raw, f, ensure_ascii=False, indent=1)
    md = au.report()
    with open(os.path.join(out, "report.md"), "w") as f:
        f.write(md)
    print(md)
    print(f"报告：{os.path.join(out, 'report.md')}\n原始数据：{os.path.join(out, 'raw.json')}", file=sys.stderr)


if __name__ == "__main__":
    main()
