#!/usr/bin/env python
"""Serve docs/ and the built zarr stores locally, with CORS, for a demo before
anything is uploaded to S3.

    python scripts/serve_local.py [--port 8787]
    open "http://localhost:8787/viewer.html?dataset=KEY&base=http://localhost:8787/zarr"

/            -> docs/
/zarr/...    -> build/zarr/...
"""
from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, read_json  # noqa: E402

DOCS = ROOT / "docs"
ZARR = ROOT / "build" / "zarr"


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/zarr/"):
            return str(ZARR / clean[len("/zarr/"):])
        return str(DOCS / clean.lstrip("/"))

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Expose-Headers", "Content-Length, Content-Range")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *a):  # keep the console readable during a demo
        if "404" in (fmt % a):
            sys.stderr.write("404 " + (fmt % a) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    if not (DOCS / "viewer.html").exists():
        raise SystemExit("docs/viewer.html missing — run: python scripts/08_site.py")

    index = read_json(DOCS / "configs" / "index.json", {}) or {}
    keys = [d["key"] for d in index.get("datasets", [])]
    base = f"http://localhost:{args.port}"
    url = f"{base}/viewer.html?dataset={keys[0]}&base={base}/zarr" if keys else base

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", args.port), functools.partial(Handler)) as httpd:
        print(f"docs/      -> {base}/")
        print(f"build/zarr -> {base}/zarr/")
        for k in keys:
            print(f"  {base}/viewer.html?dataset={k}&base={base}/zarr")
        if not args.no_open:
            webbrowser.open(url)
        print("Ctrl-C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
