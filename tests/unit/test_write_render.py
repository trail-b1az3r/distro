"""Nexora Write's MDXL helper (apps/write/data/mdxl-render.py), with a stand-in for MDXL's renderer."""
import json
import subprocess
import sys
from pathlib import Path

HELPER = Path(__file__).resolve().parents[2] / "apps/write/data/mdxl-render.py"

# MDXL (Python-Markdown's toc extension) puts a "¶" permalink in every heading.
FAKE_MDXL = '''
def render_mdxl(content, live=False):
    return ('<html><body><article>'
            '<h1 id="title">Title<a class="headerlink" href="#title" title="Permanent link">&para;</a></h1>'
            '<h2 id="two">Two<a class="headerlink" href="#two" title="Permanent link">&para;</a></h2>'
            '<p>A <a href="https://example.org">link</a>.</p></article></body></html>')
'''


def test_headings_are_not_links(tmp_path):
    (tmp_path / "mdxl_preview.py").write_text(FAKE_MDXL)
    request = json.dumps({"id": 7, "text": "# Title\n\n## Two\n\nA [link](https://example.org).\n"}) + "\n"
    res = subprocess.run([sys.executable, str(HELPER)], input=request, capture_output=True, text=True,
                         env={"MDXL_LIB": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=30)
    reply = json.loads(res.stdout.splitlines()[0])
    html = reply["html"]
    assert reply["id"] == 7
    assert "headerlink" not in html and "&para;" not in html and "¶" not in html
    # Headings keep their ids (the contents still jump to them), and ordinary links stay links.
    assert '<h1 id="title">Title</h1>' in html and '<h2 id="two">Two</h2>' in html
    assert '<a href="https://example.org">link</a>' in html


def test_epub_mxl_chapters_are_well_formed_xhtml(tmp_path):
    # EPUB-MXL chapters are XHTML: MDXL's HTML (void elements, bare attributes, scripts) made well-formed, and its
    # stylesheet without the web preview's own page.
    from xml.dom import minidom
    (tmp_path / "mdxl_preview.py").write_text(
        "def render_mdxl(content, live=False):\n"
        "    return (\"<!doctype html><html><head><style>:root{--bg:#000}body{background:#000}.x{color:red}</style>"
        "</head><body><article><h1 id='t'>T &amp; U<a class='headerlink' href='#t'>&para;</a></h1>"
        "<p>a<br>b <img src='images/c.png' alt='c'></p><input type=checkbox disabled>"
        "<script>alert(1)</script><p onclick='x()'>ok</article></body></html>\")\n")
    request = json.dumps({"id": 1, "xhtml": True, "text": "# T"}) + "\n"
    res = subprocess.run([sys.executable, str(HELPER)], input=request, capture_output=True, text=True,
                         env={"MDXL_LIB": str(tmp_path), "PATH": "/usr/bin:/bin"}, timeout=30)
    reply = json.loads(res.stdout.splitlines()[0])
    body = reply["html"]
    minidom.parseString('<body xmlns="http://www.w3.org/1999/xhtml">' + body + "</body>")
    assert "<br/>" in body and '<img src="images/c.png" alt="c"/>' in body
    assert 'disabled="disabled"' in body and "<script" not in body and "alert" not in body
    assert "onclick" not in body and "headerlink" not in body and "T &amp; U" in body
    assert ".x{color:red}" in reply["css"] and ":root{--bg" not in reply["css"]
