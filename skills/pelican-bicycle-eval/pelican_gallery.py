#!/usr/bin/env python3
"""Render a reusable, self-contained SVG comparison gallery from JSON.

The renderer performs no model calls. It validates and embeds SVG files named by
the manifest, groups samples into model/effort lanes, derives structural metrics,
and optionally shows raw plus weighted token usage.

Usage:
    python3 pelican_gallery.py MANIFEST
    python3 pelican_gallery.py MANIFEST --out board.html --open
    python3 pelican_gallery.py MANIFEST --lang en
"""

import argparse
import base64
import hashlib
import html
import json
import re
import sys
import webbrowser
import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlparse

from pelican_proxy_check import SHAPE_RE, SVG_RE, cheats


PALETTE = ("#0077b6", "#f25c2a", "#16856b", "#7c5cc4", "#b57912", "#c23b67")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

LABELS = {
    "zh": {
        "default_title": "鹈鹕骑自行车 · 模型横评",
        "default_subtitle": "同一道题，多次独立采样。原始 SVG 不做人工修图。",
        "same_prompt": "同题",
        "models": "个模型",
        "samples": "张 SVG",
        "attempt": "第 {n} 次",
        "download": "下载 SVG",
        "zoom": "点击放大",
        "effort": "推理档位",
        "channel": "通道",
        "canvas": "画布",
        "shapes": "图元",
        "paths": "路径",
        "size": "大小",
        "latency": "耗时",
        "raw_tokens": "原始总 token",
        "weighted_tokens": "折算消耗",
        "default_token_basis": "等价 token",
        "known_only": "仅统计有 token 记录的样本",
        "raw_prefix": "原始",
        "times": "倍",
        "total": "全部样本",
        "close": "关闭",
        "method": "图元、路径与文件大小只描述 SVG 的结构复杂度，不代表画面质量。",
        "exact_note": "带 ≈ 的 token 是估算值；其余为采集器记录的精确值。",
    },
    "en": {
        "default_title": "Pelican on a bicycle · model comparison",
        "default_subtitle": "One prompt, repeated independent samples. SVG output is unedited.",
        "same_prompt": "Same prompt",
        "models": "models",
        "samples": "SVG samples",
        "attempt": "Attempt {n}",
        "download": "Download SVG",
        "zoom": "Click to enlarge",
        "effort": "Reasoning effort",
        "channel": "Channel",
        "canvas": "Canvas",
        "shapes": "Shapes",
        "paths": "Paths",
        "size": "Size",
        "latency": "Time",
        "raw_tokens": "Raw total tokens",
        "weighted_tokens": "Weighted usage",
        "default_token_basis": "equivalent tokens",
        "known_only": "Only samples with token data are included",
        "raw_prefix": "Raw",
        "times": "×",
        "total": "All samples",
        "close": "Close",
        "method": "Shape, path, and file-size counts describe SVG structure, not visual quality.",
        "exact_note": "Token values prefixed with ≈ are estimates; the rest are collector-recorded values.",
    },
}


class GalleryError(ValueError):
    pass


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def text(value):
    return html.escape(str(value or ""))


def compact_number(value):
    value = float(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}".rstrip("0").rstrip(".") + "m"
    if value >= 1_000:
        return f"{value / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    return f"{value:,.1f}".rstrip("0").rstrip(".")


def full_number(value):
    value = float(value)
    return f"{value:,.1f}" if not value.is_integer() else f"{int(value):,}"


def valid_color(value, fallback):
    return value if isinstance(value, str) and COLOR_RE.fullmatch(value) else fallback


def source_link(url):
    if not url:
        return ""
    parsed = urlparse(str(url))
    if parsed.scheme not in ("http", "https"):
        raise GalleryError("token_basis.source_url must use http or https")
    return str(url)


def extract_svg(path):
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GalleryError(f"cannot read SVG source {path}: {exc}") from exc
    match = SVG_RE.search(raw)
    if not match:
        raise GalleryError(f"no complete <svg> element in {path}")
    svg = match.group(0).strip() + "\n"
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise GalleryError(f"invalid SVG XML in {path}: {exc}") from exc
    bypasses = cheats(svg)
    if bypasses:
        raise GalleryError(f"disallowed SVG shortcut in {path}: {', '.join(bypasses)}")
    return svg, root


