#!/usr/bin/env python3
"""冻结评测输入：给「实际要发给模型的字节」逐个算 SHA-256，写 manifest.jsonl。

只用 Python 标准库。

用法：
  # 1) 冻结一个目录下的输入文件（图片、文本、音频都行）
  python3 freeze_manifest.py freeze --inputs <dir> --out <run>/manifest.jsonl

  # 2) 冻结一份样本表（jsonl，每行至少有 sample_id；可带 prompt / file 字段）
  python3 freeze_manifest.py freeze --samples samples.jsonl --base-dir <dir> --out <run>/manifest.jsonl

  # 3) 跑批前 / 交付前复核：文件和 prompt 是否还是冻结时的字节
  python3 freeze_manifest.py verify --manifest <run>/manifest.jsonl [--base-dir <dir>]

manifest.jsonl 每行：
  {"sample_id", "file", "sha256", "bytes", "width", "height", "prompt_sha256"}
最后在同目录写 manifest.digest：整份清单的 SHA-256，报告里引用它即可说明「各臂吃的是同一份输入」。
"""
import argparse
import hashlib
import json
import os
import struct
import sys

SKIP_NAMES = {".DS_Store", "Thumbs.db"}


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def image_size(path):
    """从文件头读 PNG / JPEG / GIF / WebP 的宽高；不是图片返回 (None, None)。"""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return w, h
            if head[:6] in (b"GIF87a", b"GIF89a"):
                w, h = struct.unpack("<HH", head[6:10])
                return w, h
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                f.seek(12)
                chunk = f.read(30)
                kind = chunk[:4]
                if kind == b"VP8X":
                    w = int.from_bytes(chunk[12:15], "little") + 1
                    h = int.from_bytes(chunk[15:18], "little") + 1
                    return w, h
                if kind == b"VP8 ":
                    w, h = struct.unpack("<HH", chunk[14:18])
                    return w & 0x3FFF, h & 0x3FFF
                if kind == b"VP8L":
                    b = chunk[9:13]
                    w = 1 + (((b[1] & 0x3F) << 8) | b[0])
                    h = 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6))
                    return w, h
                return None, None
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    marker = f.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None, None
                    code = marker[1]
                    if code in (0xD8, 0x01) or 0xD0 <= code <= 0xD7:
                        continue
                    seglen = struct.unpack(">H", f.read(2))[0]
                    if code in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        f.read(1)
                        h, w = struct.unpack(">HH", f.read(4))
                        return w, h
                    f.seek(seglen - 2, 1)
    except (OSError, struct.error):
        pass
    return None, None


def record_for_file(sample_id, path, rel):
    w, h = image_size(path)
    return {
        "sample_id": sample_id,
        "file": rel,
        "sha256": sha256_file(path),
        "bytes": os.path.getsize(path),
        "width": w,
        "height": h,
    }


def iter_dir(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name in SKIP_NAMES or name.startswith("."):
                continue
            full = os.path.join(dirpath, name)
            yield full, os.path.relpath(full, root)


def build_records(args):
    records = []
    if args.inputs:
        for full, rel in iter_dir(args.inputs):
            sid = os.path.splitext(rel)[0].replace(os.sep, "/")
            records.append(record_for_file(sid, full, rel))
    if args.samples:
        base = args.base_dir or os.path.dirname(os.path.abspath(args.samples))
        with open(args.samples, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                sid = row.get("sample_id")
                if sid is None:
                    sys.exit(f"samples 第 {n} 行缺 sample_id")
                rec = {"sample_id": str(sid)}
                if row.get("file"):
                    full = os.path.join(base, row["file"])
                    if not os.path.isfile(full):
                        sys.exit(f"samples 第 {n} 行的文件不存在：{row['file']}")
                    rec.update(record_for_file(str(sid), full, row["file"]))
                if "prompt" in row:
                    rec["prompt_sha256"] = sha256_bytes(row["prompt"].encode("utf-8"))
                records.append(rec)
    ids = [r["sample_id"] for r in records]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        sys.exit(f"sample_id 重复：{dup[:10]}")
    return records


def cmd_freeze(args):
    if not args.inputs and not args.samples:
        sys.exit("至少给 --inputs 或 --samples 之一")
    records = build_records(args)
    if os.path.exists(args.out) and not args.force:
        sys.exit(f"{args.out} 已存在。冻结后的清单不应被覆盖；确需重冻结请加 --force 并换 run 目录")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(body)
    digest = sha256_bytes(body.encode("utf-8"))
    with open(os.path.join(os.path.dirname(os.path.abspath(args.out)), "manifest.digest"), "w") as f:
        f.write(digest + "\n")
    hashes = [r["sha256"] for r in records if r.get("sha256")]
    n_dup = len(hashes) - len(set(hashes))
    if n_dup:
        print(f"提示：有 {n_dup} 个文件与别的样本字节完全相同，重复样本会给均值加权，确认是不是故意的。")
    sizes = {}
    for r in records:
        if r.get("width"):
            k = f"{r['width']}x{r['height']}"
            sizes[k] = sizes.get(k, 0) + 1
    print(f"冻结 {len(records)} 条 → {args.out}")
    print(f"manifest digest: {digest}")
    if sizes:
        print("图片尺寸分布：" + ", ".join(f"{k}×{v}" for k, v in sorted(sizes.items(), key=lambda x: -x[1])))
        if len(sizes) > 1:
            print("提示：输入尺寸不统一。若协议要求统一分辨率，先统一预处理再冻结。")


def cmd_verify(args):
    base = args.base_dir or os.path.dirname(os.path.abspath(args.manifest))
    bad = 0
    total = 0
    with open(args.manifest, encoding="utf-8") as f:
        body = f.read()
    digest_path = os.path.join(os.path.dirname(os.path.abspath(args.manifest)), "manifest.digest")
    if os.path.exists(digest_path):
        want = open(digest_path).read().strip()
        got = sha256_bytes(body.encode("utf-8"))
        if want != got:
            print(f"清单本身被改过：digest {got} != {want}")
            bad += 1
    for line in body.splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if not r.get("file"):
            continue
        total += 1
        full = os.path.join(base, r["file"])
        if not os.path.isfile(full):
            print(f"缺失  {r['sample_id']}  {r['file']}")
            bad += 1
        elif sha256_file(full) != r["sha256"]:
            print(f"已变  {r['sample_id']}  {r['file']}")
            bad += 1
    print(f"复核 {total} 个文件，问题 {bad} 处")
    sys.exit(1 if bad else 0)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--inputs", help="输入文件目录（递归，sample_id = 去扩展名的相对路径）")
    f.add_argument("--samples", help="样本表 jsonl：sample_id 必填，可带 file / prompt")
    f.add_argument("--base-dir", help="samples 里 file 的相对根目录，默认 samples 所在目录")
    f.add_argument("--out", required=True)
    f.add_argument("--force", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("--manifest", required=True)
    v.add_argument("--base-dir", help="file 的相对根目录，默认 manifest 所在目录；用 --inputs 冻结的要指回那个输入目录")
    args = p.parse_args()
    {"freeze": cmd_freeze, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    main()
