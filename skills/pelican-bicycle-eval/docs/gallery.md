# Reusable comparison gallery / 通用横评看板

Pelican Bicycle Eval's gallery renderer turns a small JSON manifest plus SVG files into one
self-contained HTML page. It makes no API calls and has no package dependencies.
Use it when the images were collected by Codex, another script, or by hand rather
than by `pelican_proxy_check.py` itself.

Pelican Bicycle Eval 的 gallery 渲染器把一份 JSON 清单和若干 SVG 生成为一个自包含 HTML。它不会调用模型，
也不需要安装依赖；适合展示由 Codex、其他采集器或手工整理出的横评结果。

```bash
python3 pelican_eval.py render /path/to/manifest.json --out /path/to/board.html --open
```

Omit `--out` to write `index.html` next to the manifest. Add `--lang en` for an
English interface. Every relative SVG path is resolved from the manifest's
directory. A source may be a clean `.svg` or a raw text response containing one
complete `<svg>...</svg>` element.

不传 `--out` 时，页面默认写到 manifest 同目录的 `index.html`；英文界面加 `--lang en`。
SVG 相对路径以 manifest 所在目录为准。源文件既可以是纯 `.svg`，也可以是包含一段完整
`<svg>...</svg>` 的原始文本响应。

## Minimal manifest / 最小清单

```json
{
  "title": "GPT-6 low vs GPT-5.6 xhigh",
  "subtitle": "同题各画三次；原始 SVG 未经人工修图。",
  "prompt": "Generate an SVG of a pelican riding a bicycle.",
  "transport": "Official direct connection",
  "token_basis": {
    "label": "GPT-5.6 Sol-equivalent tokens",
    "note": "GPT-6 usage is converted at 2.5× for this run.",
    "source_url": "https://learn.chatgpt.com/docs/pricing",
    "source_label": "Usage-rate source"
  },
  "notes": [
    "The multiplier is supplied by this manifest; the renderer never guesses one."
  ],
  "samples": [
    {
      "key": "astra-1",
      "model": "Model A",
      "effort": "low",
      "channel": "Official",
      "attempt": 1,
      "svg": "astra-1.svg",
      "accent": "#0077b6",
      "tokens": 9446,
      "tokens_exact": false,
      "plan_multiplier": 2.5,
      "latency_ms": 61200
    },
    {
      "key": "sol-1",
      "model": "Model B",
      "effort": "xhigh",
      "channel": "Official",
      "attempt": 1,
      "svg": "sol-1.svg",
      "accent": "#f25c2a",
      "tokens": 10194,
      "tokens_exact": true,
      "plan_multiplier": 1
    }
  ]
}
```

Repeat entries in `samples` as many times as needed. Samples with the same
`group`, `model`, `effort`, and `channel` share one visual lane, in manifest
order. Use `group` when otherwise identical labels should stay in separate lanes.

按需增加 `samples` 即可，不限定模型数和每组次数。`group`、`model`、`effort`、`channel`
完全相同的样本会按 manifest 顺序进入同一行；需要把同名配置拆成两行时设置不同的 `group`。

## Sample fields / 样本字段

| Field | Required | Meaning |
| --- | --- | --- |
| `key` | recommended | Unique sample id; also supplies the default `<key>.svg` path |
| `model` | recommended | Visible model name |
| `effort` | no | Visible reasoning level |
| `channel` | no | Visible collection channel |
| `group` | no | Invisible lane separator for otherwise identical configurations |
| `attempt` / `label` | no | Card heading; `label` wins when both exist |
| `svg` | no | SVG or raw-response path, relative to the manifest by default |
| `accent` | no | Six-digit hex lane color; otherwise selected from the built-in palette |
| `tokens` | no | Raw total tokens for this sample |
| `tokens_exact` | no | `false` adds `≈`; defaults to `true` (`token_exact` is accepted for old manifests) |
| `plan_multiplier` | no | Multiplier applied to `tokens`; defaults to `1` |
| `weighted_tokens` | no | Explicit weighted result, overriding `tokens × plan_multiplier` |
| `latency_ms` | no | End-to-end latency in milliseconds |

Token cards disappear when `tokens` is omitted. Multipliers and labels are input
data, not product knowledge embedded in the renderer. That keeps a saved board
reproducible even if pricing or plan accounting changes later.

不填 `tokens` 就不显示消耗卡片。倍率和口径名称都是清单数据，渲染器不会自行推断；即使未来
定价或套餐换算变化，旧看板仍能复现当时采用的口径。

## Safety and output

The renderer strictly parses XML and rejects `<image>`, `<text>`, `<script>`,
`<foreignObject>`, external `href`, and similar shortcuts, matching the main
tool's SVG rules. SVGs are embedded as data URIs; the output HTML can be opened
or copied on its own. Click a drawing to enlarge it, or use its download link to
recover the embedded SVG.

渲染器会严格解析 XML，并按主工具相同的规则拒绝位图、文字、脚本、`foreignObject`、外部
`href` 等捷径。生成页用 data URI 内联所有 SVG，可以单文件打开和转移；点击图片可放大，
也可从卡片直接下载内嵌的原始 SVG。
