"""surface-contrib: the linux-surface fork's extras, packaged and set up per model."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "packages/pkgbuild/surface-contrib"
CLI = PKG / "surface-contrib"


def _share(tmp_path: Path) -> Path:
    share = tmp_path / "share"
    for rel in ("cameras/surface-ipu3-cameras.conf", "cameras/v4l2loopback-load.conf",
                "cameras/wireplumber/51-surface-ipu3-cameras.conf"):
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
    for f in ("etc/modprobe.d/surface-ipu3-cameras.conf", "etc/modules-load.d/v4l2loopback-surface.conf",
              "etc/wireplumber/wireplumber.conf.d/51-surface-ipu3-cameras.conf"):
        assert (root / f).is_file(), f
    # surface-camd creates its own loopback devices: no v4l2loopback options line to fight other programs'
    assert not (root / "etc/modprobe.d/v4l2loopback-surface.conf").exists()
    assert (root / "etc/modules-load.d/surface-ipu3-cameras.conf").read_text() == "ipu3_cio2\n"
    calls = (tmp_path / "calls").read_text()
    for cam in ("front", "rear", "ir"):
        assert f"enable surface-camd@{cam}.service" in calls
    assert "start with the next boot" in res.stdout  # a root other than / is never started
    assert "Configuration: on" in _run(tmp_path, "Surface Pro 6", "cameras", "status").stdout
    res = _run(tmp_path, "Surface Pro 6", "cameras", "off")
    assert res.returncode == 0 and not (root / "etc/modules-load.d/v4l2loopback-surface.conf").exists()
    assert "Configuration: off" in _run(tmp_path, "Surface Pro 6", "cameras", "status").stdout
    assert "disable surface-camd@ir.service" in (tmp_path / "calls").read_text()


OLD_OPTIONS = ('options v4l2loopback devices=3 video_nr=50,51,52 card_label="Surface Front Camera",'
               '"Surface Rear Camera","Surface IR Camera" exclusive_caps=1,1,1')


def test_upgrade_removes_the_old_loopback_options(tmp_path):
    """Older surface-contrib wrote a v4l2loopback options file; it fought other programs' options and is not
    needed any more, so the upgrade removes it."""
    old = tmp_path / "root/etc/modprobe.d/v4l2loopback-surface.conf"
    old.parent.mkdir(parents=True)
    old.write_text("# v4l2loopback devices that surface-camd publishes the cameras on.\n\n" + OLD_OPTIONS + "\n")
    res = _run(tmp_path, "Surface Pro", "cameras", "migrate", sku="Surface_Pro_1796")
    assert res.returncode == 0, res.stderr
    assert not old.exists() and "Removed" in res.stdout
    # nothing to do the second time
    assert _run(tmp_path, "Surface Pro", "cameras", "migrate").returncode == 0


def test_upgrade_keeps_changed_loopback_options(tmp_path):
    old = tmp_path / "root/etc/modprobe.d/v4l2loopback-surface.conf"
    old.parent.mkdir(parents=True)
    old.write_text(OLD_OPTIONS.replace("devices=3", "devices=4") + "\n")  # an administrator's edit
    res = _run(tmp_path, "Surface Pro", "cameras", "migrate")
    assert res.returncode == 0 and old.exists() and "kept" in res.stdout


def test_cameras_on_removes_the_old_loopback_options(tmp_path):
    old = tmp_path / "root/etc/modprobe.d/v4l2loopback-surface.conf"
    old.parent.mkdir(parents=True)
    old.write_text(OLD_OPTIONS + "\n")
    assert _run(tmp_path, "Surface Book 2", "cameras", "on").returncode == 0
    assert not old.exists()


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
    assert "surface-contrib cameras migrate" in install and "try-restart" in install
    # the fork dropped this file: installing it would fail the package build
    assert "v4l2loopback-surface.conf\" \\" not in text and "surface-camd/v4l2loopback-surface.conf" not in text


def test_touch_on_off_and_status(tmp_path):
    res = _run(tmp_path, "Surface Pro", "touch", "on")
    assert res.returncode == 0, res.stderr
    assert "enable surface-touchd.service" in (tmp_path / "calls").read_text()
    assert "next boot" in res.stdout and "input group" in res.stdout  # a root other than / is never started
    res = _run(tmp_path, "Surface Pro", "touch", "off")
    assert res.returncode == 0 and "disable surface-touchd.service" in (tmp_path / "calls").read_text()
    assert "surface-touchd:" in _run(tmp_path, "Surface Pro", "touch", "status").stdout
    assert _run(tmp_path, "Surface Pro", "touch", "sideways").returncode == 2


def _install_hook(tmp_path: Path, product: str, func: str, *args: str) -> str:
    """Run a function of surface-contrib.install with surface-contrib, systemctl and vercmp stubbed; return the
    commands it ran."""
    dmi = tmp_path / "dmi"
    dmi.mkdir(exist_ok=True)
    (dmi / "product_name").write_text(product + "\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "hook-calls"
    for name in ("surface-contrib", "systemctl"):
        (bin_dir / name).write_text(f'#!/bin/sh\necho "{name} $*" >> {log}\n')
        (bin_dir / name).chmod(0o755)
    # vercmp prints -1, 0 or 1 like pacman's
    (bin_dir / "vercmp").write_text('#!/bin/sh\n[ "$1" = "$2" ] && echo 0 || '
                                    '{ [ "$(printf "%s\\n%s\\n" "$1" "$2" | sort -V | head -1)" = "$1" ] && echo -1 || echo 1; }\n')
    (bin_dir / "vercmp").chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "SURFACE_CONTRIB_DMI": str(dmi)}
    script = f'. "{PKG / "surface-contrib.install"}"; {func} {" ".join(args)}'
    subprocess.run(["bash", "-c", script], env=env, check=True, capture_output=True, timeout=30)
    return log.read_text() if log.exists() else ""


def test_upgrade_turns_touch_on_once(tmp_path):
    # from a version without surface-touchd: turned on (and started where it was enabled) ...
    calls = _install_hook(tmp_path, "Surface Pro", "post_upgrade", "2026.11.20-1", "2026.11.16-1")
    assert "surface-contrib touch on --no-start" in calls and "systemctl start surface-touchd.service" in calls
    assert "surface-contrib cameras migrate" in calls and "try-restart surface-camd@*.service" in calls
    # ... but a later upgrade keeps whatever the administrator chose
    (tmp_path / "hook-calls").unlink()
    calls = _install_hook(tmp_path, "Surface Pro", "post_upgrade", "2026.11.21-1", "2026.11.20-1")
    assert "touch on" not in calls and "cameras migrate" in calls


def test_touch_only_on_surfaces(tmp_path):
    calls = _install_hook(tmp_path, "ThinkPad X1", "post_upgrade", "2026.11.20-1", "2026.11.16-1")
    assert "touch on" not in calls and "start surface-touchd" not in calls
    calls = _install_hook(tmp_path, "Surface Laptop 4", "post_install")
    assert "surface-contrib touch on --no-start" in calls and "start surface-touchd" not in calls  # next boot


def test_package_includes_surface_touch():
    text = (PKG / "PKGBUILD.in").read_text()
    assert 'make -C "$srcdir/linux-surface/contrib/surface-touch"' in text  # built ...
    assert 'make -C "$srcdir/linux-surface/contrib/surface-touch" test' in text  # ... tested in check()
    assert 'make -C "$contrib/surface-touch" install' in text and "backup=('etc/surface-touchd.conf')" in text
    assert "disable --now surface-touchd.service" in (PKG / "surface-contrib.install").read_text()
    # the fork's standalone surface-camd / surface-touch packages own the same files
    assert "conflicts=('surface-camd' 'surface-touch')" in text and "provides=('surface-camd' 'surface-touch')" in text
