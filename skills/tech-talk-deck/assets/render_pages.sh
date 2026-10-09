#!/bin/bash
# 只截指定页，逐页串行，不整本跑：
#   ./render_pages.sh 57 58 59         → /tmp/deck-pages/slide-57.png ...
#   DECK=other.html OUT=/tmp/x ./render_pages.sh 3
# 默认渲染脚本同目录的 deck.html；Chrome 路径不同用 CHROME=/path/to/chrome 指定。
set -u
[ $# -gt 0 ] || { echo "用法: $0 <页码> [页码...]" >&2; exit 1; }
cd "$(dirname "$0")"
DECK="${DECK:-deck.html}"
OUT="${OUT:-/tmp/deck-pages}"
[ -f "$DECK" ] || { echo "找不到 $DECK" >&2; exit 1; }
DECK_URI="file://$(cd "$(dirname "$DECK")" && pwd)/$(basename "$DECK")"

C=""
for cand in "${CHROME:-}" \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/Applications/Chromium.app/Contents/MacOS/Chromium" \
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
  /usr/bin/google-chrome /usr/bin/chromium /usr/bin/chromium-browser; do
  if [ -n "$cand" ] && [ -x "$cand" ]; then C="$cand"; break; fi
done
[ -n "$C" ] || { echo "找不到 Chrome，用 CHROME=/path/to/chrome 指定" >&2; exit 1; }

mkdir -p "$OUT"
for i in "$@"; do
  png="$OUT/slide-$i.png"
  "$C" --headless=new --disable-gpu --hide-scrollbars --virtual-time-budget=4000 \
    --force-device-scale-factor=1 --window-size=1920,1080 \
    --screenshot="$png" "$DECK_URI#$i" >/dev/null 2>&1
  if [ -s "$png" ]; then echo "$png"; else echo "✗ slide-$i 没截出来" >&2; fi
done
