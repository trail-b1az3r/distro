#!/usr/bin/env python3
"""MDXL rendering for the writer: one JSON request per line on stdin
({"id": n, "text": "..."}), one JSON answer per line on stdout ({"id": n,
"html": "..."} or {"id": n, "error": "..."}). It uses MDXL's own renderer
(mdxl_preview.render_mdxl, from the mdxl package), so the preview shows
exactly what mdxl-preview shows."""
import json
import os
import sys

sys.path.insert(0, os.environ.get("MDXL_LIB", "/usr/lib/mdxl"))
try:
    from mdxl_preview import render_mdxl
except Exception as exc:  # noqa: BLE001 - reported to the app, which shows it
    print(json.dumps({"id": 0, "error": f"MDXL is not installed: {exc}"}), flush=True)
    sys.exit(1)

for line in sys.stdin:
    try:
        req = json.loads(line)
    except ValueError:
        continue
    try:
        out = {"id": req.get("id", 0), "html": render_mdxl(req.get("text", ""))}
    except Exception as exc:  # noqa: BLE001
        out = {"id": req.get("id", 0), "error": str(exc)}
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
