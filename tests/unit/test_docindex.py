"""Local document indexing and retrieval (lib/distrokit/docindex.py, `frontline docs`)."""
import json
import os
import zipfile
from pathlib import Path

import pytest

from distrokit import docindex

APP = "frontline-test"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / ".local/share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    docs = tmp_path / "Documents"
    (docs / "Taxes").mkdir(parents=True)
    (docs / ".private").mkdir()
    (docs / "node_modules").mkdir()
    (tmp_path / "Notes").mkdir()
    (tmp_path / "Notes/garden.md").write_text("# Garden plan\n\nPlant the tomatoes after the last frost.\n\n"
                                              "Water the basil every morning.\n")
    (docs / "router.html").write_text("<html><head><title>Router manual</title><script>var tomatoes</script></head>"
                                      "<body><p>To reset the router hold the button for ten seconds.</p></body></html>")
    (docs / ".private/secret.md").write_text("tomatoes in a hidden folder\n")
    (docs / "node_modules/readme.md").write_text("tomatoes in a dependency\n")
    with zipfile.ZipFile(docs / "Taxes/receipts.docx", "w") as z:
        z.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>Deductible receipts for the home "
                                        "office:</w:t></w:r></w:p><w:p><w:r><w:t>desk &amp; chair</w:t></w:r></w:p>"
                                        "</w:body></w:document>")
        z.writestr("docProps/core.xml", "<cp:coreProperties><dc:title>Tax receipts</dc:title></cp:coreProperties>")
    with zipfile.ZipFile(docs / "story.epub", "w") as z:
        z.writestr("META-INF/container.xml", '<container><rootfile full-path="OEBPS/content.opf"/></container>')
        z.writestr("OEBPS/content.opf", '<package><manifest><item id="a" href="one.xhtml"/><item id="b" '
                                        'href="two.xhtml"/></manifest><spine><itemref idref="b"/><itemref idref="a"/>'
                                        "</spine></package>")
        z.writestr("OEBPS/one.xhtml", "<html><body><p>The lighthouse keeper.</p></body></html>")
        z.writestr("OEBPS/two.xhtml", "<html><body><p>A stormy prologue.</p></body></html>")
    return tmp_path


def paths(hits):
    return [Path(h.path).name for h in hits]


def test_it_finds_words_in_every_kind_of_document(home):
    stats = docindex.index(APP)
    assert stats.added == 4
    assert paths(docindex.search(APP, "tomatoes")) == ["garden.md"]          # not the hidden folder, script or deps
    assert paths(docindex.search(APP, "deductible desk")) == ["receipts.docx"]
    assert paths(docindex.search(APP, "lighthouse")) == ["story.epub"]
    assert paths(docindex.search(APP, "reset router")) == ["router.html"]
    assert paths(docindex.search(APP, "receipt")) == ["receipts.docx"]       # the last word is a prefix
    assert paths(docindex.search(APP, "tax receipts", kind="docx")) == ["receipts.docx"]
    assert docindex.search(APP, "tomatoes NOT basil") == []
    assert docindex.search(APP, "tomatoes -basil") == []
    assert paths(docindex.search(APP, '"hold the button"')) == ["router.html"]
    assert paths(docindex.search(APP, "garden", under=str(home / "Notes"))) == ["garden.md"]
    assert docindex.search(APP, "garden", under=str(home / "Documents")) == []


def test_titles_come_from_the_document(home):
    docindex.index(APP)
    titles = {Path(h.path).name: h.title for h in docindex.search(APP, "the")}
    assert titles["garden.md"] == "Garden plan"
    assert titles["router.html"] == "Router manual"
    assert titles["receipts.docx"] == "Tax receipts"


def test_epub_chapters_are_read_in_spine_order(home):
    text, _ = docindex.extract(home / "Documents/story.epub")
    assert text.index("prologue") < text.index("lighthouse")


def test_indexing_is_incremental(home):
    docindex.index(APP)
    again = docindex.index(APP)
    assert (again.added, again.updated, again.unchanged) == (0, 0, 4)
    garden = home / "Notes/garden.md"
    garden.write_text("# Garden plan\n\nNow with courgettes.\n")
    os.utime(garden, (garden.stat().st_atime, garden.stat().st_mtime + 5))
    (home / "Documents/router.html").unlink()
    changed = docindex.index(APP)
    assert (changed.updated, changed.removed) == (1, 1)
    assert paths(docindex.search(APP, "courgettes")) == ["garden.md"]
    assert docindex.search(APP, "tomatoes") == [] and docindex.search(APP, "router") == []


def test_passages_feed_the_local_model(home):
    docindex.index(APP)
    hits = docindex.search(APP, "home office", passages=True, mark=("", ""))
    assert hits and "Deductible receipts" in hits[0].passage
    messages = docindex.ask_messages("What can I deduct?", hits)
    assert "only the numbered passages" in messages[0]["content"]
    assert "[1] receipts.docx" in messages[1]["content"] and "What can I deduct?" in messages[1]["content"]


def test_long_text_is_cut_into_passages():
    text = "\n\n".join(f"Paragraph {n}. " + "word " * 120 for n in range(10))
    pieces = docindex.chunks(text)
    assert len(pieces) > 3 and all(len(p) <= docindex.CHUNK_CHARS for p in pieces)
    assert docindex.chunks("x" * 5000) and all(len(p) <= docindex.CHUNK_CHARS for p in docindex.chunks("x" * 5000))


def test_queries_cannot_inject_fts_syntax():
    assert docindex.fts_query('tax* OR "x" NEAR(') == '"tax" "OR" "x" "NEAR"*'
    with pytest.raises(docindex.DocIndexError):
        docindex.fts_query("-only -negative")


def test_folders_are_yours_to_choose(home):
    config = docindex.load_config(APP)
    assert str(home / "Documents") in config.roots
    config.roots = [str(home / "Notes")]
    docindex.save_config(APP, config)
    docindex.index(APP)
    assert docindex.status(APP)["files"] == 1
    assert json.loads(docindex.config_path(APP).read_text())["roots"] == [str(home / "Notes")]


def test_the_timer_and_command_ship(tmp_path):
    from distrokit.branding import load as load_branding
    from distrokit.build import stage

    b = load_branding()
    stage.Stage(tmp_path, b).run("core")
    units = tmp_path / "usr/lib/systemd/user"
    service = (units / f"{b.id}-docs-index.service").read_text()
    assert f"ExecStart=/usr/bin/{b.cli} docs index --quiet" in service and "Nice=19" in service
    assert "OnUnitActiveSec=30min" in (units / f"{b.id}-docs-index.timer").read_text()
    assert (units / "timers.target.wants" / f"{b.id}-docs-index.timer").is_symlink()
    cli = (Path(__file__).resolve().parents[2] / "lib/distrokit/cli.py").read_text()
    assert 'sub.add_parser("docs"' in cli and "def cmd_docs" in cli
