#!/usr/bin/env python3
"""算各臂共同成功的样本交集，并按臂列出每个样本没进交集的原因。

只用 Python 标准库。

用法：
  python3 intersect.py --manifest <run>/manifest.jsonl \
      --arm model_a=<run>/a/results.jsonl --arm model_b=<run>/b/results.jsonl \
      --out-dir <run>/intersect

每个臂的 results.jsonl 每行至少有：
  sample_id   与 manifest 一致
  status      ok | refused | content_filter | error | timeout | invalid_output | 其他自定义值
可选：
  input_sha256  该臂实际发出去的输入字节的哈希；和 manifest 对不上记为 input_mismatch
  params        该臂实际请求参数（dict）；同一臂出现多套参数会告警
同一 sample_id 出现多行时取最后一行，并记重试次数。

产物：
  common_ids.txt   所有臂都 ok 的 sample_id，后续指标只在这上面算
  report.json      每臂状态计数、未进交集的逐样本原因、参数套数
  report.md        可直接贴进报告的「每臂 N」表
"""
import argparse
import json
import os
import sys
from collections import Counter, OrderedDict

OK = "ok"


def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                sys.exit(f"{path} 第 {n} 行不是合法 JSON：{e}")
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", required=True)
    p.add_argument("--arm", action="append", required=True, help="名字=results.jsonl，至少两个")
    p.add_argument("--out-dir", required=True)
    args = p.parse_args()

    if len(args.arm) < 2:
        sys.exit("至少两个 --arm 才谈得上比较")

    manifest = OrderedDict()
    for r in load_jsonl(args.manifest):
        manifest[str(r["sample_id"])] = r
    ids = list(manifest)

    arms = OrderedDict()
    for spec in args.arm:
        if "=" not in spec:
            sys.exit(f"--arm 写成 名字=路径：{spec}")
        name, path = spec.split("=", 1)
        if name in arms:
            sys.exit(f"臂名重复：{name}")
        arms[name] = load_jsonl(path)

    report = {"manifest": os.path.abspath(args.manifest), "n_manifest": len(ids), "arms": OrderedDict()}
    final_status = {}
    for name, rows in arms.items():
        latest, tries, unknown, param_sets = {}, Counter(), [], set()
        for r in rows:
            sid = str(r.get("sample_id"))
            if sid not in manifest:
                unknown.append(sid)
                continue
            tries[sid] += 1
            latest[sid] = r
            if isinstance(r.get("params"), dict):
                param_sets.add(json.dumps(r["params"], sort_keys=True, ensure_ascii=False))
        status = {}
        for sid in ids:
            r = latest.get(sid)
            if r is None:
                status[sid] = "missing"
                continue
            want = manifest[sid].get("sha256")
            got = r.get("input_sha256")
            if want and got and got != want:
                status[sid] = "input_mismatch"
            else:
                status[sid] = str(r.get("status", "unknown"))
        final_status[name] = status
        counts = Counter(status.values())
        report["arms"][name] = {
            "status_counts": dict(counts.most_common()),
            "n_ok": counts.get(OK, 0),
            "n_retried": sum(1 for v in tries.values() if v > 1),
            "unknown_sample_ids": unknown[:50],
            "n_unknown_sample_ids": len(unknown),
            "n_distinct_params": len(param_sets),
            "params": [json.loads(s) for s in sorted(param_sets)][:5],
        }

    common = [sid for sid in ids if all(final_status[a][sid] == OK for a in arms)]
    excluded = OrderedDict()
    for sid in ids:
        if sid in common:
            continue
        excluded[sid] = {a: final_status[a][sid] for a in arms if final_status[a][sid] != OK}
    report["n_common"] = len(common)
    report["excluded"] = excluded

    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "common_ids.txt"), "w", encoding="utf-8") as f:
        f.write("".join(s + "\n" for s in common))
    with open(os.path.join(args.out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    all_status = sorted({s for a in arms for s in final_status[a].values()} - {OK})
    head = ["臂", "manifest N", "ok"] + all_status + ["参数套数"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for a, info in report["arms"].items():
        c = info["status_counts"]
        cells = [a, str(len(ids)), str(info["n_ok"])] + [str(c.get(s, 0)) for s in all_status]
        cells.append(str(info["n_distinct_params"]) if info["n_distinct_params"] else "未记录")
        lines.append("| " + " | ".join(cells) + " |")
    md = "\n".join(lines) + f"\n\n共同成功交集 N = {len(common)} / {len(ids)}。指标只在这 {len(common)} 条上算。\n"
    with open(os.path.join(args.out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(md)

    warn = []
    for a, info in report["arms"].items():
        if info["n_distinct_params"] > 1:
            warn.append(f"{a}: 同一臂出现 {info['n_distinct_params']} 套请求参数，先查是不是中途改过配置")
        if info["n_distinct_params"] == 0:
            warn.append(f"{a}: 没记录实际请求参数（params），无法证明各臂解码设置一致")
        if info["n_unknown_sample_ids"]:
            warn.append(f"{a}: {info['n_unknown_sample_ids']} 条结果的 sample_id 不在 manifest 里")
        if info["status_counts"].get("input_mismatch"):
            warn.append(f"{a}: {info['status_counts']['input_mismatch']} 条实际输入和冻结输入的哈希不一致")
    if len(ids) and len(common) / len(ids) < 0.8:
        warn.append(f"交集只剩 {len(common)}/{len(ids)}，交集本身可能已偏向「简单样本」，报告里要写明")
    for w in warn:
        print("警告：" + w)


if __name__ == "__main__":
    main()
