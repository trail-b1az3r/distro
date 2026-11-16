"""Microsoft Surface support (linux-surface kernel and touch/pen stack).

Everything comes from the [nexora-surface] repository, built from the distribution's linux-surface fork
(hardware/surface/surface.toml, .github/workflows/surface.yml); linux-surface's own package server is not used, and
its repository is taken out of pacman.conf when Surface support is enabled.

Detection only *recommends* the Surface kernel. It is installed when the user
enables it (installer toggle, or ``<cli> surface enable``), and a user may
enable it on hardware we did not recognise: their choice is respected.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import boot, paths, pkg, util
from .branding import Branding, load as load_branding
from .hardware.report import HardwareReport


def config() -> dict[str, Any]:
    with (paths.data("hardware", "surface", "surface.toml")).open("rb") as fh:
        return tomllib.load(fh)


@dataclass
class SurfaceInfo:
    detected: bool
    model: str
    recommended: bool
    needs_marvell_firmware: bool
    secure_boot: bool | None
    # Front, rear and IR cameras on an Intel IPU3, driven by surface-camd (surface-contrib).
    has_ipu3_cameras: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["message"] = self.message
        return d

    @property
    def message(self) -> str:
        if self.detected:
            return f"Microsoft {self.model} detected. The Surface kernel is recommended for touch, pen, cameras and battery reporting."
        return "No Surface hardware detected. Enable the Surface kernel only for Microsoft Surface devices."


def detect(report: HardwareReport) -> SurfaceInfo:
    model = report.chassis.surface_model
    marvell = cameras = False
    if report.chassis.surface:
        name = report.chassis.product_name or model
        marvell = any(re.search(p, name) for p in config()["marvell"]["models"])
        cameras = any(re.search(p, name) for p in config().get("cameras", {}).get("models", []))
    return SurfaceInfo(
        detected=report.chassis.surface,
        model=model,
        recommended=report.chassis.surface,
        needs_marvell_firmware=marvell,
        has_ipu3_cameras=cameras,
        secure_boot=report.firmware.secure_boot,
    )


@dataclass
class SurfacePlan:
    enabled: bool
    packages: list[str] = field(default_factory=list)
    repo_block: str = ""
    default_kernel: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def repo_block() -> str:
    repo = config()["repository"]
    siglevel = f"SigLevel = {repo['siglevel']}\n" if repo.get("siglevel") else ""
    return f"\n[{repo['name']}]\n{siglevel}Server = {repo['server']}\n"


def without_sections(text: str, names: list[str]) -> str:
    """pacman.conf text without the given repository sections (header to the next header)."""
    out: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        header = re.match(r"\s*\[([^\]]+)\]\s*$", line)
        if header:
            skipping = header.group(1) in names
        if not skipping:
            out.append(line)
    return "".join(out)


def plan(info: SurfaceInfo, enabled: bool, secure_boot_mok: bool = False) -> SurfacePlan:
    if not enabled:
        return SurfacePlan(enabled=False)
    cfg = config()["packages"]
    packages = list(cfg["kernel"]) + list(cfg["support"])
    notes = []
    if info.needs_marvell_firmware:
        packages += cfg["marvell"]
    if info.has_ipu3_cameras:
        packages += cfg.get("cameras", [])
        notes.append("Cameras: front, rear and IR through surface-camd (/dev/video50-52); surface-contrib cameras status.")
    if secure_boot_mok:
        packages += cfg["secureboot"]
        notes.append("Secure Boot: the Surface kernel is signed on this machine with sbctl (the installer's Secure Boot "
                     "option), not with linux-surface's MOK key.")
    if not info.detected:
        notes.append("The Surface kernel was enabled manually on hardware that was not identified as a Surface.")
    notes.append("The standard kernel stays installed and remains available in the boot menu.")
    return SurfacePlan(enabled=True, packages=packages, repo_block=repo_block(), default_kernel="linux-surface", notes=notes)


def ensure_repo(root: Path, runner: util.Runner) -> bool:
    """Add the [nexora-surface] repository to pacman.conf, and take out linux-surface's own."""
    conf = root / "etc" / "pacman.conf"
    repo = config()["repository"]
    text = conf.read_text() if conf.is_file() else ""
    new = text
    old = [name for name in repo.get("replaces", []) if f"[{name}]" in new]
    if old:
        runner._emit(f"remove [{'], ['.join(old)}] from /etc/pacman.conf (replaced by [{repo['name']}])")
        new = without_sections(new, old)
    if f"[{repo['name']}]" not in new:
        runner._emit(f"add [{repo['name']}] to /etc/pacman.conf")
        new = new.rstrip("\n") + "\n" + repo_block()
    if new != text and not runner.dry_run:
        util.atomic_write(conf, new)
    return new != text


def apply(sp: SurfacePlan, *, root: Path | str = "/", runner: util.Runner | None = None,
          branding: Branding | None = None, update_boot: bool = True) -> None:
    if not sp.enabled:
        return
    root = Path(root)
    runner = runner or util.Runner()
    branding = branding or load_branding()
    ensure_repo(root, runner)
    pkg.install(sp.packages, runner, root, refresh=True)
    cfg = boot.load_config(root, branding)
    if cfg is not None:
        cfg.default_kernel = sp.default_kernel
        if not runner.dry_run:
            boot.save_config(cfg, root, branding)
    if update_boot and not runner.dry_run and cfg is not None:
        runner._emit(boot.update(root, runner, branding))
    if not runner.dry_run:
        util.write_json(branding.system_paths(root).state / "surface.json", sp.to_dict())


def disable(*, root: Path | str = "/", runner: util.Runner | None = None, branding: Branding | None = None) -> list[str]:
    """Remove the Surface kernel and packages; the standard kernel becomes default."""
    root = Path(root)
    runner = runner or util.Runner()
    branding = branding or load_branding()
    cfgp = config()["packages"]
    removed = pkg.remove(cfgp["kernel"] + cfgp["support"] + cfgp["secureboot"], runner, root)
    cfg = boot.load_config(root, branding)
    if cfg is not None and cfg.default_kernel == "linux-surface":
        cfg.default_kernel = ""
        if not runner.dry_run:
            boot.save_config(cfg, root, branding)
            runner._emit(boot.update(root, runner, branding))
    return removed
