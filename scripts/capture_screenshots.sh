#!/usr/bin/env bash
# Capture the viewer screenshots used in the Application Note figure.
# Requires scripts/serve_local.py to be running on port 8787.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHROME="${CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
BASE="http://localhost:8787"
FLAGS=(--headless=new --no-sandbox --use-gl=angle --use-angle=swiftshader
       --enable-unsafe-swiftshader --virtual-time-budget=150000)

shot () {  # shot <output> <size> <url>
  echo "  $1"
  "$CHROME" "${FLAGS[@]}" --window-size="$2" --screenshot="$ROOT/$1" "$3" 2>/dev/null
}

curl -sf "$BASE/index.html" >/dev/null || {
  echo "preview server not running: python scripts/serve_local.py" >&2; exit 1; }

# Pinned: the figure caption describes these two datasets, and index.json order
# changes whenever publications are added. Override with FIG_DATASET / FIG_SPATIAL.
D="${FIG_DATASET:-chhatbar_et_al_2026__immune_final_2_23012025}"
S="${FIG_SPATIAL:-chhatbar_et_al_2026__figure_2_nanostring_cosmx_v1}"

shot viewer_night.png 1600,1150 "$BASE/viewer.html?dataset=$D&base=$BASE/zarr&theme=dark"
shot viewer_day.png   1600,1150 "$BASE/viewer.html?dataset=$D&base=$BASE/zarr&theme=light"
shot shot_cosmx.png   1600,1150 "$BASE/viewer.html?dataset=$S&base=$BASE/zarr&theme=dark"
shot index_page.png   1400,1650 "$BASE/index.html"
echo "done"
