"""Nexora Write's spelling: Sonnet underlines and suggests, autocorrect fixes only known typos."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRITE = ROOT / "apps/write"


def corrections():
    out = {}
    for line in (WRITE / "data/autocorrect.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        typo, _, fix = line.partition("=")
        out.setdefault(typo, []).append(fix)
    return out


def test_the_typo_list_is_well_formed():
    table = corrections()
    assert len(table) > 100
    for typo, fixes in table.items():
        assert len(fixes) == 1, f"{typo} listed twice"
        assert typo == typo.lower() and re.fullmatch(r"[a-z']+", typo), typo
        assert fixes[0] and fixes[0].lower() != typo, typo


def test_real_words_are_never_autocorrected():
    # A word that is a word in its own right must not be "fixed" into another.
    table = corrections()
    for word in ("alright", "its", "their", "there", "then", "than", "lose", "loose", "affect", "effect"):
        assert word not in table, word


def test_spelling_is_built_in_and_packaged():
    cmake = (WRITE / "CMakeLists.txt").read_text()
    assert "find_package(KF6Sonnet REQUIRED)" in cmake and "KF6::SonnetCore" in cmake
    assert "src/spelling.cpp" in cmake and "data/autocorrect.txt" in cmake
    pkgbuild = (ROOT / "packages/pkgbuild/write/PKGBUILD.in").read_text()
    assert all(dep in pkgbuild for dep in ("sonnet", "hunspell", "hunspell-en_us"))
    editor = (WRITE / "qml/Editor.qml").read_text()
    assert "Spelling.correction(" in editor and "Spelling.suggestions(" in editor
    assert "Spelling.enabled = checked" in editor and "Spelling.autocorrect = checked" in editor
    highlighter = (WRITE / "src/highlighter.cpp").read_text()
    assert "new SpellingHighlighter(" in highlighter and "SpellCheckUnderline" in highlighter
