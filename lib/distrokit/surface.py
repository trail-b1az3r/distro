"""Microsoft Surface support (linux-surface kernel and touch/pen stack).

Detection only *recommends* the Surface kernel. It is installed when the user
enables it (installer toggle, or ``<cli> surface enable``), and a user may
enable it on hardware we did not recognise: their choice is respected.
"""

from __future__ import annotations

import re
import subprocess
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


def key_path() -> Path:
    return paths.data("hardware", "surface", config()["repository"]["key_file"])


@dataclass
class SurfaceInfo:
    detected: bool
    model: str
    recommended: bool
    needs_marvell_firmware: bool
    secure_boot: bool | None

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
    marvell = False
    if report.chassis.surface:
        for pattern in config()["marvell"]["models"]:
            if re.search(pattern, model):
                marvell = True
    return SurfaceInfo(
        detected=report.chassis.surface,
        model=model,
        recommended=report.chassis.surface,
        needs_marvell_firmware=marvell,
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
    return f"\n[{repo['name']}]\nServer = {repo['server']}\n"


def plan(info: SurfaceInfo, enabled: bool, secure_boot_mok: bool = False) -> SurfacePlan:
    if not enabled:
        return SurfacePlan(enabled=False)
    cfg = config()["packages"]
    packages = list(cfg["kernel"]) + list(cfg["support"])
    notes = []
    if info.needs_marvell_firmware:
        packages += cfg["marvell"]
    if secure_boot_mok:
        packages += cfg["secureboot"]
        notes.append("Secure Boot: enroll the linux-surface MOK key when prompted after reboot (password: surface).")
    if not info.detected:
        notes.append("The Surface kernel was enabled manually on hardware that was not identified as a Surface.")
    notes.append("The standard kernel stays installed and remains available in the boot menu.")
    return SurfacePlan(enabled=True, packages=packages, repo_block=repo_block(), default_kernel="linux-surface", notes=notes)


def verify_key(path: Path | None = None) -> str:
    """Check the vendored key's fingerprint; returns it or raises."""
    path = path or key_path()
    expected = config()["repository"]["key_fingerprint"].upper()
    if not util.which("gpg"):
        # pacman-key imports through gpg too, so this only happens in odd
        # environments (the check still runs on every real system).
        raise RuntimeError("gpg is required to verify the linux-surface key")
    out = subprocess.run(
        ["gpg", "--show-keys", "--with-colons", str(path)], capture_output=True, text=True, check=True
    ).stdout
    fprs = [line.split(":")[9] for line in out.splitlines() if line.startswith("fpr:")]
    if not fprs or fprs[0].upper() != expected:
        raise RuntimeError(f"linux-surface key fingerprint mismatch: expected {expected}, found {fprs[:1]}")
    return expected


def ensure_repo(root: Path, runner: util.Runner) -> bool:
    """Add the linux-surface repository to pacman.conf and trust its key."""
    conf = root / "etc" / "pacman.conf"
    repo = config()["repository"]
    text = conf.read_text() if conf.is_file() else ""
    changed = False
    if f"[{repo['name']}]" not in text:
        runner._emit(f"add [{repo['name']}] to /etc/pacman.conf")
        if not runner.dry_run:
            util.atomic_write(conf, text.rstrip("\n") + "\n" + repo_block())
        changed = True
    fpr = verify_key() if not runner.dry_run else repo["key_fingerprint"]
    key_dest = root / "usr" / "share" / "pacman" / "keyrings-extra" / "linux-surface.asc"
    if not runner.dry_run:
        key_dest.parent.mkdir(parents=True, exist_ok=True)
        key_dest.write_bytes(key_path().read_bytes())
    in_root_key = "/" + str(key_dest.relative_to(root))
    boot.in_root(runner, root, ["pacman-key", "--add", in_root_key])
    boot.in_root(runner, root, ["pacman-key", "--lsign-key", fpr])
    return changed


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
