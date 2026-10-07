#!/usr/bin/env python3
"""edit-drift: multi-turn image-edit drift evaluation and side-by-side video.

N image-edit models get the same source image and the same prompt list; every model edits ITS OWN previous output
for K steps. `score` measures background Drift against the original; `render` draws an N-column video.

  edit-drift run    <chains.json> --budget 20 [--chains a,b] [--models m1,m2] [--max-steps K] [--dry-run]
  edit-drift score  <chains.json> [--patches patches.json]
  edit-drift render <chains.json> [--models m1,m2] [--sec 0.25] [--only chain] [--out-dir DIR]
  edit-drift models                      # list adapters

All outputs live next to chains.json (the work dir):
  inputs/<image>.png               square-cropped, resized source (run only)
  out/<chain>/<model>/NN.png       00 = source, NN = step NN (lossless; analysis always reads .png)
  log.jsonl                        one row per API attempt: request params, latency, est. cost, status, error
  manifest.json                    per model: endpoint, channel, resolution, quality, output format, dates, chain status
  patches.json / drift.json        background patches per image, drift series per <chain>-<model>
  video/<chain>.mp4, video/all.mp4

Secrets (FAL_KEY, GEMINI_API_KEY, GEMINI_BASE_URL) come from the environment or from the dotenv file named by
$EDIT_DRIFT_ENV_FILE, and are never written anywhere. ffmpeg comes from $FFMPEG or PATH. Python stdlib + numpy + PIL; HTTP via urllib.
"""
import argparse, base64, datetime, hashlib, io, json, os, pathlib, random, shutil, ssl, subprocess, sys, threading, time
import urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ENV_FILE = os.environ.get("EDIT_DRIFT_ENV_FILE", "")
CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem") if os.path.exists("/etc/ssl/cert.pem") else ssl.create_default_context()
FF = os.environ.get("FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
LOCK = threading.Lock()
UPLOAD = threading.Semaphore(int(os.environ.get("EDIT_DRIFT_UPLOADS", "8")))  # local uplink is the bottleneck
DEFAULT_SUFFIX = " Keep everything else in the image exactly the same."


# ----------------------------------------------------------------------------------------------------------- secrets
def secret(name):
    if os.environ.get(name):
        return os.environ[name]
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            line = line.strip()
            if line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == name:
                    return v.strip().strip('"').strip("'")
    raise SystemExit(f"{name} missing (env or {ENV_FILE})")


# ----------------------------------------------------------------------------------------------------------- http
def http(url, hdr, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        timeout = max(timeout, 600)
    r = urllib.request.Request(url, data=data, headers=hdr, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(r, timeout=timeout, context=CTX) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:2000]


def is_blocked(text):
    t = str(text or "")
    return "content_policy_violation" in t or "flagged by a content checker" in t


class Result:
    """raw: output bytes or None; status: ok | blocked | failed; info: extra log fields."""

    def __init__(self, status, raw=None, error=None, cost=None, **info):
        self.status, self.raw, self.error, self.cost, self.info = status, raw, error, cost, info


def fal_queue(endpoint, body):
    hdr = {"Authorization": f"Key {secret('FAL_KEY')}", "Content-Type": "application/json"}
    err = None
    for att in range(1, 7):
        try:
            with UPLOAD:
                st, sub = http(endpoint, hdr, body)
            if st >= 300:
                if is_blocked(sub):
                    return Result("blocked", error=f"submit {st}: {str(sub)[:300]}")
                err = f"submit {st}: {str(sub)[:300]}"
                if st in (429, 500, 502, 503, 504):
                    time.sleep(min(120, 5 * 2 ** att) * (0.5 + random.random())); continue
                return Result("failed", error=err)
            t0 = time.time()
            while time.time() - t0 < 1500:
                s, j = http(sub["status_url"], hdr)
                if isinstance(j, dict) and j.get("status") == "COMPLETED":
                    break
                time.sleep(3)
            else:
                err = "poll timeout"; continue
            s, res = http(sub["response_url"], hdr, timeout=300)
            if s >= 300 or not isinstance(res, dict) or not res.get("images"):
                if is_blocked(res):
                    return Result("blocked", error=f"result {s}: {str(res)[:300]}", request_id=sub.get("request_id"))
                err = f"result {s}: {str(res)[:300]}"
                if s >= 500:
                    time.sleep(10 * att); continue
                return Result("failed", error=err, request_id=sub.get("request_id"))
            url = res["images"][0]["url"]
            raw = base64.b64decode(url.split(",", 1)[1]) if url.startswith("data:") else None
            for k in range(5):
                if raw is not None:
                    break
                try:
                    with urllib.request.urlopen(url, timeout=600, context=CTX) as r:
                        raw = r.read()
                except Exception:
                    time.sleep(5 * (k + 1))
            if raw is None:
                err = "download failed"; continue
            return Result("ok", raw, request_id=sub.get("request_id"), seed=res.get("seed"))
        except Exception as e:  # network errors must not kill the chain thread
            err = f"{type(e).__name__}: {e}"[:300]; time.sleep(10 * att)
    return Result("failed", error=err or "exhausted retries")


def data_uri(raw, mime):
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


# ----------------------------------------------------------------------------------------------------------- adapters
# Each adapter: spec (for manifest / labels) + call(prompt, raw_prev, mime_prev, size) -> (Result, request params)
# Add a model: write one function, register it in ADAPTERS. est_cost is the per-step budget pre-charge (USD).

def _fal_adapter(endpoint, body_fn):
    def call(prompt, raw, mime, size):
        body = body_fn(prompt, data_uri(raw, mime), size)
        res = fal_queue(endpoint, body)
        return res, body
    return call


def flux3_body(prompt, uri, size):
    return {"prompt": prompt, "image_urls": [uri], "resolution": "1k", "aspect_ratio": "auto", "output_format": "png",
            "enable_prompt_expansion": False}


def ideogram45_body(prompt, uri, size):
    return {"prompt": prompt, "image_url": uri, "edit_precision": "high", "quality": "medium"}


def gpt25_body(prompt, uri, size):
    return {"prompt": prompt, "image_urls": [uri], "quality": "medium", "image_size": {"width": size, "height": size},
            "output_format": "png", "num_images": 1}


NB_MODEL = "gemini-nano-banana-2.1"
NB_PRICE_IN, NB_PRICE_TXT_OUT, NB_PRICE_IMG_OUT = 1.5e-6, 7.5e-6, 30e-6  # USD/token, ai.google.dev pricing 2026-10-07
NB_BLOCK_FINISH = {"SAFETY", "IMAGE_SAFETY", "PROHIBITED_CONTENT", "IMAGE_PROHIBITED_CONTENT", "BLOCKLIST", "SPII"}


def nb21_cost(u):
    if not u:
        return None
    out_img = sum(x.get("tokenCount", 0) for x in u.get("candidatesTokensDetails", []) if x.get("modality") == "IMAGE")
    out_txt = u.get("candidatesTokenCount", 0) - out_img + u.get("thoughtsTokenCount", 0)
    return u.get("promptTokenCount", 0) * NB_PRICE_IN + out_txt * NB_PRICE_TXT_OUT + out_img * NB_PRICE_IMG_OUT


def nb21_call(prompt, raw, mime, size):
    params = {"model": NB_MODEL, "generationConfig": {"responseModalities": ["IMAGE"],
                                                      "imageConfig": {"aspectRatio": "1:1", "imageSize": "1K"}}}
    body = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(raw).decode()}}]}],
            "generationConfig": params["generationConfig"]}
    url = f"{secret('GEMINI_BASE_URL').rstrip('/')}/models/{NB_MODEL}:generateContent"
    hdr = {"Content-Type": "application/json", "x-goog-api-key": secret("GEMINI_API_KEY")}
    err = None
    for att in range(1, 7):
        try:
            st, d = http(url, hdr, body, timeout=600)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:300]; time.sleep(10 * att); continue
        if st >= 300:
            err = f"http {st}: {str(d)[:300]}"
            if st in (429, 500, 502, 503, 504):
                time.sleep(min(120, 5 * 2 ** att)); continue
            return Result("failed", error=err), params
        cand = (d.get("candidates") or [{}])[0]
        for p in (cand.get("content") or {}).get("parts", []):
            if "inlineData" in p:
                u = d.get("usageMetadata")
                return Result("ok", base64.b64decode(p["inlineData"]["data"]), cost=nb21_cost(u), usage=u,
                              mime=p["inlineData"]["mimeType"], finish=cand.get("finishReason")), params
        fb = d.get("promptFeedback") or {}
        err = f"no image: finish={cand.get('finishReason')} block={fb}"[:300]
        if fb.get("blockReason") or cand.get("finishReason") in NB_BLOCK_FINISH:
            return Result("blocked", error=err, cost=nb21_cost(d.get("usageMetadata"))), params
        time.sleep(5 * att)
    return Result("failed", error=err or "exhausted retries"), params


