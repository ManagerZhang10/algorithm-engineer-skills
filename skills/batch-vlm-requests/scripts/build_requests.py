#!/usr/bin/env python3
"""Build a frozen batch of OpenAI-compatible VLM requests from a folder of images.

One image -> one request. Image bytes are inlined as a base64 data URI (never a URL),
the exact bytes of every request are written once and hashed, and a manifest maps each
custom_id back to its source image. Stdlib only.

  build_requests.py images/ --out runs/r001 --model <model> --prompt-file prompt.txt
  build_requests.py images/ --out runs/r001 --model <model> --prompt "Describe the image." \
      --max-tokens 16000 --max-tokens-field max_completion_tokens --shard-max-bytes 90000000

Output (the run directory must not exist yet; a changed prompt/model/encoding is a new run):
  <out>/requests/shard-0000.jsonl   batch lines: {"custom_id","method","url","body"}
  <out>/manifest.jsonl              custom_id -> source path, image sha256, size, shard, hashes
  <out>/run.json                    config, prompt sha256, per-shard bytes/sha256

Hashes:
  inner_sha256  sha256 of canonical JSON of "body" (what the provider consumes)
  line_sha256   sha256 of the exact UTF-8 bytes of the JSONL line, without the newline
Retries and resumes must reuse these bytes, not rebuild them.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import struct
import sys

VERSION = "1"
EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def canon(obj) -> str:
    """The one serializer for this run. Every hash and every resend goes through it."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff(data: bytes) -> tuple[str, int | None, int | None]:
    """Return (mime, width, height) from magic bytes; width/height None if unparsable."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return "image/png", w, h
    if data[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", data[6:10])
        return "image/gif", w, h
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8 ":
            w, h = struct.unpack("<HH", data[26:30])
            return "image/webp", w & 0x3FFF, h & 0x3FFF
        if chunk == b"VP8L":
            b = data[21:25]
            w = 1 + (((b[1] & 0x3F) << 8) | b[0])
            h = 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
            return "image/webp", w, h
        if chunk == b"VP8X":
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            return "image/webp", w, h
        return "image/webp", None, None
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg = struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "image/jpeg", w, h
            i += 2 + seg
        return "image/jpeg", None, None
    return "application/octet-stream", None, None


def list_images(paths: list[str]) -> list[tuple[str, str, int]]:
    """(absolute path, path relative to its input root, root index), sorted for a stable order."""
    found: list[tuple[str, str, int]] = []
    for r, p in enumerate(paths):
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in files:
                    if os.path.splitext(f)[1].lower() in EXTS:
                        full = os.path.join(root, f)
                        found.append((os.path.abspath(full), os.path.relpath(full, p), r))
        elif os.path.isfile(p):
            found.append((os.path.abspath(p), os.path.basename(p), r))
        else:
            sys.exit(f"not found: {p}")
    found.sort(key=lambda t: (t[2], t[1]))
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", help="image files or directories (recursive)")
    ap.add_argument("--out", required=True, help="new run directory; refused if it already exists")
    ap.add_argument("--model", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prompt")
    g.add_argument("--prompt-file")
    ap.add_argument("--system", help="optional system prompt")
    ap.add_argument("--max-tokens", type=int, default=4096,
                    help="output cap; reasoning models need room for thinking + answer")
    ap.add_argument("--max-tokens-field", default="max_tokens",
                    help="e.g. max_completion_tokens for providers that renamed it")
    ap.add_argument("--temperature", type=float)
    ap.add_argument("--detail", choices=["low", "high", "auto"], help="OpenAI-style image detail")
    ap.add_argument("--extra-body", help="JSON object merged into every body (response_format, etc.)")
    ap.add_argument("--url", default="/v1/chat/completions", help="batch line url field")
    ap.add_argument("--id-prefix", default="req-")
    ap.add_argument("--shard-max-bytes", type=int, default=90_000_000,
                    help="cut a new shard before exceeding this (check the provider's current per-file limit)")
    ap.add_argument("--shard-max-requests", type=int, default=50_000)
    args = ap.parse_args()

    if os.path.exists(args.out):
        sys.exit(f"{args.out} exists. A frozen run is immutable; build a new revision into a new directory.")
    prompt = args.prompt if args.prompt is not None else open(args.prompt_file, encoding="utf-8").read()
    extra = json.loads(args.extra_body) if args.extra_body else {}
    images = list_images(args.images)
    if not images:
        sys.exit("no images found")

    req_dir = os.path.join(args.out, "requests")
    os.makedirs(req_dir)
    manifest = open(os.path.join(args.out, "manifest.jsonl"), "w", encoding="utf-8")

    shards: list[dict] = []
    cur = None
    seen_sha: dict[str, str] = {}
    dupes = 0
    width = max(6, len(str(len(images))))

    def open_shard():
        idx = len(shards)
        path = os.path.join(req_dir, f"shard-{idx:04d}.jsonl")
        shards.append({"file": os.path.relpath(path, args.out), "requests": 0, "bytes": 0})
        return idx, open(path, "wb")

    for n, (full, rel, root) in enumerate(images):
        data = open(full, "rb").read()
        img_sha = sha(data)
        mime, w, h = sniff(data)
        if mime == "application/octet-stream":
            sys.exit(f"unrecognised image format: {rel}")
        if img_sha in seen_sha:
            dupes += 1
        seen_sha.setdefault(img_sha, rel)

        image_part = {"type": "image_url",
                      "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"}}
        if args.detail:
            image_part["image_url"]["detail"] = args.detail
        messages = []
        if args.system:
            messages.append({"role": "system", "content": args.system})
        messages.append({"role": "user", "content": [{"type": "text", "text": prompt}, image_part]})
        body = {"model": args.model, "messages": messages, args.max_tokens_field: args.max_tokens}
        if args.temperature is not None:
            body["temperature"] = args.temperature
        body.update(extra)

        cid = f"{args.id_prefix}{n:0{width}d}-{img_sha[:10]}"
        inner = canon(body).encode("utf-8")
        line = canon({"custom_id": cid, "method": "POST", "url": args.url, "body": body}).encode("utf-8")

        if cur is None or (shards[cur[0]]["bytes"] + len(line) + 1 > args.shard_max_bytes
                           and shards[cur[0]]["requests"] > 0) \
                or shards[cur[0]]["requests"] >= args.shard_max_requests:
            if cur:
                cur[1].close()
            cur = open_shard()
        if len(line) + 1 > args.shard_max_bytes:
            print(f"WARNING: single request {cid} is {len(line):,} bytes, above --shard-max-bytes", file=sys.stderr)
        idx, fh = cur
        line_no = shards[idx]["requests"]
        fh.write(line + b"\n")
        shards[idx]["requests"] += 1
        shards[idx]["bytes"] += len(line) + 1

        manifest.write(canon({
            "custom_id": cid, "source": rel, "root": root, "image_sha256": img_sha,
            "image_bytes": len(data), "mime": mime, "width": w, "height": h,
            "shard": idx, "line": line_no, "line_bytes": len(line),
            "inner_sha256": sha(inner), "line_sha256": sha(line),
        }) + "\n")

    cur[1].close()
    manifest.close()
    for s in shards:
        s["sha256"] = sha(open(os.path.join(args.out, s["file"]), "rb").read())

    run = {
        "builder": f"build_requests.py v{VERSION}",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "input_roots": [os.path.abspath(p) for p in args.images],
        "model": args.model, "url": args.url,
        "max_tokens_field": args.max_tokens_field, "max_tokens": args.max_tokens,
        "temperature": args.temperature, "detail": args.detail, "extra_body": extra,
        "system_sha256": sha(args.system.encode()) if args.system else None,
        "prompt_sha256": sha(prompt.encode("utf-8")), "prompt": prompt, "system": args.system,
        "image_carrier": "inline-base64", "serializer": "json sort_keys, separators=(',',':'), ensure_ascii=False",
        "requests": len(images), "duplicate_images": dupes,
        "manifest_sha256": sha(open(os.path.join(args.out, "manifest.jsonl"), "rb").read()),
        "shards": shards,
    }
    with open(os.path.join(args.out, "run.json"), "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=2)

    total = sum(s["bytes"] for s in shards)
    print(f"requests {len(images):,}   shards {len(shards)}   total {total / 1e6:,.1f} MB   duplicates {dupes}")
    for s in shards:
        print(f"  {s['file']}  {s['requests']:,} req  {s['bytes'] / 1e6:,.1f} MB  sha256 {s['sha256'][:16]}")
    print(f"frozen into {args.out}  (do not edit; a change is a new run directory)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