def dimensions(root):
    view_box = root.attrib.get("viewBox", "").replace(",", " ").split()
    if len(view_box) == 4:
        return f"{view_box[2]} × {view_box[3]}"
    return f"{root.attrib.get('width', '?')} × {root.attrib.get('height', '?')}"


def number_field(sample, name, *, minimum=0, default=None):
    value = sample.get(name, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise GalleryError(f"sample {sample.get('key', '?')}: {name} must be a number >= {minimum}")
    return value


def prepare(manifest_path, manifest):
    raw_samples = manifest.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        raise GalleryError("manifest.samples must be a non-empty array")

    prepared, seen, lane_counts = [], set(), {}
    lane_colors = OrderedDict()
    for index, sample in enumerate(raw_samples):
        if not isinstance(sample, dict):
            raise GalleryError(f"sample #{index + 1} must be an object")
        key = str(sample.get("key") or f"sample-{index + 1}")
        if key in seen:
            raise GalleryError(f"duplicate sample key: {key}")
        seen.add(key)
        model = str(sample.get("model") or "Unknown model")
        effort = str(sample.get("effort") or "")
        channel = str(sample.get("channel") or "")
        group = str(sample.get("group") or "")
        lane_key = (group, model, effort, channel)
        lane_counts[lane_key] = lane_counts.get(lane_key, 0) + 1
        attempt = sample.get("attempt", lane_counts[lane_key])
        if not isinstance(attempt, (int, str)):
            raise GalleryError(f"sample {key}: attempt must be a string or integer")

        source = Path(str(sample.get("svg") or f"{key}.svg")).expanduser()
        if not source.is_absolute():
            source = manifest_path.parent / source
        svg, root = extract_svg(source)
        names = [local_name(node.tag) for node in root.iter()]
        token_total = number_field(sample, "tokens")
        multiplier = number_field(sample, "plan_multiplier", minimum=0.000001, default=1.0)
        weighted = number_field(sample, "weighted_tokens")
        if weighted is None and token_total is not None:
            weighted = token_total * multiplier
        lane_colors.setdefault(lane_key, PALETTE[len(lane_colors) % len(PALETTE)])
        accent = valid_color(sample.get("accent"), lane_colors[lane_key])
        data_uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
        safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "-", key).strip("-") or f"sample-{index + 1}"
        tokens_exact = sample.get("tokens_exact", sample.get("token_exact", True))
        if not isinstance(tokens_exact, bool):
            raise GalleryError(f"sample {key}: tokens_exact must be true or false")
        prepared.append({
            "key": key,
            "model": model,
            "effort": effort,
            "channel": channel,
            "group": group,
            "lane_key": lane_key,
            "attempt": attempt,
            "label": str(sample.get("label") or ""),
            "accent": accent,
            "data_uri": data_uri,
            "download_name": safe_key + ".svg",
            "dimensions": dimensions(root),
            "elements": len(names) - 1,
            "shapes": len(SHAPE_RE.findall(svg)),
            "paths": names.count("path"),
            "bytes": len(svg.encode()),
            "latency_ms": number_field(sample, "latency_ms"),
            "tokens": token_total,
            "tokens_exact": tokens_exact,
            "plan_multiplier": multiplier,
            "weighted_tokens": weighted,
        })
    return prepared


def metric(label, value):
    return f"<div><dt>{text(label)}</dt><dd>{text(value)}</dd></div>"


