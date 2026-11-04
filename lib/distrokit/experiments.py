"""Opt-in pacman sources with packages from successful CI builds.

Two sources, both GitHub release pacman repositories:

- ``nexora-experiments``: the latest successful package build of main (refreshed on every main push and nightly).
- ``nexora-experiments-extra``: beta. The latest successful package build of a development branch: the
  distribution's files before they reach main.

Each component (core, nmx, hyprland-plus, …) is enabled from one of the two. Only the packages of enabled
components are taken from them, and only when they are installed already: the sources sit after every other
repository in pacman.conf, so `pacman -Syu` keeps preferring the stable repositories, and `<cli> update` installs
the experimental builds by name (``pacman -S nexora-experiments/<package>``). A stable package with a higher version
replaces an experimental one by itself.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from . import pacmanconf
from .branding import Branding, load as load_branding

MAIN = "nexora-experiments"
EXTRA = "nexora-experiments-extra"
SOURCES = (MAIN, EXTRA)

# The distribution's own split packages (<id>-<component>), then its other packages.
OWN = ("core", "branding", "desktop", "welcome", "installer", "ai")
OTHER = {
    "nmx": ("nmx",),
    "hyprland-plus": ("hyprland-plus",),
    "touchd": ("touchd-dkms",),
    "write": ("{id}-write",),
    "mdxl": ("mdxl",),
    "fonts": ("{id}-fonts-google-sans-flex",),
}
COMPONENTS = OWN + tuple(OTHER)


class ExperimentError(RuntimeError):
    pass


def packages(component: str, branding: Branding) -> tuple[str, ...]:
    if component in OWN:
        return (branding.package(component),)
    if component in OTHER:
        return tuple(name.format(id=branding.id) for name in OTHER[component])
    raise ExperimentError(f"unknown component {component!r}")


def config_path(branding: Branding | None = None) -> Path:
    b = branding or load_branding()
    return Path("/etc") / b.id / "experiments.json"


def _component_list(value, path: Path) -> list[str]:
    if not isinstance(value, list) or any(x not in COMPONENTS for x in value):
        raise ExperimentError(f"{path} contains an invalid component list")
    return list(dict.fromkeys(value))


def read_config(branding: Branding | None = None) -> dict[str, list[str]]:
    """{"components": [...], "extra": [...]}: components from nexora-experiments, and from the beta source."""
    path = config_path(branding)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {"components": [], "extra": []}
    except (OSError, ValueError) as exc:
        raise ExperimentError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ExperimentError(f"{path} is not a JSON object")
    extra = _component_list(data.get("extra", []), path)
    main = [c for c in _component_list(data.get("components", []), path) if c not in extra]
    return {"components": main, "extra": extra}


def read_enabled(branding: Branding | None = None) -> list[str]:
    """Every enabled component, from either source."""
    config = read_config(branding)
    return [c for c in COMPONENTS if c in config["components"] or c in config["extra"]]


def source_of(component: str, config: dict[str, list[str]]) -> str | None:
    if component in config["extra"]:
        return EXTRA
    if component in config["components"]:
        return MAIN
    return None


def set_enabled(action: str, requested: str, branding: Branding | None = None, *, extra: bool = False,
                pacman_conf: Path = Path("/etc/pacman.conf")) -> list[str]:
    """Enable or disable components. extra=True takes them from the beta source (nexora-experiments-extra)."""
    b = branding or load_branding()
    flag = " --extra" if extra else ""
    if os.geteuid() != 0:
        raise ExperimentError(
            f"changing experimental sources needs root: sudo {b.cli} experiments {action} {requested}{flag}")
    if requested == "all":
        selected = list(COMPONENTS)
    elif requested in COMPONENTS:
        selected = [requested]
    else:
        raise ExperimentError(f"unknown component {requested!r}; choose all or: {', '.join(COMPONENTS)}")
    config = read_config(b)
    main, beta = set(config["components"]), set(config["extra"])
    if action == "enable":
        (beta if extra else main).update(selected)
        (main if extra else beta).difference_update(selected)       # one source per component
    elif action == "disable":
        beta.difference_update(selected)
        if not extra:                                                  # plain `disable` turns it off entirely;
            main.difference_update(selected)                           # `disable --extra` only leaves the beta
    else:
        raise ExperimentError(f"unknown action {action!r}")
    result = {"components": [c for c in COMPONENTS if c in main], "extra": [c for c in COMPONENTS if c in beta]}
    path = config_path(b)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=2) + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)

    conf = pacman_conf
    if not conf.is_file():
        raise ExperimentError(f"{conf} does not exist; cannot configure the experimental repository")
    try:
        text = conf.read_text()
        text = pacmanconf.set_experiments_repo(text, bool(result["components"]), b, MAIN)
        text = pacmanconf.set_experiments_repo(text, bool(result["extra"]), b, EXTRA)
        conf.write_text(text)
    except OSError as exc:
        raise ExperimentError(f"cannot update {conf}: {exc}") from exc
    return [c for c in COMPONENTS if c in main or c in beta]


def status(branding: Branding | None = None) -> list[str]:
    return read_enabled(branding)


def _run(command: list[str], timeout: float) -> str:
    return subprocess.run(command, check=True, text=True, capture_output=True, timeout=timeout).stdout


def newer(candidate: str, installed: str) -> bool:
    """pacman's version order (vercmp), so 1.10 > 1.9 and epochs count."""
    try:
        return int(_run(["vercmp", candidate, installed], 10).strip()) > 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return candidate != installed


