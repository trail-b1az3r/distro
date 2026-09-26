"""Shell completions for the CLI, generated from its argparse parser so they
never drift from the real options.

    python3 -m distrokit.build.completions bash|fish
"""

from __future__ import annotations

import argparse
import shlex
import sys
from dataclasses import dataclass, field

from ..branding import Branding, load as load_branding


@dataclass
class Command:
    name: str
    help: str
    choices: list[str] = field(default_factory=list)  # first positional's choices
    options: list[tuple[str, str]] = field(default_factory=list)  # (flag, help)


def _commands(parser: argparse.ArgumentParser) -> list[Command]:
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))  # noqa: SLF001
    helps = {c.dest: c.help or "" for c in sub._choices_actions}  # noqa: SLF001
    out = []
    for name, p in sub.choices.items():
        cmd = Command(name, helps.get(name, ""))
        for act in p._actions:  # noqa: SLF001
            if act.help == argparse.SUPPRESS:
                continue
            if not act.option_strings:
                if act.choices and not cmd.choices:
                    cmd.choices = [str(c) for c in act.choices]
                continue
            for flag in act.option_strings:
                cmd.options.append((flag, act.help or ""))
        out.append(cmd)
    return out


def _model_ids() -> list[str]:
    from ..ai import models

    try:
        return [m.id for m in models.load_catalog().models]
    except OSError:
        return []


def bash(b: Branding, parser: argparse.ArgumentParser) -> str:
    cmds = _commands(parser)
    fn = "_" + b.cli.replace("-", "_")
    cases = []
    for c in cmds:
        words = c.choices + [o for o, _ in c.options]
        cases.append(f"        {c.name}) opts={shlex.quote(' '.join(words))} ;;")
    models = " ".join(_model_ids())
    gpu = next(c for c in cmds if c.name == "gpu")
    gpu_words = " ".join(gpu.choices + [o for o, _ in gpu.options])
    return f"""# bash completion for {b.cli} (generated from its argument parser)
{fn}() {{
    local cur prev words cword
    _init_completion 2>/dev/null || {{ cur=${{COMP_WORDS[COMP_CWORD]}}; words=("${{COMP_WORDS[@]}}"); cword=$COMP_CWORD; }}
    if [[ $cword -eq 1 ]]; then
        COMPREPLY=($(compgen -W {shlex.quote(' '.join(c.name for c in cmds) + ' --help --version')} -- "$cur"))
        return
    fi
    local opts=""
    case ${{words[1]}} in
{chr(10).join(cases)}
    esac
    if [[ ${{words[1]}} == model && $cword -eq 3 && ${{words[2]}} =~ ^(install|info|remove|default)$ ]]; then
        opts={shlex.quote(models)}
    fi
    COMPREPLY=($(compgen -W "$opts" -- "$cur"))
}}
complete -F {fn} {b.cli}

{fn}_gpu() {{
    local cur=${{COMP_WORDS[COMP_CWORD]}}
    COMPREPLY=($(compgen -W {shlex.quote(gpu_words)} -- "$cur"))
}}
complete -F {fn}_gpu {b.id}-gpu distro-gpu
"""


def _fish_quote(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def fish(b: Branding, parser: argparse.ArgumentParser) -> str:
    cmds = _commands(parser)
    names = " ".join(c.name for c in cmds)
    lines = [f"# fish completion for {b.cli} (generated from its argument parser)",
             f"complete -c {b.cli} -f"]
    for c in cmds:
        lines.append(f"complete -c {b.cli} -n '__fish_use_subcommand' -a {c.name} -d {_fish_quote(c.help)}")
    for c in cmds:
        cond = f"'__fish_seen_subcommand_from {c.name}'"
        if c.choices:
            lines.append(f"complete -c {b.cli} -n {cond} -a {_fish_quote(' '.join(c.choices))}")
        for flag, text in c.options:
            spec = f"-l {flag[2:]}" if flag.startswith("--") else f"-s {flag[1:]}"
            lines.append(f"complete -c {b.cli} -n {cond} {spec} -d {_fish_quote(text)}")
    models = " ".join(_model_ids())
    if models:
        lines.append(f"complete -c {b.cli} -n '__fish_seen_subcommand_from model; and __fish_seen_subcommand_from "
                     f"install info remove default' -a {_fish_quote(models)}")
    gpu = next(c for c in cmds if c.name == "gpu")
    for exe in (f"{b.id}-gpu", "distro-gpu"):
        lines.append(f"complete -c {exe} -f -a {_fish_quote(' '.join(gpu.choices))}")
        for flag, text in gpu.options:
            if flag.startswith("--"):
                lines.append(f"complete -c {exe} -l {flag[2:]} -d {_fish_quote(text)}")
    lines.append(f"# subcommands: {names}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from ..cli import build_parser

    shell = (sys.argv[1:] if argv is None else argv or ["bash"])[0]
    b = load_branding()
    gen = {"bash": bash, "fish": fish}.get(shell)
    if gen is None:
        print("usage: completions bash|fish", file=sys.stderr)
        return 2
    sys.stdout.write(gen(b, build_parser()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
