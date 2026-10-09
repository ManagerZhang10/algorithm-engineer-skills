# Pelican Bicycle Eval

**Repeatable, inspectable SVG trials for models, reasoning levels, usage, and API
channels.** Give every configuration the same pelican-on-a-bicycle prompt, preserve
the first responses, and compare the drawings plus the evidence around them.

> [中文说明](README.zh-CN.md)

![dashboard](assets/board.png)

The screenshot shows the proxy-check mode: one model and two channels. The general
gallery also compares different models and effort levels, with any number of
independent samples.

| Mode | Use it for | Entry point |
|---|---|---|
| Model / effort comparison | Visual quality, SVG validity, repeatability, latency, raw and weighted usage | `pelican_eval.py render` |
| Proxy integrity check | Hidden input injection, reasoning suppression, response metadata drift | `pelican_eval.py proxy-check` |

## Model and effort comparison

The neutral renderer accepts SVGs produced by Codex, another harness, or a manual
run. It makes no API calls:

```bash
python3 pelican_eval.py render /path/to/manifest.json --out /path/to/board.html --open
```

The manifest can contain any number of models and attempts, plus optional effort,
channel, latency, raw token usage, and a caller-supplied plan multiplier. Matching
samples become one lane; every drawing is embedded into a portable HTML file with
zoom and download controls. See [`docs/gallery.md`](docs/gallery.md) for the schema.

Run at least three independent attempts when judging stability, preserve failed
first responses, and label unequal reasoning settings explicitly. This is a useful
probe of spatial composition, SVG coding, instruction following, and output
stability — not a general-intelligence score. The canonical single prompt is now
saturated on many frontier models, so harder studies should vary animals, vehicles,
and constraints instead of reading too much into one pretty pelican.

## Proxy integrity mode

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

Every one of those lands **on the board itself**, under each drawing — not only in
the JSON snapshot. A cell reads `in 129 (+97)` when the proxy stapled 97 tokens of
hidden context onto your prompt, `think 0` when the channel reported zero thinking
tokens, `think —` when it reports nothing at all (**not** the same claim), and
`9 non-standard usage fields` when the reseller's own accounting leaks through.

**One prerequisite: configure the same model on at least two lanes** — a trusted
direct-to-vendor lane as your baseline, plus the proxy under test. Without a
baseline every number is just an absolute value. That's also the key difference
from fingerprinting tools: they depend on community-maintained reference
fingerprints, whereas you usually have a real direct account to compare against.

Mark the baseline explicitly with `PB_<NAME>_BASELINE=true`. Absent that flag, the
board falls back to the lane whose channel name contains `direct` / 「直连」.

> **Deltas are computed only between lanes on the same model.** Never across
> models: tokenizers differ per vendor, so a cross-model input-token difference
> measures the tokenizer, not the proxy. A model with only one lane, or no
> identifiable baseline, simply shows no delta — the tool does not guess.

## Running the proxy check

No dependencies. Python standard library only. Budget **15–25 minutes** the first
time — most of it is collecting keys and base URLs for the lanes you want to
compare. A round itself takes one to two minutes (57 s and 113 s measured on
four-lane runs, 2026-09-13); reasoning models spend most of it thinking.

```bash
git clone https://github.com/ManagerZhang10/pelican-bicycle-eval
cd pelican-bicycle-eval

mkdir -p ~/.config/pelican-bicycle-eval
cp lanes.env.example ~/.config/pelican-bicycle-eval/lanes.env
chmod 600 ~/.config/pelican-bicycle-eval/lanes.env   # it holds API keys
$EDITOR ~/.config/pelican-bicycle-eval/lanes.env

python3 pelican_eval.py proxy-check --open
```

The last command runs every lane concurrently, writes one self-contained HTML file
(the SVGs are inlined as data URIs, so the board survives being copied or emailed
on its own), and opens it in your browser.

Keys already in your shell? Reference them instead of copying them into the file:

```bash
PB_OPENAI_DIRECT_API_KEY=${OPENAI_API_KEY}
```

`${VAR}` is expanded from **the environment of the shell that runs the script**,
not from lines inside the config file — so `export` it (or `set -a; source
your.env; set +a`) before running, otherwise the script stops and tells you which
variable was unset.

Put it on a timer and it becomes continuous monitoring — the script takes a lock,
so a slow round never stacks on the next one.

```bash
python3 pelican_eval.py proxy-check render --open   # rebuild from snapshots, no API spend
```

### Options

| Flag | Default | What it does |
|---|---|---|
| `render` | — | Rebuild the board from existing snapshots, no API calls |
| `--config PATH` | `~/.config/pelican-bicycle-eval/lanes.env` | Lane config to read (must be `chmod 600`) |
| `--out DIR` | `~/.local/share/pelican-bicycle-eval/proxy-check` | Where snapshots and `index.html` go |
| `--keep N` | `3` | How many recent rounds to keep and show |
| `--lang zh\|en` | `zh` | Board language |
| `--anonymize` | off | Collapse channel names to "Proxy A / Proxy B" |
| `--open` | off | Open the board when done |
| `--help` | — | Print usage |

Two configs side by side is just two `--config` / `--out` pairs:

```bash
python3 pelican_eval.py proxy-check --config ~/lanes-work.env --out ~/boards/work --keep 10
```

An unknown flag is a hard error with a suggestion, never a silent no-op — a typo
in `--anonymize` must not quietly publish a reseller's real name.

## Why a pelican

"Generate an SVG of a pelican riding a bicycle" is
[Simon Willison's informal benchmark](https://github.com/simonw/pelican-bicycle),
running since 2024. It packs awkward geometry — body proportions, frame structure,
and where legs meet pedals — into one short, human-readable prompt. That makes it a
useful visual smoke test for spatial reasoning, structural planning, SVG coding,
and long-output stability.

The prompt is fixed verbatim so that input tokens are a stable ruler across lanes,
and so results stay comparable with the public corpus of pelican SVGs. It is no
longer a fresh or comprehensive benchmark: Hugging Face's
[scaled OpenEnv version](https://github.com/huggingface/openenv/blob/main/docs/source/environments/pelican_svg.md)
reports a saturated canonical task and explicitly avoids treating it as a model
ranking.

**But a picture alone proves nothing.** Temperature is non-zero and variance is
high. The drawing is the sensory reference; the table above is the verdict.

## Sharing results

```bash
python3 pelican_eval.py proxy-check render --anonymize --lang en
```

Channel names collapse to "Proxy A / Proxy B"; direct-to-vendor lanes keep their
names. The screenshot at the top of this README was produced that way —
**the finding is worth sharing, the vendor's name doesn't have to be.**

## Scope

The gallery compares observable output, repeatability, and recorded usage for the
configurations you name. It does not prove a model's general intelligence or the
identity behind an endpoint. Proxy-check mode measures **channel integrity** — what
happened to a request in transit — and does not perform model fingerprinting.

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