ADAPTERS = {
    "flux3": dict(label="FLUX 3", channel="fal", endpoint="https://queue.fal.run/blackforestlabs/flux-3/edit-image",
                  resolution="1k", quality="n/a (no quality knob)", output_format="png", est_cost=0.096,
                  params="resolution=1k, aspect_ratio=auto, enable_prompt_expansion=false",
                  call=_fal_adapter("https://queue.fal.run/blackforestlabs/flux-3/edit-image", flux3_body)),
    "ideogram45": dict(label="Ideogram 4.5", channel="fal", endpoint="https://queue.fal.run/ideogram/v4.5/edit",
                       resolution="input size", quality="medium", output_format="png", est_cost=0.06,
                       params="edit_precision=high, quality=medium",
                       call=_fal_adapter("https://queue.fal.run/ideogram/v4.5/edit", ideogram45_body)),
    "gpt25-sunburst": dict(label="GPT Image 2.5", channel="fal", endpoint="https://queue.fal.run/openai/gpt-image-2.5/sunburst/edit",
                           resolution="1024x1024", quality="medium", output_format="png", est_cost=0.025,
                           params="quality=medium, image_size=1024x1024, output_format=png",
                           call=_fal_adapter("https://queue.fal.run/openai/gpt-image-2.5/sunburst/edit", gpt25_body)),
    "nb21": dict(label="Nano Banana 2.1", channel="Gemini API (official direct)",
                 endpoint=f"<GEMINI_BASE_URL>/models/{NB_MODEL}:generateContent", resolution="1K, 1:1",
                 quality="n/a (no quality knob)", output_format="jpeg (API returns JPEG; NN.png is a lossless decode)",
                 est_cost=0.04, params="imageSize=1K, aspectRatio=1:1, default thinking", call=nb21_call),
}


