# pelican-proxy-check

**Is your API proxy quietly degrading the model you paid for?** Make every lane draw
the same pelican on a bicycle, then read what the server reports about itself.

> [中文说明](README.zh-CN.md)

![dashboard](assets/board.png)

Two lanes, one model, one prompt. Left: through a reseller. Right: straight to the
vendor. The pictures are the hook — the numbers underneath them are the evidence.

## The problem

When you buy API access through a proxy, gateway, or reseller, you can't see what
actually reaches the vendor. Four things commonly happen to your request:

- it gets routed to a cheaper model
- it gets served from a quantized copy
- a hidden system prompt gets stapled to it
- reasoning gets switched off

Behavioral-fingerprint tools can catch the first two. They **misclassify the last
two** — their own docs admit that a swapped system prompt shifts the output
distribution about as much as a swapped model does.

This tool takes a different route: **it doesn't guess. It reads the numbers the
server reports about its own response.**

| Signal | What it proves |
|---|---|
| `prompt_tokens` delta between lanes on the same model | Exactly how many tokens of hidden context were injected |
| `reasoning_tokens` at a matched effort level | Whether reasoning was suppressed |
| Non-standard fields in `usage` | The proxy layer's own implementation fingerprint |
| Response id prefix | Whether the response was rewritten or forged |

**One prerequisite: configure the same model on at least two lanes** — a trusted
direct-to-vendor lane as your baseline, plus the proxy under test. Without a
baseline every number is just an absolute value. That's also the key difference
from fingerprinting tools: they depend on community-maintained reference
fingerprints, whereas you usually have a real direct account to compare against.

## One minute to a dashboard

No dependencies. Python standard library only.

```bash
git clone https://github.com/ManagerZhang10/pelican-proxy-check
cd pelican-proxy-check

mkdir -p ~/.config/pelican-proxy-check
cp lanes.env.example ~/.config/pelican-proxy-check/lanes.env
chmod 600 ~/.config/pelican-proxy-check/lanes.env   # it holds API keys
$EDITOR ~/.config/pelican-proxy-check/lanes.env

python3 pelican_proxy_check.py --open
```

The last command runs every lane concurrently, writes a self-contained HTML board,
and opens it in your browser. Keys already in your shell? Reference them instead of
copying them into the file:

```bash
PB_OPENAI_DIRECT_API_KEY=${OPENAI_API_KEY}
```

Put it on a timer and it becomes continuous monitoring — the script takes a lock,
so a slow round never stacks on the next one.

```bash
python3 pelican_proxy_check.py render --open   # rebuild the board from existing snapshots, no API spend
```

## Why a pelican

"Generate an SVG of a pelican riding a bicycle" is Simon Willison's informal
benchmark, running since 2024. The scene is essentially absent from training data,
so a model has to actually work out the geometry — body proportions, frame
structure, where the legs meet the pedals — rather than recite something. One
prompt exercises spatial reasoning, structural planning, and long-output stability
at once, and anyone can see a bad result without reading a score.

The prompt is fixed verbatim so that input tokens are a stable ruler across lanes,
and so results stay comparable with the public corpus of pelican SVGs.

**But a picture alone proves nothing.** Temperature is non-zero and variance is
high. The drawing is the sensory reference; the table above is the verdict.

## Sharing results

```bash
python3 pelican_proxy_check.py render --anonymize
```

Channel names collapse to "Proxy A / Proxy B"; direct-to-vendor lanes keep their
names. The screenshot at the top of this README was produced that way —
**the finding is worth sharing, the vendor's name doesn't have to be.**

## Scope

This measures **channel integrity** — what happened to your request in transit. It
does **not** identify **model identity** — which model actually sits behind the
endpoint. That's what behavioral fingerprinting is for; the two are complementary.

A single anomalous round may just be jitter. Telling *constant* injection from
*intermittent* injection takes at least three rounds — and that distinction is the
most valuable output here. A constant offset can be subtracted as a known constant.
One that swings means multiple pools behind random routing, which means **the same
prompt does not produce reproducible behavior.**

## Notes

- [`docs/raw-data.md`](docs/raw-data.md) — the snapshot format: every field in `run.json`, and how to compute injection from it
- [`SKILL.md`](SKILL.md) — agent-facing instructions (works as a Claude Code / Codex skill)
- [`lanes.env.example`](lanes.env.example) — every field documented, including each
  vendor's thinking knob (they are not interchangeable)

MIT licensed.