def render_card(sample, labels, token_label):
    attempt_label = sample["label"] or labels["attempt"].format(n=sample["attempt"])
    aria = f"{sample['model']}, {attempt_label}, {labels['zoom']}"
    metrics = [
        metric(labels["canvas"], sample["dimensions"]),
        metric(labels["shapes"], sample["shapes"]),
        metric(labels["paths"], sample["paths"]),
        metric(labels["size"], f"{sample['bytes'] / 1024:.1f} KB"),
    ]
    if sample["latency_ms"] is not None:
        metrics.append(metric(labels["latency"], f"{sample['latency_ms'] / 1000:.1f}s"))

    usage = ""
    if sample["tokens"] is not None:
        approx = "" if sample["tokens_exact"] else "≈"
        usage = f"""
        <div class="usage">
          <div><span>{text(labels['raw_tokens'])}</span><strong>{approx}{full_number(sample['tokens'])}</strong></div>
          <div><span>{text(labels['weighted_tokens'])}</span><strong>{approx}{full_number(sample['weighted_tokens'])}</strong><small>{text(token_label)}</small></div>
        </div>"""

    return f"""
    <article class="sample" style="--accent:{sample['accent']}">
      <div class="sample-head">
        <h3>{text(attempt_label)}</h3>
        <a class="download" href="{sample['data_uri']}" download="{text(sample['download_name'])}">{text(labels['download'])}</a>
      </div>
      <button class="art" type="button" data-key="{text(sample['key'])}" aria-label="{text(aria)}">
        <img src="{sample['data_uri']}" alt="{text(aria)}">
        <span class="zoom-hint">{text(labels['zoom'])}</span>
      </button>
      {usage}
      <dl class="facts">{''.join(metrics)}</dl>
    </article>"""


def render_lane(items, labels, token_label):
    first = items[0]
    subparts = []
    if first["effort"]:
        subparts.append(f"<p><strong>{text(first['effort'])}</strong> {text(labels['effort'])}</p>")
    if first["channel"]:
        subparts.append(f"<p>{text(labels['channel'])}: {text(first['channel'])}</p>")
    lane_identity = "\x1f".join(first["lane_key"]).encode("utf-8")
    lane_id = "lane-" + hashlib.sha256(lane_identity).hexdigest()[:12]
    return f"""
    <section class="lane" style="--accent:{first['accent']};--sample-count:{len(items)}" aria-labelledby="{lane_id}">
      <header class="lane-head">
        <div class="model-mark" aria-hidden="true"><span></span><span></span></div>
        <div><h2 id="{lane_id}">{text(first['model'])}</h2>{''.join(subparts)}</div>
      </header>
      <div class="samples">{''.join(render_card(item, labels, token_label) for item in items)}</div>
    </section>"""


def render_summaries(lanes, labels, token_label):
    summaries = []
    all_samples = [sample for items in lanes.values() for sample in items]
    for items in list(lanes.values()) + ([all_samples] if len(lanes) > 1 else []):
        known = [sample for sample in items if sample["tokens"] is not None]
        if not known:
            continue
        first = items[0]
        is_total = items is all_samples
        name = labels["total"] if is_total else first["model"]
        if not is_total and first["effort"]:
            name += f" / {first['effort']}"
        if not is_total and first["channel"]:
            name += f" / {first['channel']}"
        exact = all(sample["tokens_exact"] for sample in known) and len(known) == len(items)
        approx = "" if exact else "≈"
        raw = sum(sample["tokens"] for sample in known)
        weighted = sum(sample["weighted_tokens"] for sample in known)
        partial = f" · {labels['known_only']}" if len(known) != len(items) else ""
        accent = "#0a2540" if is_total else first["accent"]
        summaries.append(f"""
        <div class="usage-total" style="--accent:{accent}">
          <span>{text(name)} · {len(known)} {text(labels['samples'])}</span>
          <strong>{approx}{compact_number(weighted)}</strong>
          <small>{text(token_label)} · {text(labels['raw_prefix'])} {approx}{compact_number(raw)}{text(partial)}</small>
        </div>""")
    return "<section class=\"usage-summary\" aria-label=\"Token usage summary\">" + "".join(summaries) + "</section>" if summaries else ""


