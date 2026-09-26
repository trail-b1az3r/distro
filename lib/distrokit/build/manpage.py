"""The CLI's man page, generated from its argparse parser.

    python3 -m distrokit.build.manpage > nexora.1
"""

from __future__ import annotations

import argparse
import sys
import time

from ..branding import Branding, load as load_branding


def _esc(text: str) -> str:
    text = text.replace("\\", "\\\\").replace("-", "\\-")
    return "\n".join(("\\&" + line) if line.startswith((".", "'")) else line for line in text.splitlines())


def render(b: Branding, parser: argparse.ArgumentParser, date: str = "") -> str:
    date = date or time.strftime("%Y-%m")
    from . import completions

    out = [
        f'.TH {b.cli.upper()} 1 "{date}" "{_esc(b.pretty_name)}" "User Commands"',
        ".SH NAME",
        f"{_esc(b.cli)} \\- {_esc(b.pretty_name)} system tool",
        ".SH SYNOPSIS",
        f".B {_esc(b.cli)}",
        ".I command",
        "[\\fIoptions\\fR]",
        ".br",
        f".B {_esc(b.id)}\\-gpu",
        "detect | configure | status",
        ".SH DESCRIPTION",
        _esc("Inspects and maintains the system: hardware, graphics drivers, updates, AI tools and models, "
             "diagnostics and repairs. Read-only commands never need root. Commands that change the system "
             "explain what they will do, ask for confirmation and then re-run themselves through sudo."),
        ".SH COMMANDS",
    ]
    for cmd in completions._commands(parser):  # noqa: SLF001
        out += [".TP", f"\\fB{_esc(cmd.name)}\\fR" + (f" [{_esc('|'.join(cmd.choices))}]" if cmd.choices else "")]
        out.append(_esc(cmd.help or ""))
        opts = [(f, h) for f, h in cmd.options if f not in ("-h", "--help")]
        if opts:
            out.append(".RS")
            for flag, text in opts:
                out += [".TP", f"\\fB{_esc(flag)}\\fR", _esc(text or "")]
            out.append(".RE")
    out += [
        ".SH EXAMPLES",
        ".nf",
        _esc(f"sudo {b.id}-gpu detect          # what graphics hardware there is and the recommended drivers"),
        _esc(f"sudo {b.id}-gpu configure       # install and configure them"),
        _esc(f"{b.cli} doctor                  # diagnose problems, with a fix for each"),
        _esc(f"{b.cli} update                  # packages, AUR, Flatpak, desktop and AI tools"),
        _esc(f"{b.cli} install office docker   # add features after installation"),
        _esc(f"{b.cli} model recommend         # which local AI models fit this machine"),
        ".fi",
        ".SH FILES",
        ".TP", f"/etc/{b.id}/", _esc("System configuration written by the installer and the GPU manager."),
        ".TP", f"/var/lib/{b.id}/", _esc("Install record and hardware report."),
        ".TP", f"~/.config/{b.id}/", _esc("Per-user settings, installed models (models.json) and ai.env."),
        ".SH SEE ALSO",
        _esc(f"pacman(8), yay(8), {b.get('DISTRO_DOC_URL')}"),
    ]
    return "\n".join(out) + "\n"


def main() -> int:
    from ..cli import build_parser

    sys.stdout.write(render(load_branding(), build_parser()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
