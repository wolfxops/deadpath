#!/usr/bin/env bash
# Render Product Hunt assets at exact required sizes, then exit Chrome.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/src"
OUT="$ROOT/gallery"
THUMB="$ROOT/thumbnail"
mkdir -p "$OUT" "$THUMB"
CHROME="${CHROME:-google-chrome}"

shot() {
  local html="$1" dest="$2" w="$3" h="$4" scale="$5"
  local data
  data="$(mktemp -d /tmp/ph-chrome-XXXXXX)"
  mkdir -p "$(dirname "$dest")"
  rm -f "$dest"
  timeout 25s "$CHROME" \
    --headless=new \
    --no-sandbox \
    --disable-gpu \
    --disable-dev-shm-usage \
    --disable-background-networking \
    --disable-sync \
    --disable-extensions \
    --disable-component-update \
    --disable-default-apps \
    --disable-features=Translate,BackForwardCache \
    --hide-scrollbars \
    --no-first-run \
    --no-default-browser-check \
    --user-data-dir="$data" \
    --force-device-scale-factor="$scale" \
    --window-size="$w,$h" \
    --screenshot="$dest" \
    "file://${html}" >/tmp/ph-chrome.log 2>&1 || true
  rm -rf "$data"
  if [[ ! -s "$dest" ]]; then
    echo "failed $dest" >&2
    tail -20 /tmp/ph-chrome.log >&2
    return 1
  fi
  echo "wrote $dest ($(wc -c < "$dest") bytes)"
}

shot "$SRC/00-thumbnail.html" "$THUMB/deadpath-thumbnail-240.png" 240 240 1
shot "$SRC/01-hero.html" "$OUT/01-deadpath-dead-code-detection-for-coding-agents.png" 1270 760 2
shot "$SRC/02-problem.html" "$OUT/02-deadpath-unused-code-false-positives.png" 1270 760 2
shot "$SRC/03-engine.html" "$OUT/03-deadpath-confidence-score-devils-advocate.png" 1270 760 2
shot "$SRC/04-coverage.html" "$OUT/04-deadpath-16-languages-45-frameworks.png" 1270 760 2
shot "$SRC/05-safety.html" "$OUT/05-deadpath-never-auto-delete-ci.png" 1270 760 2
python3 - << PY
import struct
from pathlib import Path
for p in sorted(Path("$THUMB").glob("*.png")) + sorted(Path("$OUT").glob("*.png")):
    w, h = struct.unpack(">II", p.read_bytes()[16:24])
    print(f"{p.name:60} {w}x{h}")
PY
