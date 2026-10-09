#!/usr/bin/env python3
"""Send a frozen run through a realtime OpenAI-compatible endpoint, with bounded
concurrency, retries, and resume. Stdlib only.

It sends the frozen "body" of each batch line, re-serialised with the run's canonical
serializer, and refuses to send if that does not hash to the recorded inner_sha256 --
so smoke, full run and retries are provably the same request bytes.

Output lines use the same shape as an OpenAI batch output file, so collect_results.py
reads both:
  {"custom_id", "response": {"status_code", "request_id", "body"}, "error", "attempts", "latency_s"}

  export MY_API_KEY=...                     # never put the key on the command line or in files
  run_realtime.py runs/r001 --base-url https://api.example.com/v1 --api-key-env MY_API_KEY \
      --limit 30 --out runs/r001/results/smoke.jsonl          # paid smoke
  run_realtime.py runs/r001 --base-url ... --api-key-env MY_API_KEY --concurrency 32   # full / resume

Resume: ids that already have a terminal record in --out are skipped (2xx, or 4xx other
than 408/409/429). Retryable: network errors, timeouts, 408/409/429/5xx, with
exponential backoff + jitter, honouring Retry-After.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 520, 522, 524, 529}


def canon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def terminal(rec: dict) -> bool:
    code = (rec.get("response") or {}).get("status_code")
    return code is not None and (200 <= code < 300 or (400 <= code < 500 and code not in RETRYABLE))


def load_done(path: str) -> set[str]:
    done: set[str] = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for l in f:
                if l.strip():
                    rec = json.loads(l)
                    if terminal(rec):
                        done.add(rec["custom_id"])
    return done


def send(url: str, key: str, payload: bytes, timeout: float, max_retries: int, base_delay: float) -> dict:
    attempts, t0, last = 0, time.time(), None
    while True:
        attempts += 1
        req = urllib.request.Request(url, data=payload, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        retry_after = None
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read().decode("utf-8"))
                return {"response": {"status_code": r.status,
                                     "request_id": r.headers.get("x-request-id") or body.get("id"),
                                     "body": body},
                        "error": None, "attempts": attempts, "latency_s": round(time.time() - t0, 2)}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                body = json.loads(raw)
            except ValueError:
                body = {"raw": raw[:2000]}
            last = {"response": {"status_code": e.code, "request_id": e.headers.get("x-request-id"), "body": body},
                    "error": {"type": "http", "message": f"HTTP {e.code}"}}
            if e.code not in RETRYABLE:
                return {**last, "attempts": attempts, "latency_s": round(time.time() - t0, 2)}
            ra = e.headers.get("Retry-After")
            retry_after = float(ra) if ra and ra.replace(".", "", 1).isdigit() else None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = {"response": None, "error": {"type": "network", "message": str(e)[:500]}}
        if attempts > max_retries:
            return {**last, "attempts": attempts, "latency_s": round(time.time() - t0, 2)}
        delay = retry_after if retry_after is not None else base_delay * 2 ** (attempts - 1)
        time.sleep(min(delay, 120) * random.uniform(0.8, 1.2))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", help="run directory made by build_requests.py")
    ap.add_argument("--base-url", required=True, help="e.g. https://api.example.com/v1")
    ap.add_argument("--path", default="/chat/completions")
    ap.add_argument("--api-key-env", required=True, help="NAME of the env var holding the key")
    ap.add_argument("--out", help="results JSONL (default <run>/results/realtime.jsonl), appended")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--max-retries", type=int, default=5)
    ap.add_argument("--base-delay", type=float, default=2.0)
    ap.add_argument("--timeout", type=float, default=600, help="per-attempt seconds; reasoning models are slow")
    ap.add_argument("--limit", type=int, help="only the first N pending requests (smoke)")
    ap.add_argument("--ids", help="file with one custom_id per line to (re)send")
    args = ap.parse_args()

    key = os.environ.get(args.api_key_env)
    if not key:
        sys.exit(f"env var {args.api_key_env} is empty")
    out = args.out or os.path.join(args.run, "results", "realtime.jsonl")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    manifest = {}
    with open(os.path.join(args.run, "manifest.jsonl"), encoding="utf-8") as f:
        for l in f:
            r = json.loads(l)
            manifest[r["custom_id"]] = r
    wanted = None
    if args.ids:
        wanted = {l.strip() for l in open(args.ids, encoding="utf-8") if l.strip()}
    done = load_done(out)

    jobs = []
    for shard in sorted(glob.glob(os.path.join(args.run, "requests", "*.jsonl"))):
        with open(shard, "rb") as f:
            for raw in f:
                raw = raw.rstrip(b"\n")
                if not raw:
                    continue
                line = json.loads(raw)
                cid = line["custom_id"]
                if cid in done or (wanted is not None and cid not in wanted):
                    continue
                m = manifest[cid]
                if hashlib.sha256(raw).hexdigest() != m["line_sha256"]:
                    sys.exit(f"{cid}: frozen line bytes changed since build -- refusing to send")
                payload = canon(line["body"]).encode("utf-8")
                if hashlib.sha256(payload).hexdigest() != m["inner_sha256"]:
                    sys.exit(f"{cid}: body does not reproduce inner_sha256 -- serializer mismatch")
                jobs.append((cid, payload))
    if args.limit:
        jobs = jobs[:args.limit]
    print(f"pending {len(jobs):,}   already terminal {len(done):,}   concurrency {args.concurrency}", flush=True)
    if not jobs:
        return 0

    url = args.base_url.rstrip("/") + args.path
    lock = threading.Lock()
    stats = {"ok": 0, "fail": 0}
    t0 = time.time()
    with open(out, "a", encoding="utf-8") as fh, ThreadPoolExecutor(args.concurrency) as pool:
        futs = {pool.submit(send, url, key, p, args.timeout, args.max_retries, args.base_delay): cid
                for cid, p in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            cid = futs[fut]
            rec = {"custom_id": cid, **fut.result()}
            code = (rec.get("response") or {}).get("status_code")
            with lock:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                stats["ok" if code and 200 <= code < 300 else "fail"] += 1
            if i % 50 == 0 or i == len(jobs):
                print(f"  {i:,}/{len(jobs):,}  ok {stats['ok']:,}  fail {stats['fail']:,}  "
                      f"{time.time() - t0:,.0f}s", flush=True)
    print(f"results appended to {out}; run collect_results.py next")
    return 0 if stats["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
