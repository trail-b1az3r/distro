"""An old hyprland-plus built from source into /usr/local hides the packaged one: found, and moved aside (never
deleted) by the package's install script and `<cli> repair hyprland`."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from distrokit.system import compositor, doctor, repair

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "packages/pkgbuild/hyprland-plus/hyprland-plus.install"


def system(tmp_path: Path, *, package: bool = True, local: bytes | None = b"\x7fELF ... hyprland-plus 0.57.0.p3 ...",
           session: bool = True) -> Path:
    root = tmp_path / "root"
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/bin/Hyprland").write_bytes(b"\x7fELF hyprland-plus 0.57.1.p1")
    if package:
        (root / "var/lib/pacman/local/hyprland-plus-0.57.1.p1-1").mkdir(parents=True)
    if local is not None:
        bin_dir = root / "usr/local/bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "Hyprland").write_bytes(local)
        os.symlink("Hyprland", bin_dir / "hyprland")
        for name in ("hyprctl", "start-hyprland"):
            (bin_dir / name).write_bytes(b"#!/bin/sh\n")
        (bin_dir / "unrelated-tool").write_bytes(b"keep me")
        if session:
            (root / "usr/local/share/wayland-sessions").mkdir(parents=True)
            (root / "usr/local/share/wayland-sessions/hyprland.desktop").write_text("Exec=/usr/local/bin/start-hyprland\n")
    return root


def test_found_only_when_it_hides_the_package(tmp_path):
    root = system(tmp_path)
    names = sorted(p.name for p in compositor.stale_local_build(root))
    assert names == ["Hyprland", "hyprctl", "hyprland", "hyprland.desktop", "start-hyprland"]
    assert compositor.stale_local_build(system(tmp_path / "a", package=False)) == [], "then it is the only Hyprland"
    assert compositor.stale_local_build(system(tmp_path / "b", local=b"\x7fELF stock Hyprland")) == [], \
        "someone's own stock build is theirs"
    assert compositor.stale_local_build(system(tmp_path / "c", local=None)) == []


def test_the_mark_is_found_across_read_chunks(tmp_path):
    path = tmp_path / "bin"
    path.write_bytes(b"x" * 10 + b"hyprland-plus" + b"y" * 10)
    assert compositor._contains(path, b"hyprland-plus", chunk=16)        # the mark straddles two chunks
    assert not compositor._contains(path, b"aquamarine", chunk=16)


def test_repair_moves_it_aside(tmp_path):
    root = system(tmp_path)
    plan = repair.hyprland_plan(root)
    assert len(plan.actions) == 1 and plan.actions[0].destructive
    assert plan.execute(log=lambda _: None) == []
    assert not (root / "usr/local/bin/Hyprland").exists() and not (root / "usr/local/bin/hyprland").is_symlink()
    assert (root / "usr/local/bin/unrelated-tool").read_bytes() == b"keep me"
    kept = list((root / compositor.RETIRED).iterdir())
    assert len(kept) == 1
    assert (kept[0] / "bin/Hyprland").read_bytes().startswith(b"\x7fELF")
    assert (kept[0] / "share/wayland-sessions/hyprland.desktop").is_file()
    assert repair.hyprland_plan(root).actions == [], "nothing left to do"


def test_doctor_names_it(tmp_path):
    root = system(tmp_path)
    check = doctor.Doctor(root).compositor()
    assert check.status == doctor.FAIL and check.fix.endswith("repair hyprland")
    assert any(d.endswith("usr/local/bin/Hyprland") for d in check.details)
    assert doctor.Doctor(system(tmp_path / "ok", local=None)).compositor().status == doctor.OK


@pytest.mark.parametrize("hook", ["post_install", "post_upgrade"])
def test_package_install_script(tmp_path, hook):
    """The script uses absolute /usr/local paths; run it with them pointed into a scratch root."""
    root = system(tmp_path)
    script = INSTALL.read_text().replace("/usr/local", str(root / "usr/local"))
    out = subprocess.run(["bash", "-c", f"{script}\n{hook}"], capture_output=True, text=True, check=True).stdout
    assert "now in" in out
    assert not (root / "usr/local/bin/Hyprland").exists()
    assert (root / "usr/local/bin/unrelated-tool").exists()
    kept = next((root / "usr/local/lib/hyprland-plus-retired").iterdir())
    assert sorted(p.name for p in (kept / "bin").iterdir()) == ["Hyprland", "hyprctl", "hyprland", "start-hyprland"]
    # Run again: nothing more to move, nothing printed.
    again = subprocess.run(["bash", "-c", f"{script}\n{hook}"], capture_output=True, text=True, check=True).stdout
    assert again == ""


def test_install_script_leaves_a_stock_build(tmp_path):
    root = system(tmp_path, local=b"\x7fELF stock Hyprland")
    script = INSTALL.read_text().replace("/usr/local", str(root / "usr/local"))
    subprocess.run(["bash", "-c", f"{script}\npost_upgrade"], check=True)
    assert (root / "usr/local/bin/Hyprland").exists()


def test_package_ships_the_script():
    pkgbuild = (ROOT / "packages/pkgbuild/hyprland-plus/PKGBUILD.in").read_text()
    assert "install=hyprland-plus.install" in pkgbuild and "replaces=(hyprland-plus-local)" in pkgbuild