# ----------------------------------------------------------------------------------------------------------- config
class Cfg:
    def __init__(self, path):
        self.path = pathlib.Path(path).resolve(); self.wd = self.path.parent
        c = json.loads(self.path.read_text())
        self.raw = c
        self.size = int(c.get("size", 1024))
        self.suffix = c.get("suffix", DEFAULT_SUFFIX)
        self.models = c["models"]
        self.labels = c.get("labels", {})
        self.images = {k: self._p(v) for k, v in c.get("images", {}).items()}
        self.chains = c["chains"]
        self.sources = c.get("sources", {})
        for m in self.models:
            if m not in ADAPTERS and m not in self.sources:
                raise SystemExit(f"unknown model {m!r}: no adapter and no sources entry")
        for ch in self.chains:
            if not ch.get("id") or not ch.get("image") or not ch.get("prompts"):
                raise SystemExit(f"chain needs id, image, prompts: {ch.get('id')}")

    def _p(self, v):
        p = pathlib.Path(v)
        return p if p.is_absolute() else (self.wd / p)

    def label(self, m):
        return self.labels.get(m) or (ADAPTERS[m]["label"] if m in ADAPTERS else m)

    def fmt(self, tmpl, ch):
        return tmpl.format(chain=ch["id"], image=ch["image"])

    def dir(self, ch, m):
        if m in self.sources:
            return self._p(self.fmt(self.sources[m]["dir"], ch))
        return self.wd / "out" / ch["id"] / m

    def frames(self, ch, m):
        d = self.dir(ch, m); out = []
        for k in range(len(ch["prompts"]) + 1):
            p = d / f"{k:02d}.png"
            if not p.exists():
                break
            out.append(p)
        return out

    def log_rows(self, ch, m):
        rows = []
        lp = self.wd / "log.jsonl"
        if lp.exists():
            rows += [r for r in map(json.loads, open(lp)) if r.get("chain") == ch["id"] and r.get("model") == m]
        s = self.sources.get(m)
        if s and s.get("log"):
            lc = self.fmt(s.get("log_chain", "{chain}"), ch)
            rows += [r for r in map(json.loads, open(self._p(s["log"]))) if r.get("chain") == lc]
        return rows

    def status(self, ch, m):
        """(status, last_ok_step, stop_step): complete | blocked | failed | incomplete | missing."""
        n = len(ch["prompts"]); f = self.frames(ch, m); last = len(f) - 1
        if last < 0:
            return "missing", -1, None
        if last >= n:
            return "complete", n, None
        nxt = [r for r in self.log_rows(ch, m) if r.get("step") == last + 1]
        if any(r.get("status") == "blocked" or is_blocked(r.get("error")) for r in nxt):
            return "blocked", last, last + 1
        if any(r.get("status") == "failed" for r in nxt):
            return "failed", last, last + 1
        return "incomplete", last, last + 1


# ----------------------------------------------------------------------------------------------------------- run
def prepare_input(src, dst, size):
    im = Image.open(src).convert("RGB"); w, h = im.size; s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((size, size), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True); im.save(dst)


def redact(params):
    """Request params for the log: image payloads replaced by length + sha256."""
    def r(v):
        if isinstance(v, str) and (v.startswith("data:") or len(v) > 2000):
            return f"<{len(v)} chars sha256={hashlib.sha256(v.encode()).hexdigest()[:16]}>"
        if isinstance(v, dict):
            return {k: r(x) for k, x in v.items()}
        if isinstance(v, list):
            return [r(x) for x in v]
        return v
    return r(params)


