"""ISO assembly: the archiso profile generated from releng and iso/."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from distrokit import pacmanconf
from distrokit.branding import load as load_branding
from distrokit.build import iso

# The parts of archiso's releng profile the assembler touches.
RELENG_FILES = {
    "profiledef.sh": 'iso_name="archlinux"\n',
    "packages.x86_64": "base\n",
    "pacman.conf": "[core]\n",
    "bootstrap_packages": "base\n",
    "efiboot/loader/loader.conf": "timeout 15\n",
    "efiboot/loader/entries/01-archiso-linux.conf": "title Arch\n",
    "grub/grub.cfg": "",
    "syslinux/syslinux.cfg": "",
    "syslinux/archiso_sys-linux.cfg": "MENU LABEL Arch Linux install medium\n",
    "airootfs/etc/mkinitcpio.conf.d/archiso.conf": "HOOKS=(base udev archiso)\n",
    "airootfs/etc/passwd": "root:x:0:0:root:/root:/usr/bin/zsh\n",
    "airootfs/etc/shadow": "root::14871::::::\n",
    "airootfs/etc/motd": "Arch Linux\n",
    "airootfs/etc/hostname": "archiso\n",
    "airootfs/root/.automated_script.sh": "#!/bin/sh\n",
    "airootfs/etc/systemd/network/20-ethernet.network": "",
    "airootfs/etc/systemd/system/getty@tty1.service.d/autologin.conf": "",
    "airootfs/etc/systemd/system/pacman-init.service": "[Service]\n",
}
RELENG_LINKS = {
    "airootfs/etc/systemd/system/multi-user.target.wants/sshd.service": "/usr/lib/systemd/system/sshd.service",
    "airootfs/etc/systemd/system/multi-user.target.wants/iwd.service": "/usr/lib/systemd/system/iwd.service",
    "airootfs/etc/systemd/system/multi-user.target.wants/pacman-init.service": "/etc/systemd/system/pacman-init.service",
    "airootfs/etc/resolv.conf": "/run/systemd/resolve/stub-resolv.conf",
}


@pytest.fixture
def releng(tmp_path):
    root = tmp_path / "releng"
    for rel, text in RELENG_FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    for rel, target in RELENG_LINKS.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).symlink_to(target)
    return root


def test_names_follow_distro_conf():
    b = load_branding()
    epoch = 1790393700  # 2026-09-26
    assert iso.iso_version(b, epoch) == "2026.09"
    assert iso.iso_filename(b, "2026.09") == f"{b.name}-2026.09-x86_64.iso"
    assert iso.iso_label(b, epoch) == f"{b['ISO_LABEL_PREFIX']}_202609"


def test_assemble_profile(tmp_path, releng):
    b = load_branding()
    opts = iso.Options(profile="ai", offline="full", build=tmp_path / "build", releng=releng)
    offline = opts.offline_repo
    offline.mkdir(parents=True)
    (offline / "nexora-core-1-1-any.pkg.tar.zst").write_bytes(b"pkg")
    prof = iso.assemble(opts, b, epoch=1790393700)
    air = prof / "airootfs"

    # releng's Arch branding, root autologin, sshd and networkd are gone.
    assert not (prof / "grub").exists()
    assert not (prof / "efiboot/loader/entries/01-archiso-linux.conf").exists()
    assert not (air / "root/.automated_script.sh").exists()
    assert not (air / "etc/systemd/system/multi-user.target.wants/sshd.service").is_symlink()
    assert not (air / "etc/systemd/system/multi-user.target.wants/iwd.service").is_symlink()
    assert not (air / "etc/systemd/network").exists()
    assert not (air / "etc/resolv.conf").is_symlink()
    # Kept: keyring initialisation and the archiso initramfs.
    assert (air / "etc/systemd/system/multi-user.target.wants/pacman-init.service").is_symlink()
    assert (air / "etc/mkinitcpio.conf.d/archiso.conf").is_file()

    # profiledef.sh parses and names the ISO after distro.conf.
    out = subprocess.run(["bash", "-c", 'declare -A file_permissions; source profiledef.sh; '
                          'echo "$iso_name|$iso_label|$iso_version|${bootmodes[*]}|${file_permissions[/etc/shadow]}"'],
                         cwd=prof, capture_output=True, text=True, check=True).stdout.strip()
    assert out == f"{b.name}|{b['ISO_LABEL_PREFIX']}_202609|2026.09|bios.syslinux uefi.systemd-boot|0:0:400"

    # Boot menus are branded and keep archiso's placeholders.
    entry = (prof / "efiboot/loader/entries/01-live.conf").read_text()
    assert b.pretty_name in entry and "archisosearchuuid=%ARCHISO_UUID%" in entry
    safe = (prof / "syslinux/archiso_sys-linux.cfg").read_text()
    assert f"{b.id}.safe_graphics=1" in safe and "nomodeset" in safe and "Arch Linux" not in safe
    assert "@" not in (prof / "syslinux/archiso_head.cfg").read_text()

    packages = (prof / "packages.x86_64").read_text().split()
    for name in (f"{b.id}-installer", f"{b.id}-desktop", "linux", "greetd", "cage", "mkinitcpio-archiso",
                 "illogical-impulse-hyprland", "memtest86+-efi", "edk2-shell"):
        assert name in packages, name

    # mkarchiso installs from the freshly built repository.
    assert f"Server = file://{opts.repo.resolve()}" in (prof / "pacman.conf").read_text()
    # The live system and the installer know the offline repository.
    live = (air / "etc/pacman.conf").read_text()
    assert f"[{b.repo_name}-offline]" in live and f"file:///var/cache/{b.id}/repo" in live
    assert (air / f"etc/{b.id}/pacman-offline.conf").read_text() == pacmanconf.render(
        "offline", b, offline_repo=f"/var/cache/{b.id}/repo")
    assert (air / f"var/cache/{b.id}/repo/nexora-core-1-1-any.pkg.tar.zst").read_bytes() == b"pkg"

    info = json.loads((air / f"etc/{b.id}/iso-build.json").read_text())
    assert info["profile"] == "ai" and info["offline"] == "full" and info["version"] == "2026.09"
    assert (air / f"etc/{b.id}/live").is_file()

    # Live session: greetd autologin, NetworkManager, the live user service.
    systemd = air / "etc/systemd/system"
    assert os.readlink(systemd / "display-manager.service").endswith("/greetd.service")
    for unit in ("NetworkManager.service", "bluetooth.service", f"{b.id}-live-setup.service"):
        assert (systemd / "multi-user.target.wants" / unit).is_symlink()
    greetd = (air / "etc/greetd/config.toml").read_text()
    assert f'user = "{b["LIVE_USER"]}"' in greetd and f"{b.id}-live-session" in greetd
    sudoers = (air / f"etc/sudoers.d/10-{b.id}-live").read_text()
    assert sudoers.strip().endswith(f"{b['LIVE_USER']} ALL=(ALL:ALL) NOPASSWD: ALL")
    assert (air / "etc/shadow").read_text().startswith("root:!*:")  # no empty root password
    for script in (f"{b.id}-live-session", f"{b.id}-live-setup"):
        subprocess.run(["bash", "-n", str(air / f"usr/lib/{b.id}/bin/{script}")], check=True)


def test_offline_sets_keep_conflicting_stacks_apart():
    b = load_branding()
    sets = iso.offline_sets(b, "standard")
    base = set(sets[0])
    assert {"linux", "linux-headers", "grub", "sbctl", "llama.cpp-vulkan"} <= base
    assert "visual-studio-code-bin" not in base
    nvidia = [s for s in sets if "nvidia-utils" in s]
    assert any("nvidia-open" in s and "nvidia-open-dkms" not in s for s in nvidia)  # prebuilt variant
    assert any("nvidia-open-dkms" in s and "linux-headers" in s for s in nvidia)
    assert not any({"nvidia-utils", "nvidia-580xx-utils"} <= set(s) for s in sets)
    assert not any("cuda" in s for s in sets)  # compute toolkits stay online-only


def test_dry_run_build_commands(tmp_path, releng, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1790393700")
    opts = iso.Options(profile="standard", build=tmp_path / "b", dist=tmp_path / "dist", releng=releng)
    from distrokit import util

    runner = util.Runner(dry_run=True)
    result = iso.build(opts, runner)
    cmds = result["commands"]
    assert any("distrokit.build.packages build" in c for c in cmds)
    assert any(c.startswith("repo-add --new") and c.split()[2].endswith(f"{load_branding().repo_name}-offline.db.tar.gz")
               for c in cmds)
    mk = next(c for c in cmds if c.startswith("mkarchiso"))
    assert " -r " in mk and mk.endswith(str(opts.profile_dir))
    assert not any("-Sw" in c for c in cmds)  # minimal offline repository downloads nothing


def test_checksums_and_finish(tmp_path, releng, monkeypatch):
    b = load_branding()
    opts = iso.Options(build=tmp_path / "build", dist=tmp_path / "out" / "dist", releng=releng)
    opts.out.mkdir(parents=True)
    (opts.out / "whatever.iso").write_bytes(b"iso9660" * 1000)
    (opts.work / "iso/arch").mkdir(parents=True)
    (opts.work / "iso/arch/pkglist.x86_64.txt").write_text("base 3-2\nlinux 6.16-1\n")
    from distrokit import util

    info = iso.finish(opts, b, 1790393700, util.Runner(dry_run=True))
    name = f"{b.name}-2026.09-x86_64.iso"
    assert info["iso"] == name and (opts.dist / name).is_file()
    root = opts.dist.parent
    sha = (root / "checksums" / f"{name}.sha256").read_text().split()
    assert sha[1] == name and len(sha[0]) == 64
    subprocess.run(["sha256sum", "-c", str(root / "checksums" / f"{name}.sha256")], cwd=opts.dist, check=True,
                   capture_output=True)
    meta = json.loads((root / "metadata" / f"{Path(name).stem}.json").read_text())
    assert meta["live_packages"] == 2 and meta["sha256"] == sha[0]