def render(manifest_path, output_path, template_path, lang):
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GalleryError(f"cannot read manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise GalleryError("manifest root must be an object")
    labels = LABELS[lang]
    samples = prepare(manifest_path, manifest)
    lanes = OrderedDict()
    for sample in samples:
        lanes.setdefault(sample["lane_key"], []).append(sample)

    basis = manifest.get("token_basis") or {}
    if not isinstance(basis, dict):
        raise GalleryError("manifest.token_basis must be an object")
    token_label = str(basis.get("label") or labels["default_token_basis"])
    basis_note = text(basis.get("note") or "")
    basis_url = source_link(basis.get("source_url"))
    if basis_url:
        basis_note += (" " if basis_note else "") + f'<a href="{text(basis_url)}">{text(basis.get("source_label") or basis_url)}</a>'

    title = str(manifest.get("title") or labels["default_title"])
    subtitle = str(manifest.get("subtitle") or labels["default_subtitle"])
    prompt = str(manifest.get("prompt") or "Generate an SVG of a pelican riding a bicycle.")
    transport = str(manifest.get("transport") or "")
    exact_note = labels["exact_note"] if any(not sample["tokens_exact"] for sample in samples if sample["tokens"] is not None) else ""
    raw_notes = manifest.get("notes", [])
    if not isinstance(raw_notes, list):
        raise GalleryError("manifest.notes must be an array")
    notes = [str(note) for note in raw_notes]
    footnote_parts = []
    if basis_note:
        footnote_parts.append(f'<p class="footnote">{basis_note}</p>')
    footnote_parts.extend(
        f'<p class="footnote">{text(note)}</p>'
        for note in (exact_note, labels["method"], *notes) if note
    )
    footnote_html = "".join(footnote_parts)
    transport_html = f'<span class="direct">✓ {text(transport)}</span>' if transport else ""
    payload = json.dumps([
        {"key": sample["key"], "model": sample["model"], "effort": sample["effort"],
         "display_label": sample["label"] or labels["attempt"].format(n=sample["attempt"]),
         "src": sample["data_uri"]}
        for sample in samples
    ], ensure_ascii=False).replace("</", "<\\/")

    try:
        page = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GalleryError(f"cannot read template {template_path}: {exc}") from exc
    replacements = {
        "{{LANG}}": lang,
        "{{TITLE}}": text(title),
        "{{SUBTITLE}}": text(subtitle),
        "{{PROMPT}}": text(prompt),
        "{{SAME_PROMPT}}": text(labels["same_prompt"]),
        "{{MODEL_COUNT}}": str(len({sample["model"] for sample in samples})),
        "{{MODELS_LABEL}}": text(labels["models"]),
        "{{SAMPLE_COUNT}}": str(len(samples)),
        "{{SAMPLES_LABEL}}": text(labels["samples"]),
        "{{TRANSPORT}}": transport_html,
        "{{SUMMARIES}}": render_summaries(lanes, labels, token_label),
        "{{LANES}}": "".join(render_lane(items, labels, token_label) for items in lanes.values()),
        "{{FOOTNOTES}}": footnote_html,
        "{{CLOSE}}": text(labels["close"]),
        "{{PAYLOAD}}": payload,
    }
    for marker, value in replacements.items():
        page = page.replace(marker, value)
    leftovers = sorted(set(re.findall(r"{{[A-Z_]+}}", page)))
    if leftovers:
        raise GalleryError("unresolved template markers: " + ", ".join(leftovers))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return samples, lanes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("manifest", type=Path, help="JSON manifest describing SVG samples")
    parser.add_argument("--out", type=Path, help="output HTML (default: MANIFEST directory/index.html)")
    parser.add_argument("--template", type=Path, help="HTML template override")
    parser.add_argument("--lang", choices=sorted(LABELS), default="zh")
    parser.add_argument("--open", action="store_true", help="open the rendered page in the default browser")
    args = parser.parse_args(argv)
    manifest_path = args.manifest.expanduser().resolve()
    output_path = (args.out.expanduser().resolve() if args.out else manifest_path.parent / "index.html")
    template_path = (args.template.expanduser().resolve() if args.template else Path(__file__).with_name("templates") / "gallery.html")
    try:
        samples, lanes = render(manifest_path, output_path, template_path, args.lang)
    except GalleryError as exc:
        parser.error(str(exc))
    print(f"{len(samples)} samples / {len(lanes)} lanes -> {output_path}")
    if args.open:
        webbrowser.open(output_path.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
