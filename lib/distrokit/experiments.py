"""Rolling experimental package list published with the Nexora CI packages."""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from . import pacmanconf
from .branding import Branding, load as load_branding

COMPONENTS = ("core", "branding", "desktop", "welcome", "installer", "ai")
MANIFEST_URL = "https://github.com/trail-b1az3r/distro/releases/download/nexora-experiments/packages.json"


class ExperimentError(RuntimeError):
    pass


def config_path(branding: Branding | None = None) -> Path:
    b = branding or load_branding()
    return Path("/etc") / b.id / "experiments.json"


def read_enabled(branding: Branding | None = None) -> list[str]:
    path = config_path(branding)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise ExperimentError(f"cannot read {path}: {exc}") from exc
    enabled = data.get("components", []) if isinstance(data, dict) else []
    if not isinstance(enabled, list) or any(x not in COMPONENTS for x in enabled):
        raise ExperimentError(f"{path} contains an invalid component list")
    return list(dict.fromkeys(enabled))


def set_enabled(action: str, requested: str, branding: Branding | None = None) -> list[str]:
    b = branding or load_branding()
    if os.geteuid() != 0:
        raise ExperimentError(f"changing experimental sources needs root: sudo {b.cli} experiments {action} {requested}")
    if requested == "all":
        selected = list(COMPONENTS)
    elif requested in COMPONENTS:
        selected = [requested]
    else:
        raise ExperimentError(f"unknown component {requested!r}; choose all or: {', '.join(COMPONENTS)}")
    enabled = set(read_enabled(b))
    if action == "enable":
        enabled.update(selected)
    elif action == "disable":
        enabled.difference_update(selected)
    else:
        raise ExperimentError(f"unknown action {action!r}")
    result = [c for c in COMPONENTS if c in enabled]
    path = config_path(b)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"components": result}, indent=2) + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)

    conf = Path("/etc/pacman.conf")
    if not conf.is_file():
        raise ExperimentError(f"{conf} does not exist; cannot configure the experimental repository")
    try:
        current = conf.read_text()
        conf.write_text(pacmanconf.set_experiments_repo(current, bool(result), b))
    except OSError as exc:
        raise ExperimentError(f"cannot update {conf}: {exc}") from exc
    return result


def status(branding: Branding | None = None) -> list[str]:
    return read_enabled(branding)


def fetch_manifest(timeout: float = 15.0) -> dict:
    """Read the public rolling package manifest; never use the Actions artifacts API."""
    request = urllib.request.Request(
        MANIFEST_URL,
        headers={"User-Agent": "Nexora-updater/1", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise ExperimentError(f"could not fetch the public CI package list: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("packages"), list):
        raise ExperimentError("the published CI package list is invalid or unsupported")
    return data


def check(branding: Branding | None = None) -> list[str]:
    """Compare installed packages with the versions in the latest CI release manifest."""
    if not read_enabled(branding):
        return []
    manifest = fetch_manifest()
    try:
        installed_result = subprocess.run(
            ["pacman", "-Q"], check=True, text=True, capture_output=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ExperimentError(f"could not read installed pacman packages: {exc}") from exc
    installed = {}
    for line in installed_result.stdout.splitlines():
        fields = line.split(None, 1)
        if len(fields) == 2:
            installed[fields[0]] = fields[1]
    updates = []
    for package in manifest["packages"]:
        if not isinstance(package, dict):
            continue
        name, new = package.get("name"), package.get("version")
        current = installed.get(name) if isinstance(name, str) else None
        if not current or not isinstance(new, str) or current == new:
            continue
        try:
            comparison = subprocess.run(
                ["vercmp", current, new], check=True, text=True, capture_output=True, timeout=5
            )
            if int(comparison.stdout.strip()) < 0:
                updates.append(f"{name} {current} -> {new}")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise ExperimentError(f"could not compare {name} versions ({current}, {new}): {exc}") from exc
    return sorted(updates)


def apply(runner, branding: Branding | None = None, *, interactive: bool = True) -> list[str]:
    updates = check(branding)
    if not updates:
        return []
    print("Experimental CI package updates:")
    for item in updates:
        print(f"  {item}")
    command = ["pacman", "-Syu"] + ([] if interactive else ["--noconfirm"])
    if os.geteuid() != 0:
        command = ["sudo", *command]
    result = runner.run(command, terminal=interactive, check=False)
    if getattr(result, "returncode", 0):
        raise ExperimentError(f"pacman could not install the published CI packages (exit {result.returncode})")
    return updates
