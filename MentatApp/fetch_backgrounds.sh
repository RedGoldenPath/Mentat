#!/bin/bash
# Mentat backgrounds
#
# Folder layout (next to the app source):
#   background/     -> full-size images pulled from Pexels / Pixabay
#   ui-examples/    -> reference screenshots I look at for design direction
#   Resources/      -> optimized images actually bundled into Mentat.app
#
# Drop new desert photos into ./backgrounds (any name), run this script to
# downscale them into ./Resources, then ./build.sh to rebuild the app.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$DIR/backgrounds"
OUT="$DIR/Resources"
mkdir -p "$SRC" "$OUT"

# Which source maps to which mode:
#   day  (light mode)            -> a bright colour desert
#   mono (dark + black & white)  -> a dark / B&W desert
DAY=$(ls "$SRC"/*day* 2>/dev/null | head -1 || true)
MONO=$(ls "$SRC"/*night* "$SRC"/*mono* "$SRC"/*bw* 2>/dev/null | head -1 || true)

[ -n "$DAY" ]  && cp "$DAY"  "$OUT/bg-desert-day.jpg"  || echo "no *day* image in $SRC" >&2
[ -n "$MONO" ] && cp "$MONO" "$OUT/bg-desert-mono.jpg" || echo "no *night*/*mono* image in $SRC" >&2

sips -Z 2400 "$OUT/bg-desert-day.jpg"  >/dev/null 2>&1 || true
sips -Z 2400 "$OUT/bg-desert-mono.jpg" >/dev/null 2>&1 || true
echo "bundled backgrounds:"
ls -la "$OUT"
