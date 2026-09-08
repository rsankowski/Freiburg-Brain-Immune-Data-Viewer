#!/usr/bin/env python
"""Stage 8 — generate the static Vitessce site into docs/ (GitHub Pages).

    python scripts/08_site.py [--dataset KEY] [--base-url URL]

Produces:
    docs/index.html      dataset landing page
    docs/viewer.html     full-page Vitessce viewer (?dataset=KEY[&base=URL])
    docs/configs/*.json  view configs, served alongside the page
    docs/.nojekyll

The page loads expression data from `base_url` in config/pipeline.json. Until
the S3 sync has run, use the local preview server:

    python scripts/serve_local.py
    open "http://localhost:8787/viewer.html?dataset=KEY&base=http://localhost:8787/zarr"
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))

from common import (  # noqa: E402
    BUILD_DIR, CHECK_DIR, CONFIG_DIR, ROOT, add_common_args, load_pipeline_config, log,
    read_json,
)

STAGE = "08_site"
DOCS = ROOT / "docs"
ASSETS = DOCS / "assets"
VITESSCE_VERSION = "3.4.9"
REACT_VERSION = "18.3.1"

STYLE = """
:root {
  color-scheme: light dark;
  --bg: #fbfaf8; --panel: #ffffff; --ink: #1a1a19; --muted: #6b6a66;
  --line: #e4e2dd; --accent: #7b4bd8; --accent-ink: #ffffff;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14141a; --panel: #1c1c24; --ink: #eceaf0; --muted: #9a98a6;
    --line: #2c2c36; --accent: #a284f0; --accent-ink: #14141a;
  }
}
:root[data-theme="dark"] {
  --bg: #14141a; --panel: #1c1c24; --ink: #eceaf0; --muted: #9a98a6;
  --line: #2c2c36; --accent: #a284f0; --accent-ink: #14141a;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, system-ui, sans-serif;
}
a { color: var(--accent); }
.wrap { max-width: 940px; margin: 0 auto; padding: 48px 24px 72px; }
header h1 { font-size: 30px; letter-spacing: -0.02em; margin: 0 0 8px; }
header p.lede { color: var(--muted); margin: 0 0 6px; max-width: 62ch; }
.card {
  background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
  padding: 22px 24px; margin: 22px 0;
}
.card h2 { margin: 0 0 4px; font-size: 20px; letter-spacing: -0.01em; }
.card .paper { color: var(--muted); font-size: 13px; margin: 0 0 14px; }
.stats { display: flex; flex-wrap: wrap; gap: 26px; margin: 16px 0 20px; }
.stat .n { font-size: 20px; font-variant-numeric: tabular-nums; font-weight: 600; }
.stat .k { font-size: 11px; text-transform: uppercase; letter-spacing: 0.07em; color: var(--muted); }
.btn {
  display: inline-block; background: var(--accent); color: var(--accent-ink);
  text-decoration: none; padding: 9px 18px; border-radius: 8px; font-weight: 600; font-size: 14px;
}
.btn.sec { background: transparent; color: var(--ink); border: 1px solid var(--line); font-weight: 500; }
.crumb { margin: 0 0 10px; font-size: 13px; }
.pubcard { display: grid; grid-template-columns: 210px 1fr; gap: 22px; align-items: start; }
@media (max-width: 640px) { .pubcard { grid-template-columns: 1fr; } }
.ga { display: block; border: 1px solid var(--line); border-radius: 8px; overflow: hidden;
      background: #fff; }
.ga img { display: block; width: 100%; height: auto; }
.ga.wide { max-width: 100%; margin: 0 0 22px; padding: 10px; }
.cite { font-size: 12.5px; color: var(--muted); margin: 0 0 6px;
        text-transform: uppercase; letter-spacing: 0.06em; }
.arttitle { margin: 0 0 12px; font-size: 15.5px; line-height: 1.45; }
.arttitle a { text-decoration: none; }
.arttitle a:hover { text-decoration: underline; }
.datasetlist { color: var(--muted); font-size: 14px; }
.modality { display: inline-block; font-size: 12px; color: var(--accent);
            border: 1px solid var(--accent); border-radius: 999px;
            padding: 2px 10px; margin: 0 0 10px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 14px; }
.acc { font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
       color: var(--muted); border: 1px solid var(--line); border-radius: 6px;
       padding: 4px 9px; text-decoration: none; }
.acc:hover { border-color: var(--accent); color: var(--accent); }
.acc.more { border-style: dashed; }
.crumb a { text-decoration: none; }
.card h2 a { color: inherit; text-decoration: none; }
.card h2 a:hover { color: var(--accent); }
.tags { display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 18px; }
.tag {
  font-size: 12px; color: var(--muted); border: 1px solid var(--line);
  border-radius: 999px; padding: 2px 10px; white-space: nowrap;
}
pre {
  background: var(--bg); border: 1px solid var(--line); border-radius: 8px;
  padding: 12px 14px; overflow-x: auto; font-size: 12.5px; margin: 10px 0 0;
}
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.themebtn {
  position: fixed; top: 16px; right: 16px; background: var(--panel); color: var(--ink);
  border: 1px solid var(--line); border-radius: 7px; padding: 5px 12px;
  font: inherit; font-size: 12.5px; cursor: pointer;
}
.themebtn:hover { border-color: var(--accent); color: var(--accent); }
footer { color: var(--muted); font-size: 13px; border-top: 1px solid var(--line); padding-top: 18px; margin-top: 34px; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
td, th { text-align: left; padding: 6px 10px 6px 0; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-weight: 500; }
"""

VIEWER_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #14141a; --panel: #1c1c24; --line: #2c2c36; --ink: #eceaf0;
    --muted: #9a98a6; --faint: #6f6d7a; --accent: #a284f0;
  }
  :root[data-theme="light"] {
    --bg: #fbfaf8; --panel: #ffffff; --line: #e4e2dd; --ink: #1a1a19;
    --muted: #6b6a66; --faint: #8a8884; --accent: #7b4bd8;
  }
  html, body { margin: 0; }
  html, body, #root { min-height: 100%; }
  body { background: var(--bg); color: var(--ink);
         font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
  #msg { padding: 40px 28px; max-width: 720px; }
  #msg h1 { font-size: 20px; margin: 0 0 10px; }
  #msg p { color: var(--muted); }
  #msg pre { background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
             padding: 12px; overflow-x: auto; font-size: 12.5px; }
  #msg a { color: var(--accent); }
  .bar { padding: 10px 16px; background: var(--panel); border-bottom: 1px solid var(--line);
         display: flex; gap: 14px; align-items: baseline; flex-wrap: wrap; }
  .bar b { font-weight: 600; }
  .bar span { color: var(--muted); font-size: 12.5px; }
  .bar .hint { color: var(--faint); font-size: 12px; }
  .bar label { color: var(--ink); font-size: 12.5px; display: flex; align-items: center;
               gap: 6px; cursor: pointer; user-select: none; }
  .bar .right { margin-left: auto; display: flex; gap: 14px; align-items: center; }
  .bar a { color: var(--accent); font-size: 13px; }
  .bar button {
    background: transparent; color: var(--ink); border: 1px solid var(--line);
    border-radius: 6px; padding: 3px 10px; font: inherit; font-size: 12.5px; cursor: pointer;
  }
  .bar button:hover { border-color: var(--accent); color: var(--accent); }
  #legend { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 14px;
            padding: 8px 16px; background: var(--panel); border-bottom: 1px solid var(--line);
            max-height: 76px; overflow-y: auto; }
  #legend .lg-title { color: var(--faint); font-size: 11px; text-transform: uppercase;
                      letter-spacing: 0.07em; margin-right: 4px; }
  #legend .lg { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--ink); }
  #legend .sw { width: 11px; height: 11px; border-radius: 2px; flex: none;
                border: 1px solid rgba(128,128,128,0.4); }
  #legend .none { color: var(--faint); font-size: 12.5px; }
  #vit { min-height: 200px; }
</style>
<script type="importmap">
{
  "imports": {
    "react": "https://esm.sh/react@__REACT__",
    "react/": "https://esm.sh/react@__REACT__/",
    "react-dom": "https://esm.sh/react-dom@__REACT__?deps=react@__REACT__",
    "react-dom/": "https://esm.sh/react-dom@__REACT__/",
    "react-dom/client": "https://esm.sh/react-dom@__REACT__/client?deps=react@__REACT__",
    "vitessce": "https://cdn.jsdelivr.net/npm/vitessce@__VITESSCE__/dist/index.min.js"
  }
}
</script>
</head>
<body>
<div id="root"><div id="msg"><h1>Loading viewer&hellip;</h1></div></div>
<script type="module">
import React from "react";
import { createRoot } from "react-dom/client";
import { Vitessce } from "vitessce";

const INDEX_URL = "./configs/index.json";
const params = new URLSearchParams(location.search);
const root = createRoot(document.getElementById("root"));

// --- theme -----------------------------------------------------------------
// Order of precedence: ?theme= in the URL, then the viewer's own saved choice,
// then the operating system setting.
function initialTheme() {
  const q = params.get("theme");
  if (q === "light" || q === "dark") return q;
  try {
    const saved = localStorage.getItem("theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch (e) { /* private window */ }
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}
let theme = initialTheme();
document.documentElement.dataset.theme = theme;

function panel(title, bodyHtml) {
  document.getElementById("root").innerHTML =
    `<div id="msg"><h1>${title}</h1>${bodyHtml}</div>`;
}

// Point the config's file URLs at a different host (e.g. a local preview
// server) without regenerating the config.
function rebase(config, base) {
  if (!base) return config;
  const clean = base.replace(/\/$/, "");
  for (const ds of config.datasets || []) {
    for (const f of ds.files || []) {
      f.url = f.url.replace(/^.*\/([^/]+\.zarr)/, `${clean}/$1`);
    }
  }
  return config;
}

async function reachable(url) {
  try {
    const r = await fetch(`${url}/.zattrs`, { method: "GET", mode: "cors" });
    return r.ok;
  } catch (e) {
    return false;
  }
}

(async function main() {
  const index = await (await fetch(INDEX_URL)).json();
  const key = params.get("dataset") || (index.datasets[0] || {}).key;
  const entry = index.datasets.find(d => d.key === key);
  if (!entry) {
    panel("Unknown dataset", `<p>No dataset <code>${key}</code> in the index.</p>
      <p><a href="./index.html">Back to the dataset list</a></p>`);
    return;
  }

  const config = rebase(await (await fetch(`./configs/${key}.json`)).json(), params.get("base"));
  const storeUrl = config.datasets[0].files[0].url;

  if (!(await reachable(storeUrl))) {
    panel("Data store not reachable", `
      <p>The viewer loaded, but the expression data at</p>
      <pre>${storeUrl}</pre>
      <p>could not be fetched. Either the S3 sync has not run yet, or CORS is not
      configured for this origin.</p>
      <p><b>To present from this machine right now:</b></p>
      <pre>python scripts/serve_local.py</pre>
      <p>then open
      <a href="./viewer.html?dataset=${key}&base=http://localhost:8787/zarr">this local link</a>.</p>
      <p><a href="./index.html">Back to the dataset list</a></p>`);
    return;
  }

  document.getElementById("root").innerHTML =
    `<div class="bar"><b>${entry.title}</b><span>${entry.n_cells.toLocaleString()} cells &middot;
      ${entry.n_genes.toLocaleString()} genes &middot; ${entry.paper || ""}</span>
      <span class="hint">left: metadata &middot; right: ${entry.modality || "gene expression"}</span>
      <label><input type="checkbox" id="summary"> Summary plots</label>
      <span class="right">
        <button id="themeBtn" type="button"></button>
        <a href="./index.html">All datasets</a>
      </span></div>
      <div id="legend"></div><div id="vit"></div>`;

  const SUMMARY_VIEWS = ["obsSetSizes", "obsSetFeatureValueDistribution"];
  let showSummary = true;
  try {
    const saved = localStorage.getItem("summaryPlots");
    if (saved !== null) showSummary = saved === "1";
  } catch (e) { /* private window: fall back to the default */ }

  // The config ships with the violin row; hiding it means dropping that view
  // and giving the rows above their space back.
  function withSummary(cfg, show) {
    const c = JSON.parse(JSON.stringify(cfg));
    if (show) return c;
    c.layout = c.layout.filter(v => !SUMMARY_VIEWS.includes(v.component));
    for (const v of c.layout) {
      if (v.component === "scatterplot") { v.y = 0; v.h = 8; }
      else { v.y = 8; v.h = 4; }
    }
    return c;
  }

  // Legend for the metadata map. Vitessce keeps the active set selection and its
  // colours in the coordination space, so reading them back on every config
  // change keeps the legend correct even after the user picks another column.
  const legendEl = document.getElementById("legend");

  function firstScope(obj) {
    if (!obj) return null;
    const k = Object.keys(obj)[0];
    return k === undefined ? null : obj[k];
  }

  function renderLegend(cfg) {
    const cs = (cfg && cfg.coordinationSpace) || {};
    const selection = firstScope(cs.obsSetSelection) || [];
    const colours = firstScope(cs.obsSetColor) || [];
    const byPath = new Map(colours.map(c => [c.path.join("\u0001"), c.color]));
    if (!selection.length) {
      legendEl.innerHTML = '<span class="none">No cell sets selected &mdash; pick a column in '
        + 'Cell Sets to colour the left map.</span>';
      return;
    }
    const group = selection[0][0];
    const items = selection.map(path => {
      const name = path[path.length - 1];
      const rgb = byPath.get(path.join("\u0001"));
      const sw = rgb
        ? `<span class="sw" style="background: rgb(${rgb.join(",")})"></span>`
        : '<span class="sw" style="background: transparent; border-style: dashed"></span>';
      return `<span class="lg">${sw}${name}</span>`;
    }).join("");
    legendEl.innerHTML = `<span class="lg-title">${group}</span>${items}`;
  }

  let latestConfig = config;
  renderLegend(config);

  // Vitessce lays its grid out from an explicit pixel height; without one the
  // react-grid-layout collapses to 0 and every view stacks in the corner.
  const mount = createRoot(document.getElementById("vit"));
  const chrome = () => document.querySelector(".bar").offsetHeight + legendEl.offsetHeight;
  const draw = () => mount.render(React.createElement(Vitessce, {
    config: withSummary(latestConfig, showSummary),
    theme,
    height: Math.max(showSummary ? 1000 : 480, window.innerHeight - chrome()),
    onConfigChange: (cfg) => { latestConfig = cfg; renderLegend(cfg); },
  }));

  const box = document.getElementById("summary");
  box.checked = showSummary;
  box.addEventListener("change", () => {
    showSummary = box.checked;
    try { localStorage.setItem("summaryPlots", showSummary ? "1" : "0"); } catch (e) { /* ignore */ }
    draw();
  });

  const themeBtn = document.getElementById("themeBtn");
  const labelFor = t => t === "dark" ? "\u2600 Day mode" : "\u263E Night mode";
  themeBtn.textContent = labelFor(theme);
  themeBtn.addEventListener("click", () => {
    theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = theme;
    themeBtn.textContent = labelFor(theme);
    try { localStorage.setItem("theme", theme); } catch (e) { /* ignore */ }
    draw();
  });

  draw();
  let t = null;
  window.addEventListener("resize", () => {
    clearTimeout(t);
    t = setTimeout(draw, 150);
  });
})().catch(err => {
  panel("Viewer failed to start", `<pre>${String(err && err.stack || err)}</pre>
    <p><a href="./index.html">Back to the dataset list</a></p>`);
  console.error(err);
});
</script>
</body>
</html>
"""


def paper_slug(paper_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (paper_id or "other").lower()).strip("-")


def dataset_card(entry: dict, validate: dict, cfg: dict) -> str:
    sets = entry.get("obs_sets", [])
    shown = sets[:10]
    tags = "".join(
        f'<span class="tag">{html.escape(s.replace("_", " "))}</span>' for s in shown
    )
    if len(sets) > len(shown):
        tags += f'<span class="tag">+{len(sets) - len(shown)} more</span>'
    timing = (validate or {}).get("single_gene_fetch", {})
    modality = (f'<p class="modality">{html.escape(entry["modality"])}</p>'
                if entry.get("modality") else "")
    return f"""
    <section class="card">
      <h2>{html.escape(entry['title'])}</h2>
      <p>{html.escape(entry.get('description') or '')}</p>
      <div class="stats">
        <div class="stat"><div class="n">{entry['n_cells']:,}</div><div class="k">cells</div></div>
        <div class="stat"><div class="n">{entry['n_genes']:,}</div><div class="k">genes</div></div>
        <div class="stat"><div class="n">{len(sets)}</div><div class="k">cell-set columns</div></div>
        <div class="stat"><div class="n">{', '.join(entry['embeddings'])}</div><div class="k">embeddings</div></div>
        <div class="stat"><div class="n">{entry['store_size']}</div><div class="k">zarr store</div></div>
      </div>
      {modality}
      <div class="tags">{tags}</div>
      <p>
        <a class="btn" href="./viewer.html?dataset={entry['key']}">Open viewer</a>
        <a class="btn sec" href="./configs/{entry['key']}.json">View config JSON</a>
      </p>
      <pre><code>import anndata as ad
adata = ad.read_zarr("{entry['url']}")</code></pre>
      <p style="color:var(--muted);font-size:12.5px;margin-top:12px">
        Single-gene fetch measured locally: p50 {timing.get('p50_ms', '?')} ms,
        p95 {timing.get('p95_ms', '?')} ms &middot; X chunked {timing.get('chunk_shape', '?')}
      </p>
    </section>"""


def paper_card(paper: str, slug: str, entries: list, pub: dict | None = None) -> str:
    cells = sum(e["n_cells"] for e in entries)
    titles = ", ".join(e["title"] for e in entries[:4])
    if len(entries) > 4:
        titles += f", +{len(entries) - 4} more"
    pub = pub or {}
    art = pub.get("title")
    journal = pub.get("journal_short") or ""
    year = pub.get("year") or ""
    img = (f'<a class="ga" href="./{slug}.html">'
           f'<img src="./assets/{pub["image"]}" alt="Graphical abstract, {html.escape(paper)}" '
           f'loading="lazy"></a>') if pub.get("image") else ""
    head = (f'<p class="cite">{html.escape(journal)}'
            + (f' &middot; {year}' if year else '') + '</p>') if journal else ""
    art_html = (f'<p class="arttitle"><a href="{html.escape(pub["paper_url"])}" '
                f'target="_blank" rel="noopener">{html.escape(art)}</a></p>') if art else ""
    return f"""
    <section class="card pubcard">
      {img}
      <div class="pubbody">
        <h2><a href="./{slug}.html">{html.escape(paper)}</a></h2>
        {head}
        {art_html}
        <div class="stats">
          <div class="stat"><div class="n">{len(entries)}</div><div class="k">datasets</div></div>
          <div class="stat"><div class="n">{cells:,}</div><div class="k">cells total</div></div>
        </div>
        <p class="datasetlist">{html.escape(titles)}</p>
        <p class="actions">
          <a class="btn" href="./{slug}.html">Browse datasets</a>
          {links_html(pub)}
        </p>
      </div>
    </section>"""


def links_html(pub: dict) -> str:
    """Paper and data-repository links, deduplicated across raw and processed."""
    out = []
    if pub.get("paper_url"):
        out.append(f'<a class="btn sec" href="{html.escape(pub["paper_url"])}" '
                   f'target="_blank" rel="noopener">Paper</a>')
    seen, acc = set(), []
    for row in (pub.get("raw_data") or []) + (pub.get("processed_data") or []):
        if row["url"] in seen:
            continue
        seen.add(row["url"])
        acc.append(row)
    for row in acc[:8]:
        out.append(f'<a class="acc" href="{html.escape(row["url"])}" target="_blank" '
                   f'rel="noopener">{html.escape(row["label"])}</a>')
    if len(acc) > 8:
        out.append(f'<span class="acc more">+{len(acc) - 8}</span>')
    return "\n          ".join(out)


def page_shell(title: str, body: str, cfg: dict) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{STYLE}</style>
</head>
<body>
<button class="themebtn" id="themebtn" type="button">theme</button>
<div class="wrap">
{body}
  <footer>
    Embeddings and annotations are the published ones &mdash; no re-clustering or
    re-embedding was performed. Built with Vitessce {VITESSCE_VERSION}.
    Last updated {date.today().isoformat()}.
  </footer>
</div>
<script>
  // Same three-step resolution as the viewer: saved choice, else OS setting.
  (function () {{
    var el = document.documentElement, btn = document.getElementById("themebtn");
    var theme;
    try {{ theme = localStorage.getItem("theme"); }} catch (e) {{ /* private window */ }}
    if (theme !== "light" && theme !== "dark") {{
      theme = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    }}
    function apply(t) {{
      el.dataset.theme = t;
      btn.textContent = t === "dark" ? "\u2600 Day mode" : "\u263E Night mode";
    }}
    apply(theme);
    btn.addEventListener("click", function () {{
      theme = theme === "dark" ? "light" : "dark";
      try {{ localStorage.setItem("theme", theme); }} catch (e) {{ /* ignore */ }}
      apply(theme);
    }});
  }})();
</script>
</body>
</html>
"""


def build_index(index: dict, cfg: dict, by_paper: dict, pubs: dict) -> str:
    cards = "".join(
        paper_card(paper, slug, entries, pubs.get(slug))
        for paper, (slug, entries) in by_paper.items()
    )
    n_cells = sum(e["n_cells"] for _slug, entries in by_paper.values() for e in entries)
    n_sets = sum(len(entries) for _slug, entries in by_paper.values())
    body = f"""  <header>
    <h1>{html.escape(index.get('title', 'Datasets'))}</h1>
    <p class="lede">Published single-cell RNA-seq datasets, converted to cloud-optimised
    AnnData-Zarr and browsable in the browser &mdash; UMAP or tissue space, cell-type sets
    and per-gene expression, with no backend server.</p>
    <p class="lede">{n_sets} datasets from {len(by_paper)} publications,
    {n_cells:,} cells in total. Pick a publication to see its datasets.</p>
  </header>
  {cards}
  <section class="card">
    <h2>Direct data access</h2>
    <p>No credentials required. Everything is public and openly licensed
    ({html.escape(cfg.get('license', 'CC-BY-4.0'))}).</p>
    <pre><code>aws s3 ls --no-sign-request s3://{cfg['s3_bucket']}/</code></pre>
    <table>
      <tr><th>Path</th><th>Contents</th></tr>
      <tr><td><code>&lt;dataset&gt;.zarr/X</code></td><td>normalised expression, dense, chunked (n_cells, 10)</td></tr>
      <tr><td><code>&lt;dataset&gt;.zarr/obs</code></td><td>per-cell metadata</td></tr>
      <tr><td><code>&lt;dataset&gt;.zarr/obsm/X_umap</code></td><td>UMAP embedding (and <code>X_spatial</code> where applicable)</td></tr>
      <tr><td><code>&lt;dataset&gt;.zarr/var</code></td><td>gene metadata, incl. <code>highly_variable</code></td></tr>
      <tr><td><code>configs/</code></td><td>Vitessce view configs</td></tr>
    </table>
  </section>"""
    return page_shell(index.get("title", "Datasets"), body, cfg)


def build_paper_page(paper: str, entries: list, index: dict, cfg: dict,
                     pub: dict | None = None) -> str:
    cards = "".join(
        dataset_card(e, read_json(CHECK_DIR / f"{e['key']}_validate.json", {}), cfg)
        for e in entries
    )
    cells = sum(e["n_cells"] for e in entries)
    plural = "s" if len(entries) != 1 else ""
    pub = pub or {}
    art = pub.get("title")
    meta = []
    if pub.get("journal_short"):
        meta.append(html.escape(pub["journal_short"]) + (f" &middot; {pub['year']}" if pub.get("year") else ""))
    if pub.get("doi"):
        meta.append(f'<a href="https://doi.org/{html.escape(pub["doi"])}" target="_blank" '
                    f'rel="noopener">doi:{html.escape(pub["doi"])}</a>')
    art_html = (f'<p class="arttitle"><a href="{html.escape(pub.get("paper_url", "#"))}" '
                f'target="_blank" rel="noopener">{html.escape(art)}</a></p>') if art else ""
    img = (f'<img class="ga wide" src="./assets/{pub["image"]}" '
           f'alt="Graphical abstract, {html.escape(paper)}">') if pub.get("image") else ""
    body = f"""  <header>
    <p class="crumb"><a href="./index.html">&larr; All publications</a></p>
    <h1>{html.escape(paper)}</h1>
    {art_html}
    <p class="cite">{' &middot; '.join(meta)}</p>
    <p class="lede">{len(entries)} dataset{plural}, {cells:,} cells in total.</p>
    <p class="actions">{links_html(pub)}</p>
  </header>
  {img}
  {cards}"""
    return page_shell(f"{paper} \u2014 {index.get('title', 'Datasets')}", body, cfg)


def main() -> int:
    ap = add_common_args(argparse.ArgumentParser(description=__doc__))
    ap.add_argument("--base-url", help="override config/pipeline.json base_url")
    args = ap.parse_args()

    cfg = load_pipeline_config()
    if args.base_url:
        cfg["base_url"] = args.base_url
    index = read_json(CONFIG_DIR / "index.json")
    if not index or not index.get("datasets"):
        raise SystemExit("configs/index.json is empty — run stage 5 first.")

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "configs").mkdir(exist_ok=True)
    for f in CONFIG_DIR.glob("*.json"):
        shutil.copy2(f, DOCS / "configs" / f.name)

    # Group datasets by publication: the landing page lists publications, and each
    # publication gets its own page listing its datasets.
    by_paper = {}
    manifest = read_json(BUILD_DIR / "manifest.json", {}) or {}
    for entry in index["datasets"]:
        ds = (manifest.get("datasets") or {}).get(entry["key"], {})
        paper = entry.get("paper") or ds.get("paper_id") or "Other"
        slug = paper_slug(ds.get("paper_id") or paper)
        by_paper.setdefault(paper, (slug, []))[1].append(entry)
    for paper, (slug, entries) in by_paper.items():
        entries.sort(key=lambda e: e["title"])

    pubs = read_json(ASSETS / "publications.json", {}) or {}
    pubs = {paper_slug(k): v for k, v in pubs.items()}

    (DOCS / "index.html").write_text(build_index(index, cfg, by_paper, pubs))
    for paper, (slug, entries) in by_paper.items():
        (DOCS / f"{slug}.html").write_text(
            build_paper_page(paper, entries, index, cfg, pubs.get(slug)))
        log(f"  {slug}.html - {paper}: {len(entries)} dataset(s)")
    viewer = (VIEWER_HTML
              .replace("__TITLE__", html.escape(index.get("title", "Viewer")))
              .replace("__REACT__", REACT_VERSION)
              .replace("__VITESSCE__", VITESSCE_VERSION))
    (DOCS / "viewer.html").write_text(viewer)
    (DOCS / ".nojekyll").write_text("")

    log(f"wrote docs/ for {len(index['datasets'])} dataset(s)")
    for f in sorted(p.name for p in DOCS.iterdir()):
        log(f"  {f}")
    log("GitHub Pages: Settings -> Pages -> Source: main branch, /docs folder")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
