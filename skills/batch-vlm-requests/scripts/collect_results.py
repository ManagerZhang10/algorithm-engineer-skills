#!/usr/bin/env python3
"""Join batch / realtime outputs back to the frozen manifest by custom_id and give every
input exactly one classified record. Stdlib only.

  collect_results.py runs/r001 runs/r001/results/batch_out_*.jsonl runs/r001/results/realtime.jsonl
  collect_results.py runs/r001 results/*.jsonl --expect-json --write runs/r001/merged.jsonl

Later files override earlier ones for the same custom_id unless that would replace a
model answer with an infrastructure failure, or an ok with anything else (retry overlay);
the record keeps `source_file` and `superseded` so lineage is visible. Never trust provider row order -- join on custom_id only.

Status (one per distinguishable cause):
  ok                content present, finish_reason stop (or unknown)
  invalid_json      --expect-json and content does not parse
  truncated         content present but finish_reason == length
  empty_at_cap      content empty AND output hit the cap -- typically a reasoning model spent
                    max_tokens on thinking. Raise the cap; do not just retry as-is.
  empty             content empty, not at cap
  refusal           message.refusal set, or finish_reason == content_filter
  http_error        non-2xx response (code in `http_status`)
  network_error     no response at all after retries
  missing           in the manifest, absent from every results file
Also reports ids present in results but not in the manifest (foreign) -- that is a bug.

Exit code 0 only if nothing is missing/foreign; status counts are printed either way.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys


# Overlay order: a later record replaces an earlier one only if it is at least as final.
# A model answer (even empty/refusal) is never overwritten by a later infrastructure failure.
RANK = {"network_error": 0, "http_error": 1, "ok": 3}


def read_jsonl(path: str):
    with open(path, encoding="utf-8") as f:
        for n, l in enumerate(f, 1):
            if l.strip():
                try:
                    yield json.loads(l)
                except ValueError:
                    print(f"WARNING: {path}:{n} is not JSON, skipped", file=sys.stderr)


def classify(rec: dict, cap: int | None, expect_json: bool) -> dict:
    resp = rec.get("response") or {}
    code = resp.get("status_code")
    body = resp.get("body") or {}
    out = {"http_status": code, "request_id": resp.get("request_id"), "content": None,
           "finish_reason": None, "usage": body.get("usage"), "model": body.get("model")}
    if code is None:
        out["status"] = "network_error" if rec.get("error") else "missing"
        out["error"] = rec.get("error")
        return out
    if not 200 <= code < 300:
        out["status"] = "http_error"
        out["error"] = body.get("error") or rec.get("error") or body
        return out
    choice = (body.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):  # some providers return content parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    fr = choice.get("finish_reason")
    out.update(content=content, finish_reason=fr)
    usage = body.get("usage") or {}
    comp = usage.get("completion_tokens") or 0
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
    out["reasoning_tokens"] = reasoning
    at_cap = fr == "length" or (cap is not None and comp >= cap)
    if msg.get("refusal") or fr == "content_filter":
        out["status"] = "refusal"
        out["refusal"] = msg.get("refusal")
    elif not (content or "").strip():
        out["status"] = "empty_at_cap" if at_cap else "empty"
    elif fr == "length" or at_cap:
        out["status"] = "truncated"
    elif expect_json:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.find("\n") + 1:] if "\n" in text else text
        try:
            out["parsed"] = json.loads(text)
            out["status"] = "ok"
        except ValueError:
            out["status"] = "invalid_json"
    else:
        out["status"] = "ok"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", help="run directory made by build_requests.py")
    ap.add_argument("results", nargs="+", help="batch output / realtime JSONL files, oldest first")
    ap.add_argument("--expect-json", action="store_true", help="content must parse as JSON")
    ap.add_argument("--write", help="write one merged record per manifest id here")
    ap.add_argument("--retry-ids", help="write ids worth resending (http_error 429/5xx, network_error, missing)")
    args = ap.parse_args()

    run = json.load(open(os.path.join(args.run, "run.json"), encoding="utf-8"))
    cap = run.get("max_tokens")
    manifest = [json.loads(l) for l in open(os.path.join(args.run, "manifest.jsonl"), encoding="utf-8") if l.strip()]
    ids = {m["custom_id"] for m in manifest}

    best: dict[str, dict] = {}
    foreign = collections.Counter()
    for path in args.results:
        for rec in read_jsonl(path):
            cid = rec.get("custom_id")
            if cid not in ids:
                foreign[path] += 1
                continue
            c = classify(rec, cap, args.expect_json)
            c["source_file"] = os.path.basename(path)
            prev = best.get(cid)
            if prev is None or RANK.get(c["status"], 2) >= RANK.get(prev["status"], 2):
                c["superseded"] = (prev or {}).get("superseded", []) + ([prev["status"] + "@" + prev["source_file"]] if prev else [])
                best[cid] = c

    counts = collections.Counter()
    merged = []
    for m in manifest:
        c = best.get(m["custom_id"]) or {"status": "missing"}
        counts[c["status"]] += 1
        merged.append({"custom_id": m["custom_id"], "source": m["source"], "image_sha256": m["image_sha256"],
                       "inner_sha256": m["inner_sha256"], **c})

    print(f"manifest {len(manifest):,}   max_tokens {cap}")
    for k, v in counts.most_common():
        print(f"  {k:<14} {v:>8,}  {v / len(manifest):6.1%}")
    models = collections.Counter(r.get("model") for r in merged if r.get("model"))
    if len(models) > 1:
        print(f"  NOTE: responses came from several model versions: {dict(models)}")
    if counts.get("empty_at_cap"):
        rs = [r.get("reasoning_tokens") or 0 for r in merged if r["status"] == "empty_at_cap"]
        print(f"  empty_at_cap: mean reasoning tokens {sum(rs) / len(rs):,.0f} -- raise the cap in a NEW run, not a silent rebuild")
    for path, n in foreign.items():
        print(f"  FOREIGN ids in {path}: {n} (results from another run mixed in?)")

    if args.write:
        with open(args.write, "w", encoding="utf-8") as f:
            for r in merged:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"wrote {args.write}")
    if args.retry_ids:
        retry = [r["custom_id"] for r in merged
                 if r["status"] in ("missing", "network_error")
                 or (r["status"] == "http_error" and (r.get("http_status") in (408, 409, 429) or (r.get("http_status") or 0) >= 500))]
        with open(args.retry_ids, "w", encoding="utf-8") as f:
            f.write("".join(i + "\n" for i in retry))
        print(f"wrote {len(retry):,} retryable ids to {args.retry_ids}")
    return 0 if not counts.get("missing") and not foreign else 1


if __name__ == "__main__":
    sys.exit(main())
