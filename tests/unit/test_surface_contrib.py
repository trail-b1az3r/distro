"""surface-contrib: the linux-surface fork's extras, packaged and set up per model."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "packages/pkgbuild/surface-contrib"
CLI = PKG / "surface-contrib"


def _share(tmp_path: Path) -> Path:
    share = tmp_path / "share"
    for rel in ("cameras/surface-ipu3-cameras.conf",
                "cameras/v4l2loopback-load.conf", "cameras/wireplumber/51-surface-ipu3-cameras.conf"):
        (share / rel).parent.mkdir(parents=True, exist_ok=True)
        (share / rel).write_text(rel + "\n")
    return share


def _run(tmp_path: Path, product: str, *args: str, sku: str = "") -> subprocess.CompletedProcess:
    dmi = tmp_path / "dmi"
    dmi.mkdir(exist_ok=True)
    (dmi / "product_name").write_text(product + "\n")
    (dmi / "product_sku").write_text(sku + "\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "systemctl").write_text(f'#!/bin/sh\necho "systemctl $*" >> {tmp_path}/calls\n')
    (bin_dir / "systemctl").chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "SURFACE_CONTRIB_DMI": str(dmi),
           "SURFACE_CONTRIB_SHARE": str(_share(tmp_path)), "SURFACE_CONTRIB_ROOT": str(tmp_path / "root")}
    return subprocess.run(["bash", str(CLI), *args], capture_output=True, text=True, env=env, timeout=30)


def test_models(tmp_path):
    assert _run(tmp_path, "Surface Pro", "model", sku="Surface_Pro_1796").stdout.split() == ["ipu3", "pro5"]
    assert _run(tmp_path, "Surface Book 2", "model").stdout.split() == ["ipu3"]
    assert _run(tmp_path, "Surface Pro 7+", "model").stdout.split() == ["pro7plus"]
    assert _run(tmp_path, "Surface Pro 9", "model").stdout.split() == []


def test_cameras_on_and_off(tmp_path):
    root = tmp_path / "root"
    res = _run(tmp_path, "Surface Pro 6", "cameras", "on")
    assert res.returncode == 0, res.stderr
    for f in ("etc/modprobe.d/surface-ipu3-cameras.conf",
              "etc/modules-load.d/v4l2loopback-surface.conf", "etc/wireplumber/wireplumber.conf.d/51-surface-ipu3-cameras.conf"):
        assert (root / f).is_file(), f
    # surface-camd makes its own loopback devices: no v4l2loopback options file.
    assert not (root / "etc/modprobe.d/v4l2loopback-surface.conf").exists()
    assert (root / "etc/modules-load.d/surface-ipu3-cameras.conf").read_text() == "ipu3_cio2\n"
    calls = (tmp_path / "calls").read_text()
    for cam in ("front", "rear", "ir"):
        assert f"enable surface-camd@{cam}.service" in calls
    assert "start with the next boot" in res.stdout  # a root other than / is never started
    res = _run(tmp_path, "Surface Pro 6", "cameras", "off")
    assert res.returncode == 0 and not (root / "etc/modules-load.d/surface-ipu3-cameras.conf").exists()
    assert "disable surface-camd@ir.service" in (tmp_path / "calls").read_text()


def test_an_older_options_file_is_cleared(tmp_path):
    stale = tmp_path / "root/etc/modprobe.d/v4l2loopback-surface.conf"
    stale.parent.mkdir(parents=True)
    stale.write_text("options v4l2loopback video_nr=50,51,52\n")
    assert _run(tmp_path, "Surface Pro 6", "cameras", "on").returncode == 0
    assert not stale.exists()
    install = (PKG / "surface-contrib.install").read_text()
    assert "rm -f /etc/modprobe.d/v4l2loopback-surface.conf" in install
    assert "v4l2loopback-surface.conf" not in (PKG / "PKGBUILD.in").read_text()


def test_location_runs_the_forks_setup(tmp_path):
    share = _share(tmp_path)
    (share / "location").mkdir()
    (share / "location/surface-location-setup.sh").write_text('echo "location $*"\n')
    env = {"PATH": "/usr/bin:/bin", "SURFACE_CONTRIB_SHARE": str(share)}
    res = subprocess.run(["bash", str(CLI), "location", "--test"], capture_output=True, text=True, env=env, timeout=30)
    assert res.stdout.strip() == "location --test"
    assert "surface-location/surface-location-setup.sh" in (PKG / "PKGBUILD.in").read_text()
    assert "location [--fix|--test]" in subprocess.run(["bash", str(CLI), "--help"], capture_output=True, text=True).stdout


def test_cameras_only_on_ipu3_models(tmp_path):
    res = _run(tmp_path, "Surface Pro 7", "cameras", "on")
    assert res.returncode == 0 and "nothing to do" in res.stdout
    assert not (tmp_path / "root/etc").exists()


def test_package_builds_from_the_fork():
    text = (PKG / "PKGBUILD.in").read_text()
    assert "git+https://github.com/trail-b1az3r/linux-surface.git#commit=" in text
    assert "check()" in text and "make -C" in text and "surface-camd@.service" in text
    assert os.access(CLI, os.X_OK)
    install = (PKG / "surface-contrib.install").read_text()
    assert "surface-contrib cameras on --no-start" in install
