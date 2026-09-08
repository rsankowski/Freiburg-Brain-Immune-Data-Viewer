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

D=$(python3 -c "import json;print(json.load(open('$ROOT/configs/index.json'))['datasets'][0]['key'])")
S=$(python3 -c "
import json;ds=json.load(open('$ROOT/configs/index.json'))['datasets']
print(next(d['key'] for d in ds if 'SPATIAL' in d['embeddings']))")

shot viewer_night.png 1600,1150 "$BASE/viewer.html?dataset=$D&base=$BASE/zarr&theme=dark"
shot viewer_day.png   1600,1150 "$BASE/viewer.html?dataset=$D&base=$BASE/zarr&theme=light"
shot shot_cosmx.png   1600,1150 "$BASE/viewer.html?dataset=$S&base=$BASE/zarr&theme=dark"
shot index_page.png   1400,1650 "$BASE/index.html"
echo "done"