def plan(branding: Branding | None = None) -> list[tuple[str, str, str, str]]:
    """(source, package, installed version, experimental version) for every installed package of an enabled
    component whose source has a newer build."""
    b = branding or load_branding()
    config = read_config(b)
    wanted: dict[str, str] = {}                                        # package -> source
    for component in COMPONENTS:
        source = source_of(component, config)
        if source:
            for name in packages(component, b):
                wanted[name] = source
    if not wanted:
        return []
    sources = sorted(set(wanted.values()))
    try:
        installed = {}
        for line in _run(["pacman", "-Q"], 60).splitlines():
            fields = line.split()
            if len(fields) >= 2:
                installed[fields[0]] = fields[1]
        offered: dict[str, dict[str, str]] = {}
        for source in sources:
            offered[source] = {}
            for line in _run(["pacman", "-Sl", source], 30).splitlines():
                fields = line.split()
                if len(fields) >= 3 and fields[0] == source:
                    offered[source][fields[1]] = fields[2]
    except (OSError, subprocess.SubprocessError) as exc:
        raise ExperimentError(
            f"could not query {', '.join(sources)}; refresh pacman databases (sudo pacman -Sy) and check that the "
            f"source is enabled: {exc}"
        ) from exc
    result = []
    for name, source in sorted(wanted.items()):
        version = offered[source].get(name)
        if name in installed and version and newer(version, installed[name]):
            result.append((source, name, installed[name], version))
    return result


def check(branding: Branding | None = None) -> list[str]:
    """Experimental updates waiting, as "package old -> new (source)"."""
    if not read_enabled(branding):
        return []
    return [f"{name} {old} -> {new} ({source})" for source, name, old, new in plan(branding)]


def apply(runner, branding: Branding | None = None, *, interactive: bool = True) -> list[str]:
    if not read_enabled(branding):
        return []
    todo = plan(branding)
    if not todo:
        return []
    print("Experimental CI package updates:")
    for source, name, old, new in todo:
        print(f"  {name} {old} -> {new} ({source})")
    command = ["pacman", "-S", "--needed"] + ([] if interactive else ["--noconfirm"])
    command += [f"{source}/{name}" for source, name, _, _ in todo]
    if os.geteuid() != 0:
        command = ["sudo", *command]
    result = runner.run(command, terminal=interactive, check=False)
    if getattr(result, "returncode", 0):
        raise ExperimentError(f"pacman could not install the published CI packages (exit {result.returncode})")
    return [f"{name} {new}" for _, name, _, new in todo]