def log_row(wd, row):
    row["ts"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    with LOCK, open(wd / "log.jsonl", "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_pair(cfg, ch, m, spent, budget, a):
    ad = ADAPTERS[m]; od = cfg.dir(ch, m); od.mkdir(parents=True, exist_ok=True)
    if not (od / "00.png").exists():
        shutil.copy(cfg.wd / "inputs" / f"{ch['image']}.png", od / "00.png")
    prompts = ch["prompts"][: a.max_steps] if a.max_steps else ch["prompts"]
    rows = cfg.log_rows(ch, m)
    fails, k = 0, 1
    while k <= len(prompts):
        if (od / f"{k:02d}.png").exists():
            k += 1; continue
        nblock = sum(1 for r in rows if r.get("step") == k and r.get("status") == "blocked")
        if nblock > a.blocked_retries:
            print(f"[{m}] {ch['id']} blocked at step {k} ({nblock}x), stop", flush=True); return
        prev = next((p for p in (od / f"{k - 1:02d}.jpg", od / f"{k - 1:02d}.webp", od / f"{k - 1:02d}.png")
                     if p.exists() and (m == "nb21" or p.suffix == ".png")), None)
        mime = {".jpg": "image/jpeg", ".webp": "image/webp"}.get(prev.suffix, "image/png")
        est = ad["est_cost"]
        with LOCK:
            if spent[0] + est > budget:
                print(f"[{m}] budget stop {ch['id']} at {k} (spent ${spent[0]:.2f})", flush=True); return
            spent[0] += est
        t0 = time.time(); res, params = ad["call"](prompts[k - 1], prev.read_bytes(), mime, cfg.size)
        cost = res.cost if res.cost is not None else (est if res.status == "ok" else 0.0)
        row = {"chain": ch["id"], "model": m, "step": k, "prompt": prompts[k - 1], "channel": ad["channel"],
               "endpoint": ad["endpoint"], "params": redact(params), "input": prev.name,
               "latency_s": round(time.time() - t0, 1), "est_cost": round(cost, 5), "status": res.status}
        with LOCK:
            spent[0] += cost - est
        if res.status != "ok":
            row["error"] = res.error; row.update({k_: v for k_, v in res.info.items() if v is not None})
            log_row(cfg.wd, row); rows.append(row)
            print(f"[{m}] {ch['id']} step {k} {res.status.upper()} {res.error[:120] if res.error else ''}", flush=True)
            if res.status == "blocked":
                time.sleep(5); continue  # re-checked against --blocked-retries at loop top
            fails += 1
            if fails > 3:
                return
            time.sleep(30); continue
        raw = res.raw
        ext = ".png" if raw[:4] == b"\x89PNG" else ".webp" if raw[8:12] == b"WEBP" else ".jpg"
        if ext != ".png":
            (od / f"{k:02d}{ext}").write_bytes(raw)
            Image.open(io.BytesIO(raw)).convert("RGB").save(od / f"{k:02d}.png")
        else:
            (od / f"{k:02d}.png").write_bytes(raw)
        with Image.open(io.BytesIO(raw)) as im:
            row.update(out_format=im.format, out_size=list(im.size))
        row.update({k_: v for k_, v in res.info.items() if v is not None})
        row["out_sha256"] = hashlib.sha256(raw).hexdigest()
        log_row(cfg.wd, row); rows.append(row)
        print(f"[{m}] {ch['id']} {k}/{len(prompts)} {row['latency_s']}s spent ${spent[0]:.2f}", flush=True)
        k += 1


def cmd_run(cfg, a):
    models = [m for m in (a.models.split(",") if a.models else cfg.models) if m not in cfg.sources]
    chains = [c for c in cfg.chains if not a.chains or c["id"] in a.chains.split(",")]
    for m in models:
        if m not in ADAPTERS:
            raise SystemExit(f"no adapter for {m}")
    pairs = [(c, m) for c in chains for m in models]
    steps = sum(min(len(c["prompts"]), a.max_steps or 10 ** 9) for c, _ in pairs)
    est = sum(ADAPTERS[m]["est_cost"] * min(len(c["prompts"]), a.max_steps or 10 ** 9) for c, m in pairs)
    print(f"[run] {len(pairs)} chains x models, <= {steps} steps, list-price estimate ${est:.2f}, budget ${a.budget:.2f}")
    if a.dry_run:
        for c, m in pairs:
            print(f"  {c['id']:24s} {m:16s} {ADAPTERS[m]['channel']:30s} {ADAPTERS[m]['params']}")
        return
    for img in {c["image"] for c in chains}:
        dst = cfg.wd / "inputs" / f"{img}.png"
        if not dst.exists():
            prepare_input(cfg.images[img], dst, cfg.size)
    spent = [0.0]
    if (cfg.wd / "log.jsonl").exists():
        spent[0] = sum(json.loads(l).get("est_cost", 0) or 0 for l in open(cfg.wd / "log.jsonl"))
    with ThreadPoolExecutor(a.workers or max(1, len(pairs))) as ex:
        list(ex.map(lambda p: run_pair(cfg, p[0], p[1], spent, a.budget, a), pairs))
    write_manifest(cfg)
    print(f"[run] done, est. spent ${spent[0]:.2f}; manifest {cfg.wd / 'manifest.json'}")


# ----------------------------------------------------------------------------------------------------------- manifest
def write_manifest(cfg):
    lp = cfg.wd / "log.jsonl"
    rows = list(map(json.loads, open(lp))) if lp.exists() else []
    out = {"generated": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "size": cfg.size,
           "prompt_suffix": cfg.suffix, "repeats": "1 run per chain, no seed repeats", "models": {}}
    for m in cfg.models:
        ad = ADAPTERS.get(m, {})
        src = cfg.sources.get(m)
        e = {k: ad.get(k) for k in ("label", "channel", "endpoint", "resolution", "quality", "output_format", "params")}
        e["label"] = cfg.label(m)
        mine = [r for r in rows if r.get("model") == m]
        if src:
            e.update({k: v for k, v in src.items() if k in ("channel", "endpoint", "resolution", "quality", "output_format", "params")})
            e["imported_from"] = src["dir"]
            dates = set()
            for ch in cfg.chains:
                f = cfg.frames(ch, m)
                if len(f) > 1:
                    dates.add(datetime.date.fromtimestamp(f[1].stat().st_mtime).isoformat())
            e["dates"] = sorted(dates) if not src.get("date") else [src["date"]]
        else:
            e["dates"] = sorted({r["ts"][:10] for r in mine if r.get("ts")})
            e["observed_output_formats"] = sorted({r["out_format"] for r in mine if r.get("out_format")})
            e["est_cost_usd"] = round(sum(r.get("est_cost") or 0 for r in mine), 3)
        e["chains"] = {}
        for ch in cfg.chains:
            st, last, stop = cfg.status(ch, m)
            e["chains"][ch["id"]] = {"status": st, "steps_ok": max(last, 0), "of": len(ch["prompts"]),
                                     **({"stopped_at_step": stop} if stop else {})}
        out["models"][m] = e
    (cfg.wd / "manifest.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))


# ----------------------------------------------------------------------------------------------------------- score
def box_mean(x, k):
    """Mean over a k x k window (same size, edge-padded)."""
    p = k // 2
    xp = np.pad(x.astype(np.float64), ((p, k - 1 - p), (p, k - 1 - p)), mode="edge")
    c = np.cumsum(np.cumsum(np.pad(xp, ((1, 0), (1, 0))), 0), 1)
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def dist_to(m, maxd=200):
    """Chebyshev distance from each pixel to the nearest True pixel of m (capped)."""
    d = np.full(m.shape, maxd, np.int32); cur = m.copy(); d[cur] = 0
    for r in range(1, maxd):
        nxt = box_mean(cur.astype(np.float64), 3) > 1e-9; d[nxt & ~cur] = r; cur = nxt
        if cur.all():
            break
    return d


def rgb(p, size=None):
    im = Image.open(p).convert("RGB")
    if size and im.size != size:
        im = im.resize(size, Image.LANCZOS)
    return np.asarray(im).astype(np.int16)


def pick_patches(cfg, img):
    """3 background patches (96 px at 1024) far from the union of every model's step-1 edit region on this image."""
    U = None
    for ch in [c for c in cfg.chains if c["image"] == img]:
        for m in cfg.models:
            f = cfg.frames(ch, m)
            if len(f) < 2:
                continue
            x0 = rgb(f[0]); x1 = rgb(f[1], (x0.shape[1], x0.shape[0]))
            E = np.abs(x1 - x0).max(-1) > 30
            E = box_mean(E.astype(float), 9) > 0.5
            if E.mean() > 0.6:  # whole-frame redraw on step 1 carries no location information
                continue
            U = E if U is None else (U | E)
    if U is None:
        raise SystemExit(f"{img}: no model has a localized step-1 edit; pass --patches")
    s = U.shape[1] / 1024
    patch, gap, margin, stride = round(96 * s), 360 * s, 40 * s, max(1, round(16 * s))
    d = dist_to(U, round(400 * s)).astype(float)
    score = box_mean(d, patch)
    h, w = d.shape; half = patch // 2
    cands = sorted(((score[y, x], y, x) for y in range(half, h - half, stride) for x in range(half, w - half, stride)), reverse=True)
    out = []
    for _, y, x in cands:
        if d[y - half:y + half, x - half:x + half].min() < margin:
            continue
        if all(((y - yy) ** 2 + (x - xx) ** 2) ** 0.5 >= gap for yy, xx in out):
            out.append((y, x))
        if len(out) == 3:
            break
    return [[int(x - half), int(y - half), int(x + half), int(y + half)] for y, x in out]


def drift_series(frames, boxes):
    """Legacy reading: mean |x_k - x_0| over the 3 patches (0-255). Kept in drift_mae.json for reference."""
    x0 = rgb(frames[0]); sz = (x0.shape[1], x0.shape[0]); out = []
    for p in frames[1:]:
        xk = rgb(p, sz)
        out.append(round(float(np.mean([np.abs(xk[y0:y1, x0_:x1] - x0[y0:y1, x0_:x1]).mean() for x0_, y0, x1, y1 in boxes])), 1))
    return out


BBOX_MODEL = os.environ.get("EDIT_DRIFT_BBOX_MODEL", "gemini-3.8-flash")
BBOX_PAD = 48  # px at 1024: spill-over allowance around the target box
BBOX_Q = ("An image-editing instruction will be applied to this photo:\n\"{instr}\"\n"
          "Return the tight bounding box of the region this instruction is allowed to change (only the target object, "
          "e.g. that person's jacket or hair), as JSON {{\"box_2d\": [ymin, xmin, ymax, xmax], \"label\": \"...\"}} "
          "with coordinates normalized to 0-1000.")


def gemini_bbox(png_path, instr):
    """Ask a Gemini VLM for the target region of the edit on the ORIGINAL image. Returns [x0, y0, x1, y1] in 0-1000."""
    raw = pathlib.Path(png_path).read_bytes()
    body = {"contents": [{"parts": [{"inline_data": {"mime_type": "image/png", "data": base64.b64encode(raw).decode()}},
                                    {"text": BBOX_Q.format(instr=instr)}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    url = f"{secret('GEMINI_BASE_URL').rstrip('/')}/models/{BBOX_MODEL}:generateContent"
    hdr = {"Content-Type": "application/json", "x-goog-api-key": secret("GEMINI_API_KEY")}
    err = None
    for att in range(1, 5):
        try:
            st, d = http(url, hdr, body, timeout=300)
            if st < 300:
                j = json.loads(d["candidates"][0]["content"]["parts"][-1]["text"])
                j = j[0] if isinstance(j, list) else j
                y0, x0, y1, x1 = j["box_2d"]
                return [int(x0), int(y0), int(x1), int(y1)], j.get("label", "")
            err = f"{st}: {str(d)[:200]}"
        except Exception as e:
            err = f"{type(e).__name__}: {e}"[:200]
        time.sleep(5 * att)
    raise SystemExit(f"bbox failed for {png_path}: {err}")


def chain_bboxes(cfg):
    """Target box per chain (0-1000, x0 y0 x1 y1): chains.json "bboxes" > cached bboxes.json > Gemini on the original."""
    path = cfg.wd / "bboxes.json"
    cache = json.loads(path.read_text()) if path.exists() else {}
    cache.update(cfg.raw.get("bboxes", {}))
    for ch in cfg.chains:
        if ch["id"] in cache:
            continue
        src = next((cfg.frames(ch, m)[0] for m in cfg.models if cfg.frames(ch, m)), None)
        instr = ch["prompts"][0].replace(cfg.suffix, "").strip()
        box, label = gemini_bbox(src, instr)
        cache[ch["id"]] = {"box": box, "label": label, "instruction": instr, "model": BBOX_MODEL}
        print(f"[bbox] {ch['id']}: {box} {label}", flush=True)
    path.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    return {k: (v["box"] if isinstance(v, dict) else v) for k, v in cache.items()}


def outside_mask(shape, box, pad=BBOX_PAD):
    """True outside the padded target box: everything the instruction did not ask to change (incl. other people)."""
    h, w = shape[:2]; p = round(pad * w / 1024)
    x0, y0, x1, y1 = box
    m = np.ones((h, w), bool)
    m[max(0, int(y0 * h / 1000) - p):min(h, int(y1 * h / 1000) + p), max(0, int(x0 * w / 1000) - p):min(w, int(x1 * w / 1000) + p)] = False
    return m


def grad_mag(x):
    g = x.astype(np.float64) @ np.array([0.299, 0.587, 0.114])
    gx = np.zeros_like(g); gy = np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]; gy[1:-1] = g[2:] - g[:-2]
    return np.hypot(gx, gy)


def texture_series(frames, mask):
    """背景漂移 (default score): 100 * (1 - corr(|grad x_k|, |grad x_0|)) outside the target bbox, clipped to 0-100.
    0 = edges and textures identical to the original; ~100 = none of the original detail is left."""
    x0 = rgb(frames[0]); sz = (x0.shape[1], x0.shape[0]); G0 = grad_mag(x0)[mask]; out = []
    for p in frames[1:]:
        Gk = grad_mag(rgb(p, sz))[mask]
        if G0.std() < 1e-9 or Gk.std() < 1e-9:
            c = 1.0 if np.allclose(G0, Gk) else 0.0
        else:
            c = float(np.corrcoef(G0, Gk)[0, 1])
        out.append(round(min(100.0, max(0.0, 100 * (1 - c))), 1))
    return out


def cmd_score(cfg, a):
    if a.patches:
        patches = json.loads(pathlib.Path(a.patches).read_text())
    elif cfg.raw.get("patches"):
        patches = cfg.raw["patches"]
    else:
        patches = {}
    for img in dict.fromkeys(c["image"] for c in cfg.chains):
        if img not in patches:
            patches[img] = pick_patches(cfg, img)
    (cfg.wd / "patches.json").write_text(json.dumps(patches, indent=1))
    boxes, masks = chain_bboxes(cfg), {}
    for ch in cfg.chains:
        f0 = next((cfg.frames(ch, m)[0] for m in cfg.models if cfg.frames(ch, m)), None)
        masks[ch["id"]] = outside_mask(rgb(f0).shape, boxes[ch["id"]])
    drift, mae = {}, {}
    for ch in cfg.chains:
        for m in cfg.models:
            f = cfg.frames(ch, m); key = f"{ch['id']}-{m}"
            drift[key] = texture_series(f, masks[ch["id"]]) if f else []
            mae[key] = drift_series(f, patches[ch["image"]]) if f else []
    (cfg.wd / "drift.json").write_text(json.dumps(drift, indent=1))
    (cfg.wd / "drift_mae.json").write_text(json.dumps(mae, indent=1))
    write_manifest(cfg)
    print("outside-bbox share:", {k: round(float(v.mean()), 2) for k, v in masks.items()})
    for ch in cfg.chains:
        for m in cfg.models:
            v = drift[f"{ch['id']}-{m}"]; st, last, stop = cfg.status(ch, m)
            pick = "  ".join(f"s{k} {v[k - 1]:5.1f}" for k in (1, 10, len(ch["prompts"])) if k <= len(v))
            print(f"{ch['id']:20s} {m:16s} {pick:36s} {st}{f' @ step {stop}' if stop else ''}")
    return drift


# ----------------------------------------------------------------------------------------------------------- render
W, H, FPS = 1920, 1080, 30
BG, INK, MUTED, ACCENT, CARD_FOOT = (241, 239, 234), (24, 24, 24), (120, 120, 120), (150, 100, 30), (22, 22, 22)
GOOD, WARN, BAD = (70, 200, 120), (245, 180, 60), (240, 90, 80)
MODEL_COLOURS = {"nb21": (238, 102, 88), "flux3": (32, 150, 106), "ideogram45": (118, 92, 206), "gpt25-sunburst": (52, 62, 82)}
HN = "/System/Library/Fonts/HelveticaNeue.ttc"
ZH = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FOOT = ("每个模型都在自己上一步的结果上继续改，从不回到原图。背景漂移 = 修改目标框（Gemini 标注）之外的区域里，纹理和细节跟原图对不上的程度："
        "0 = 和原图一致，100 = 原来的细节全没了。")


def font(size, bold=False):
    return ImageFont.truetype(HN, size, index=1 if bold else 0)


def zh(size, bold=False):
    return ImageFont.truetype(ZH, size, index=1 if bold else 0)


def colour(v):
    return GOOD if v < 5 else WARN if v < 20 else BAD


def wrap(d, text, f, width):
    words, line, lines = text.split(), "", []
    for w_ in words:
        t = (line + " " + w_).strip()
        if d.textlength(t, font=f) > width and line:
            lines.append(line); line = w_
        else:
            line = t
    return lines + [line]


def layout(n):
    gap, margin = 22, 26
    P = min(600, (W - 2 * margin - gap * (n - 1)) // n)
    x0 = (W - (n * P + (n - 1) * gap)) // 2
    return P, [x0 + i * (P + gap) for i in range(n)]


class Fonts:
    def __init__(self, n):
        self.lab, self.step, self.of, self.prompt = zh(22, True), font(64, True), font(30), font(32, True)
        self.pill, self.dlab, self.num, self.stop = font(30, True), zh(24, True), font(86 if n <= 3 else 72, True), zh(26)
        self.foot, self.credit = zh(20), zh(22, True)


def rounded(img, r, top=True, bottom=True):
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1 + (0 if bottom else r)], radius=r, fill=255)
    if not top:
        ImageDraw.Draw(m).rectangle([0, 0, img.size[0], r], fill=255)
    return m


def frame(k, n, prompt, cols, keys, imgs, drifts, stops, ymax, F, credit=""):
    """cols: labels; keys: model keys (for colours); imgs: PIL or None; drifts: series per col; stops: (kind, step) or None."""
    P, XS = layout(len(cols))
    im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)
    xL, xR = XS[0], XS[-1] + P
    # top bar: step on the left, edit intent on the right
    d.rounded_rectangle([xL, 22, xR, 158], radius=34, fill=(252, 251, 248), outline=INK, width=3)
    d.text((xL + 36, 36), "步数", font=F.lab, fill=ACCENT)
    num = f"{k:02d}"; d.text((xL + 36, 62), num, font=F.step, fill=INK)
    d.text((xL + 42 + d.textlength(num, font=F.step), 90), f"/ {n}", font=F.of, fill=MUTED)
    dx = xL + 250; d.line([dx, 44, dx, 136], fill=(200, 198, 192), width=2)
    d.text((dx + 30, 36), "修改意图", font=F.lab, fill=ACCENT)
    lines = wrap(d, "原图，还没开始改" if k == 0 else prompt, F.prompt if k else zh(32, True), xR - dx - 70)
    if len(lines) > 2:
        lines = lines[:2]; lines[1] = lines[1].rstrip(".,") + " …"
    for j, line in enumerate(lines):
        d.text((dx + 30, 66 + j * 40 + (20 if len(lines) == 1 else 0)), line, font=F.prompt if k else zh(32, True), fill=INK)
    # cards
    FH = 176
    TY = 184 + max(0, (H - 60 - 184 - (P + FH)) // 2)
    for i, (lab, img) in enumerate(zip(cols, imgs)):
        x = XS[i]
        card = Image.new("RGB", (P, P + FH), CARD_FOOT)
        if img is not None:
            card.paste(img.resize((P, P), Image.LANCZOS), (0, 0))
        else:
            ImageDraw.Draw(card).rectangle([0, 0, P, P], fill=(60, 60, 60))
        cd = ImageDraw.Draw(card)
        if img is None:
            cd.text((24, P // 2 - 14), "无数据", font=F.stop, fill=(220, 220, 220))
        st = stops[i]
        if st and k >= st[1]:
            msg = f"被内容审核拦截（第 {st[1]} 步）" if st[0] == "blocked" else f"第 {st[1]} 步起无输出（{'调用失败' if st[0] == 'failed' else '未跑'}）"
            ov = Image.new("RGBA", (P, 64), (170, 40, 40, 225) if st[0] == "blocked" else (70, 70, 70, 225))
            card.paste(ov, (0, P - 64), ov); cd.text((18, P - 50), msg, font=F.stop, fill=(255, 255, 255))
        # footer: label, sparkline, big number
        ser = drifts[i]; kk = min(k, len(ser)); v = ser[kk - 1] if kk else 0.0
        cd.text((22, P + 18), "背景漂移", font=F.dlab, fill=(235, 235, 235))
        numtxt = f"{v:.1f}" if (ser or not k) else "–"
        nw = cd.textlength(numtxt, font=F.num)
        cd.text((P - 22 - nw, P + FH - 22 - F.num.size), numtxt, font=F.num, fill=(255, 255, 255))
        gx0, gx1, gy0, gy1 = 22, max(60, P - 44 - nw), P + 62, P + FH - 26
        cd.line([gx0, gy1, gx1, gy1], fill=(90, 90, 90), width=2)
        if kk:
            pts = [(gx0 + (gx1 - gx0) * j / (n - 1 if n > 1 else 1), gy1 - (gy1 - gy0) * min(ser[j], ymax) / ymax) for j in range(kk)]
            if len(pts) > 1:
                cd.line(pts, fill=colour(v), width=4)
            cd.ellipse([pts[-1][0] - 6, pts[-1][1] - 6, pts[-1][0] + 6, pts[-1][1] + 6], fill=colour(v))
        else:
            cd.ellipse([gx0 - 6, gy1 - 6, gx0 + 6, gy1 + 6], fill=MODEL_COLOURS.get(keys[i], (130, 130, 130)))
        im.paste(card, (x, TY), rounded(card, 26))
        # model pill
        pc = MODEL_COLOURS.get(keys[i], (90, 90, 90)); w = d.textlength(lab, font=F.pill)
        d.rounded_rectangle([x + 16, TY + 16, x + w + 52, TY + 70], radius=16, fill=pc)
        d.text((x + 34, TY + 26), lab, font=F.pill, fill=(255, 255, 255))
    if credit:  # optional line from chains.json "credit", e.g. the tool / repo used for this evaluation
        cw = d.textlength(credit, font=F.credit)
        d.rounded_rectangle([xL, H - 92, xL + cw + 36, H - 56], radius=18, fill=INK)
        d.text((xL + 18, H - 87), credit, font=F.credit, fill=(255, 255, 255))
    d.text((xL, H - 44), FOOT, font=F.foot, fill=MUTED)
    return im


def render_chain(cfg, ch, models, drift, vd, a):
    n = len(ch["prompts"])
    series = [drift.get(f"{ch['id']}-{m}", []) for m in models]
    frames = [cfg.frames(ch, m) for m in models]
    stops = []
    for m in models:
        st, last, stop = cfg.status(ch, m)
        stops.append((st, stop) if stop else None)
    ymax = 100.0
    F = Fonts(len(models)); labels = [cfg.label(m) for m in models]
    tmp = vd / f"_frames_{ch['id']}"; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    lst = []
    for k in range(n + 1):
        imgs = [Image.open(f[min(k, len(f) - 1)]).convert("RGB") if f else None for f in frames]
        prompt = ch["prompts"][k - 1].replace(cfg.suffix, "").strip() if k else ""
        frame(k, n, prompt, labels, models, imgs, series, stops, ymax, F, cfg.raw.get("credit", "")).save(tmp / f"{k:04d}.png")
        hold = a.hold_start if k == 0 else (a.hold_end if k == n else a.sec)
        lst.append(f"file '{k:04d}.png'\nduration {hold}\n")
    lst.append(f"file '{n:04d}.png'\n")
    (tmp / "list.txt").write_text("".join(lst))
    out = vd / f"{ch['id']}.mp4"
    subprocess.run([FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"), "-vf", f"fps={FPS},format=yuv420p",
                    "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-movflags", "+faststart", str(out)], check=True)
    if a.keep_frames:
        print(f"frames kept: {tmp}")
    else:
        shutil.rmtree(tmp)
    return out


def cmd_render(cfg, a):
    dp = cfg.wd / "drift.json"
    if not dp.exists():
        cmd_score(cfg, argparse.Namespace(patches=None))
    drift = json.loads(dp.read_text())
    models = a.models.split(",") if a.models else cfg.models
    vd = pathlib.Path(a.out_dir) if a.out_dir else cfg.wd / "video"; vd.mkdir(parents=True, exist_ok=True)
    chains = [c for c in cfg.chains if not a.only or c["id"] in a.only.split(",")]
    outs = [render_chain(cfg, c, models, drift, vd, a) for c in chains]
    if len(outs) > 1:
        l = vd / "_all.txt"; l.write_text("".join(f"file '{o.name}'\n" for o in outs))
        subprocess.run([FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(l), "-c", "copy", str(vd / "all.mp4")], check=True)
        l.unlink(); outs.append(vd / "all.mp4")
    print("\n".join(str(o) for o in outs))


# ----------------------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(prog="edit-drift", description=__doc__.split("\n")[1])
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run", help="run edit chains (paid API calls)")
    r.add_argument("config"); r.add_argument("--budget", type=float, required=True, help="USD cap, includes earlier log rows")
    r.add_argument("--chains", default=""); r.add_argument("--models", default="")
    r.add_argument("--max-steps", type=int, default=0); r.add_argument("--workers", type=int, default=0)
    r.add_argument("--blocked-retries", type=int, default=2, help="extra attempts after a content-policy block (block is stochastic)")
    r.add_argument("--dry-run", action="store_true", help="print the plan and cost estimate, call nothing")
    s = sp.add_parser("score", help="background Drift -> patches.json, drift.json, manifest.json")
    s.add_argument("config"); s.add_argument("--patches", default=None, help='JSON {"<image>": [[x0,y0,x1,y1] x3]}')
    v = sp.add_parser("render", help="N-column video per chain + all.mp4")
    v.add_argument("config"); v.add_argument("--models", default=""); v.add_argument("--only", default="")
    v.add_argument("--sec", type=float, default=0.25); v.add_argument("--hold-start", type=float, default=0.5)
    v.add_argument("--hold-end", type=float, default=0.5); v.add_argument("--out-dir", default="")
    v.add_argument("--keep-frames", action="store_true")
    sp.add_parser("models", help="list model adapters")
    a = ap.parse_args()
    if a.cmd == "models":
        for k, ad in ADAPTERS.items():
            print(f"{k:16s} {ad['label']:16s} {ad['channel']:30s} ~${ad['est_cost']}/step  {ad['params']}")
        return
    cfg = Cfg(a.config)
    {"run": cmd_run, "score": cmd_score, "render": cmd_render}[a.cmd](cfg, a)


if __name__ == "__main__":
    main()
