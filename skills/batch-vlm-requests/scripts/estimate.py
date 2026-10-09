#!/usr/bin/env python3
"""Estimate tokens and cost of a frozen run before submitting it. Stdlib only.

Two modes, use both:
  1. Formula (no API call): image tokens from each image's width/height using a provider
     heuristic. Heuristics drift as providers change resizing rules -- treat as a first guess.
  2. Calibrated: pass a results file from a small real smoke run (--calibrate). The script
     reads actual usage (prompt / completion / reasoning tokens) and extrapolates. This is the
     number to put in front of the user.

Prices are never built in. Pass the current per-1M-token prices you looked up today.

  estimate.py runs/r001 --scheme openai-tile --out-tokens 300
  estimate.py runs/r001 --calibrate runs/r001/results/smoke.jsonl \
      --price-in 2.0 --price-out 8.0 --batch-discount 0.5
  estimate.py runs/r001 --shard-limit-bytes 200000000     # also check shard sizes

Heuristics (snapshot as of 2026-10; check the provider's current vision docs):
  openai-tile   fit in 2048x2048, shortest side to 768, 512px tiles: 85 + 170 * tiles
                (detail=low: 85 flat). Newer OpenAI models may use a patch-based rule.
  anthropic     long edge capped (~1568 px), tokens ~= w * h / 750
  gemini        both sides <= 384: 258; else 768px tiles x 258. Newer models expose a
                media-resolution setting with different per-image budgets.
  fixed         --fixed-tokens per image
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys


def openai_tile(w: int, h: int, detail: str | None) -> int:
    if detail == "low":
        return 85
    s = min(1.0, 2048 / max(w, h))
    w, h = w * s, h * s
    s = 768 / min(w, h)
    if s < 1:
        w, h = w * s, h * s
    return 85 + 170 * math.ceil(w / 512) * math.ceil(h / 512)


def anthropic(w: int, h: int, _d=None) -> int:
    s = min(1.0, 1568 / max(w, h), math.sqrt(1_150_000 / (w * h)))
    return math.ceil(w * s * h * s / 750)


def gemini(w: int, h: int, _d=None) -> int:
    if w <= 384 and h <= 384:
        return 258
    return 258 * math.ceil(w / 768) * math.ceil(h / 768)


SCHEMES = {"openai-tile": openai_tile, "anthropic": anthropic, "gemini": gemini}


def read_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def usage_of(rec: dict) -> dict | None:
    """Pull usage from a batch-output / realtime record (OpenAI-compatible shape)."""
    body = (rec.get("response") or {}).get("body") or {}
    u = body.get("usage")
    if not u:
        return None
    details = u.get("completion_tokens_details") or {}
    return {
        "in": u.get("prompt_tokens") or u.get("input_tokens") or 0,
        "out": u.get("completion_tokens") or u.get("output_tokens") or 0,
        "reasoning": details.get("reasoning_tokens") or u.get("reasoning_tokens") or 0,
    }


def fmt_money(x: float | None) -> str:
    return "n/a (pass --price-in/--price-out)" if x is None else f"${x:,.2f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", help="run directory made by build_requests.py")
    ap.add_argument("--scheme", choices=sorted(SCHEMES) + ["fixed"], default="openai-tile")
    ap.add_argument("--fixed-tokens", type=int, default=1000)
    ap.add_argument("--text-tokens", type=int, help="prompt text tokens per request (default: chars/3 guess)")
    ap.add_argument("--out-tokens", type=int, default=300,
                    help="expected output tokens per request INCLUDING reasoning tokens")
    ap.add_argument("--calibrate", nargs="*", default=[], help="results JSONL from a real smoke run")
    ap.add_argument("--price-in", type=float, help="USD per 1M input tokens (look up today)")
    ap.add_argument("--price-out", type=float, help="USD per 1M output tokens (look up today)")
    ap.add_argument("--batch-discount", type=float, default=1.0, help="multiplier for batch, e.g. 0.5")
    ap.add_argument("--shard-limit-bytes", type=int, help="provider per-file limit to check shards against")
    args = ap.parse_args()

    run = json.load(open(os.path.join(args.run, "run.json"), encoding="utf-8"))
    rows = read_jsonl(os.path.join(args.run, "manifest.jsonl"))
    n = len(rows)
    text = (run.get("prompt") or "") + (run.get("system") or "")
    text_tokens = args.text_tokens if args.text_tokens is not None else max(1, len(text) // 3)

    print(f"run           {args.run}   model {run['model']}   requests {n:,}")
    sizes = [r["line_bytes"] for r in rows]
    print(f"request bytes mean {statistics.mean(sizes):,.0f}  median {statistics.median(sizes):,.0f}  max {max(sizes):,}")
    if run.get("image_carrier") != "inline-base64":
        print("  WARNING: images are not inlined; provider-side URL fetching has its own rate ceiling")

    missing_dims = sum(1 for r in rows if not r.get("width"))
    if args.scheme == "fixed":
        per_img = [args.fixed_tokens] * n
    else:
        fn = SCHEMES[args.scheme]
        per_img = [fn(r["width"], r["height"], run.get("detail")) if r.get("width") else args.fixed_tokens for r in rows]
    est_in = [t + text_tokens for t in per_img]
    total_in = sum(est_in)
    total_out = args.out_tokens * n
    print(f"\n[formula: {args.scheme}]  image tokens/req mean {statistics.mean(per_img):,.0f}  "
          f"max {max(per_img):,}  (+{text_tokens} text){'  dims missing: ' + str(missing_dims) if missing_dims else ''}")
    print(f"  input  {total_in:,} tok   output {total_out:,} tok (assumed {args.out_tokens}/req)")

    def cost(tin: float, tout: float) -> float | None:
        if args.price_in is None or args.price_out is None:
            return None
        return (tin * args.price_in + tout * args.price_out) / 1e6

    c = cost(total_in, total_out)
    print(f"  cost   realtime {fmt_money(c)}   batch {fmt_money(None if c is None else c * args.batch_discount)}")

    est_by_id = {r["custom_id"]: e for r, e in zip(rows, est_in)}
    usages = []
    for p in args.calibrate:
        for rec in read_jsonl(p):
            u = usage_of(rec)
            if u and rec.get("custom_id") in est_by_id:
                u["est"] = est_by_id[rec["custom_id"]]
                usages.append(u)
    if args.calibrate:
        if not usages:
            print("\n[calibrated]  no usage found in calibration files")
        else:
            m_in = statistics.mean(u["in"] for u in usages)
            m_out = statistics.mean(u["out"] for u in usages)
            m_r = statistics.mean(u["reasoning"] for u in usages)
            max_out = max(u["out"] for u in usages)
            k = len(usages)
            print(f"\n[calibrated on {k} real responses]")
            print(f"  per req: input {m_in:,.0f}  output {m_out:,.0f} (of which reasoning {m_r:,.0f})  max output {max_out:,}")
            ratio = statistics.mean(u["est"] for u in usages) / m_in
            print(f"  formula/actual input ratio {ratio:.2f}  ({'formula is off; trust calibrated' if abs(ratio - 1) > 0.25 else 'formula roughly agrees'})")
            cap = run.get("max_tokens")
            if cap and max_out >= cap * 0.95:
                print(f"  WARNING: some outputs reach the {cap}-token cap -> truncation / empty content risk")
            if k < 20:
                print(f"  note: only {k} samples; large images or long answers in the tail may move this")
            ci, co = m_in * n, m_out * n
            c2 = cost(ci, co)
            print(f"  full run: input {ci:,.0f} tok  output {co:,.0f} tok")
            print(f"  cost   realtime {fmt_money(c2)}   batch {fmt_money(None if c2 is None else c2 * args.batch_discount)}")

    if args.shard_limit_bytes:
        print(f"\n[shards vs limit {args.shard_limit_bytes:,} bytes]")
        bad = 0
        for s in run["shards"]:
            ok = s["bytes"] <= args.shard_limit_bytes
            bad += not ok
            print(f"  {s['file']}  {s['bytes'] / 1e6:,.1f} MB  {'ok' if ok else 'OVER LIMIT'}")
        if bad:
            print("  rebuild into a NEW run dir with a smaller --shard-max-bytes")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
