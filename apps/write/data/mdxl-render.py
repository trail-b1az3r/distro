#!/usr/bin/env python3
"""MDXL rendering for Nexora Write, including document metadata and review markup."""
import html
from html.parser import HTMLParser
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


def add_after_body_start(document, fragment):
    match = re.search(r"<body\b[^>]*>", document, re.IGNORECASE)
    if match:
        return document[:match.end()] + fragment + document[match.end():]
    return fragment + document


# EPUB-MXL (an EPUB whose chapters are MDXL rendered as rich text): a chapter's <body> as well-formed XHTML, and MDXL's
# stylesheet without its dark web-preview page, so it suits any reader's page and colours.
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
DROP = {"script", "noscript", "iframe", "object", "button", "form", "template"}


class XhtmlBody(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.styles, self.stack = [], [], []
        self.in_body = self.in_style = False
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True
            return
        if tag == "style":
            self.in_style = True
            return
        if not self.in_body:
            return
        if tag in DROP:
            self.skip += 1
            return
        if self.skip:
            return
        text = "".join(f' {k}="{html.escape(v if v is not None else k, quote=True)}"'
                       for k, v in attrs if not k.startswith("on") and k not in ("contenteditable",))
        if tag in VOID:
            self.out.append(f"<{tag}{text}/>")
        else:
            self.out.append(f"<{tag}{text}>")
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1] == tag and not self.skip:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "body":
            self.in_body = False
            return
        if tag == "style":
            self.in_style = False
            return
        if not self.in_body or tag in VOID:
            return
        if tag in DROP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in self.stack:
            return
        while self.stack:  # close anything left open inside it, as browsers do
            top = self.stack.pop()
            self.out.append(f"</{top}>")
            if top == tag:
                break

    def handle_data(self, data):
        if self.in_style:
            self.styles.append(data)
        elif self.in_body and not self.skip:
            self.out.append(html.escape(data, quote=False))

    def result(self):
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


BOOK_CSS = ("\n:root{color-scheme:light dark}body{margin:0;background:none;color:inherit;font:inherit;line-height:1.6}"
            "article{max-width:none;margin:0;padding:0}h1{font-size:2em}img{max-width:100%;height:auto}"
            "table{border-collapse:collapse}th,td{border:1px solid #8886;padding:.25em .6em}\n")


def to_xhtml(document):
    parser = XhtmlBody()
    parser.feed(document)
    parser.close()
    css = "\n".join(parser.styles)
    css = re.sub(r":root\s*\{[^}]*\}", "", css)
    return parser.result(), css + BOOK_CSS


HEADERLINK = re.compile(r"""<a\b[^>]*\bclass=["']headerlink["'][^>]*>.*?</a>""", re.IGNORECASE | re.DOTALL)


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
        # MDXL puts a permalink (a "¶" link) in every heading; in Write a heading is just a heading.
        document = HEADERLINK.sub("", document)
        style = '<style>.write-header,.write-footer{font-size:.82em;color:#666;border-bottom:1px solid #aaa;padding:0 0 8px;margin:0 0 22px}.write-footer{border:0;border-top:1px solid #aaa;padding:8px 0 0;margin:22px 0 0}.write-comments{margin:28px 0;padding:12px 16px;border-left:3px solid #888;background:#8881}.write-comment{margin:5px 0}ins{background:#b9e8c4;text-decoration:underline}del{background:#f3c2c2;text-decoration:line-through}mark{background:#ffe79a}</style>'
        if header:
            document = add_after_body_start(document, style + '<div class="write-header">' + html.escape(header) + '</div>')
        else:
            document = add_after_body_start(document, style)
        tail = ''
        if footer:
            tail += '<div class="write-footer">' + html.escape(footer) + '</div>'
        if comments:
            tail += '<aside class="write-comments"><strong>Comments</strong>' + ''.join(
                '<div class="write-comment">' + html.escape(c) + '</div>' for c in comments
            ) + '</aside>'
        document = add_before_body_end(document, tail)
        out = {"id": req.get("id", 0), "html": document}
        if req.get("xhtml"):
            out["html"], out["css"] = to_xhtml(document)
    except Exception as exc:  # noqa: BLE001
        out = {"id": req.get("id", 0), "error": str(exc)}
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
