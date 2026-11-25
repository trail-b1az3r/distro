"""Frontline Write's MDXL helper (apps/write/data/mdxl-render.py), with a stand-in for MDXL's renderer."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_document_view_lays_pages_out_and_prints_them_as_text():
    root = Path(__file__).resolve().parents[2] / "apps/write"
    editor = (root / "qml/Editor.qml").read_text()
    # Page-break markers start a sheet, overflow moves on, and each sheet is a printed page.
    assert "readonly property string paginator:" in editor
    assert "classList.contains('write-page-break')" in editor and "content.scrollHeight > content.clientHeight" in editor
    assert ".write-sheet{box-sizing:border-box;position:relative;width:794px;height:1123px" in editor
    assert "break-after:page;page-break-after:always" in editor
    # PDFs always come from the paged layout, and print without effects that would flatten text into pictures.
    assert "printToPdf(out, WebEngineView.A4, WebEngineView.Portrait)" in editor
    assert "backdrop-filter:none!important" in editor and "text-shadow:none!important" in editor
    # Preview shows where a page breaks.
    assert "content:'Page break'" in editor


def test_text_is_drawn_as_vector_outlines():
    main = (Path(__file__).resolve().parents[2] / "apps/write/src/main.cpp").read_text()
    assert "QQuickWindow::setTextRenderType(QQuickWindow::CurveTextRendering);" in main


WRITE = Path(__file__).resolve().parents[2] / "apps/write"


def test_ribbon_inserts_mdxl_styles_and_blocks():
    editor = (WRITE / "qml/Editor.qml").read_text()
    for marker in ('wrapSelection("/u//", "/u//")', 'wrapSelection("/bdg#2E8BF2//", "/bdg//")',
                   'wrapSelection("/grad#FF5F57#4DB6FF//", "/grad//")', 'wrapSelection("/rb//"',
                   'wrapSelection("->", "<-")', 'insertBlock("::: columns"', 'insertBlock("::: card "',
                   'insertBlock("::: timeline"', 'insertBlock("::: chat"'):
        assert marker in editor, marker
    # On white A4 sheets the new elements are light, and the wave holds still for PDFs.
    assert "body .mdxl-card{background:#f6f7f4" in editor and "body .mdxl-wave span{animation:none!important}" in editor


def test_spelling_skips_mdxl_markers():
    highlighter = (WRITE / "src/highlighter.cpp").read_text()
    assert "/rb//.*?/rb//|/[a-z]{1,5}(?:#[0-9A-Fa-f]{6}){0,2}//" in highlighter


def test_docx_export_uses_the_mdxl_converter():
    files = (WRITE / "src/files.cpp").read_text()
    assert "MdxlWord::body(text)" in files
    assert "src/mdxlword.h src/mdxlword.cpp" in (WRITE / "CMakeLists.txt").read_text()


def _qt_core_flags():
    compiler = shutil.which("g++") or shutil.which("c++")
    if not compiler or not shutil.which("pkg-config"):
        return None
    res = subprocess.run(["pkg-config", "--cflags", "--libs", "Qt6Core"], capture_output=True, text=True)
    if res.returncode != 0:
        return None
    libdir = subprocess.run(["pkg-config", "--variable=libdir", "Qt6Core"], capture_output=True, text=True).stdout.strip()
    return compiler, res.stdout.split(), libdir


def test_mdxl_becomes_word_formatting(tmp_path):
    from xml.dom import minidom
    found = _qt_core_flags()
    if not found:
        pytest.skip("needs a C++ compiler and Qt6Core")
    compiler, flags, libdir = found
    (tmp_path / "main.cpp").write_text(
        '#include "mdxlword.h"\n#include <QFile>\n#include <QTextStream>\n'
        "int main(int, char **argv) { QFile in(argv[1]); in.open(QIODevice::ReadOnly);\n"
        "  QTextStream(stdout) << MdxlWord::body(QString::fromUtf8(in.readAll())); }\n")
    binary = tmp_path / "mdxlword"
    build = subprocess.run([compiler, "-std=c++17", "-fPIC", "-I", str(WRITE / "src"), str(WRITE / "src/mdxlword.cpp"),
                            str(tmp_path / "main.cpp"), "-o", str(binary), *flags, f"-Wl,-rpath,{libdir}"],
                           capture_output=True, text=True)
    assert build.returncode == 0, build.stderr
    source = tmp_path / "doc.mdxl"
    source.write_text("# Title\n\n**Bold** /u//under/u// /bdg#E5484D//Hot/bdg// /grad#FF0000#0000FF//ab/grad//\n"
                      "/rb//漢字//かんじ/rb// /tip//word//explained/tip// <&>\n\n->Centred<-\n\n"
                      "::: card Notes\nInside\n:::\n\n::: timeline\n2026 :: Launch\n:::\n\n"
                      "::: chat\nAna: Hi\nBen: Hello\n:::\n\n```\n/u//literal/u//\n```\n", encoding="utf-8")
    out = subprocess.run([str(binary), str(source)], capture_output=True, text=True,
                         env={**os.environ, "LD_LIBRARY_PATH": libdir}).stdout
    minidom.parseString('<w:body xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                        + out + "</w:body>")
    assert '<w:pStyle w:val="Heading1"/>' in out
    assert '<w:b/></w:rPr><w:t xml:space="preserve">Bold</w:t>' in out
    assert '<w:u w:val="single"/></w:rPr><w:t xml:space="preserve">under</w:t>' in out
    assert 'w:fill="E5484D"/></w:rPr><w:t xml:space="preserve"> Hot </w:t>' in out
    assert '<w:color w:val="FF0000"/>' in out and '<w:color w:val="0000FF"/>' in out
    assert "<w:ruby>" in out and "かんじ" in out and " (explained)" in out and "&lt;&amp;&gt;" in out
    assert '<w:jc w:val="center"/>' in out and '<w:jc w:val="right"/>' in out
    assert 'w:fill="F6F7F4"' in out and "Notes" in out and ">2026<" in out
    assert "/u//literal/u//" in out                       # code is kept as written
    assert ":::" not in out and "/bdg//" not in out and "/grad" not in out
