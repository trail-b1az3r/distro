"""Documentation: relative links resolve, and documented commands exist."""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PAGES = [REPO / "README.md", REPO / "CONTRIBUTING.md", REPO / "cli/README.md", *sorted((REPO / "docs").glob("*.md"))]
LINK = re.compile(r"\]\(([^)#\s]+)(#[^)]*)?\)")


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(REPO)))
def test_relative_links_resolve(page):
    for target, _anchor in LINK.findall(page.read_text()):
        if re.match(r"^[a-z]+:", target):
            continue
        assert (page.parent / target).exists(), f"{page.name}: broken link {target}"


def test_documented_subcommands_exist():
    from distrokit.cli import build_parser

    parser = build_parser()
    sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")  # noqa: SLF001
    known = set(sub.choices)
    text = "\n".join(p.read_text() for p in PAGES)
    used = set(re.findall(r"`nexora ([a-z][a-z-]+)", text)) | set(re.findall(r"^nexora ([a-z][a-z-]+)", text, re.M))
    assert used, "no commands found"
    assert used <= known, f"documented but missing: {sorted(used - known)}"
