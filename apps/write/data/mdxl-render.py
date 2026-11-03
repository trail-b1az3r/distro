#!/usr/bin/env python3
"""MDXL rendering for Nexora Write, including document metadata and review markup."""
import html
import json
import os
import re
import sys

sys.path.insert(0, os.environ.get("MDXL_LIB", "/usr/lib/mdxl"))
try:
    from mdxl_preview import render_mdxl
except Exception as exc:  # noqa: BLE001
    print(json.dumps({"id": 0, "error": f"MDXL is not installed: {exc}"}), flush=True)
    sys.exit(1)


def add_before_body_end(document, fragment):
    match = re.search(r"</body\s*>", document, re.IGNORECASE)
    if match:
        return document[:match.start()] + fragment + document[match.start():]
    return document + fragment


for line in sys.stdin:
    try:
        req = json.loads(line)
    except ValueError:
        continue
    try:
        source = req.get("text", "")
        source = source.replace("<!-- WRITE_PAGE_BREAK -->",
                                '<div class="write-page-break"></div>')
        header = footer = ""
        comments = []
        kept = []
        for source_line in source.splitlines():
            match = re.fullmatch(r"\s*<!-- WRITE_HEADER:(.*?) -->\s*", source_line)
            if match:
                header = match.group(1)
                continue
            match = re.fullmatch(r"\s*<!-- WRITE_FOOTER:(.*?) -->\s*", source_line)
            if match:
                footer = match.group(1)
                continue
            match = re.fullmatch(r"\s*<!-- WRITE_COMMENT:(.*?) -->\s*", source_line)
            if match:
                comments.append(match.group(1))
                continue
            kept.append(source_line)
        document = render_mdxl("\n".join(kept))
        fragments = ['<style>.write-header,.write-footer{font-size:.82em;color:#666;border-bottom:1px solid #aaa;padding:0 0 8px;margin:0 0 22px}.write-footer{border:0;border-top:1px solid #aaa;padding:8px 0 0;margin:22px 0 0}.write-comments{margin:28px 0;padding:12px 16px;border-left:3px solid #888;background:#8881}.write-comment{margin:5px 0}ins{background:#b9e8c4;text-decoration:underline}del{background:#f3c2c2;text-decoration:line-through}</style>']
        if header:
            fragments.append('<div class="write-header">' + html.escape(header) + '</div>')
        if footer:
            fragments.append('<div class="write-footer">' + html.escape(footer) + '</div>')
        if comments:
            fragments.append('<aside class="write-comments"><strong>Comments</strong>' +
                             ''.join('<div class="write-comment">' + html.escape(c) + '</div>' for c in comments) +
                             '</aside>')
        document = add_before_body_end(document, ''.join(fragments))
        out = {"id": req.get("id", 0), "html": document}
    except Exception as exc:  # noqa: BLE001
        out = {"id": req.get("id", 0), "error": str(exc)}
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
