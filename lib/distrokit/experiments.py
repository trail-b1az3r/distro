"""Opt-in pacman repository for packages from the latest successful Nexora CI run."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import pacmanconf
from .branding import Branding, load as load_branding

COMPONENTS = ("core", "branding", "desktop", "welcome", "installer", "ai")


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


def check(branding: Branding | None = None) -> list[str]:
    # The experimental repository is an ordinary pacman source. pacman -Qu
    # and -Syu already include it, so there is no separate artifact check.
    return []


def apply(runner, branding: Branding | None = None, *, interactive: bool = True) -> list[str]:
    # pacman -Syu in the normal updater installs experimental packages from
    # [nexora-experiments] according to pacman's repository priority/version.
    return []
