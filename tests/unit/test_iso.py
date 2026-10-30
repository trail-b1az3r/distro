"""ISO assembly: the archiso profile generated from releng and iso/."""

import json
import os
import shutil
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
    "grub/grub.cfg": "menuentry 'Arch Linux install medium' {}\n",
    "grub/loopback.cfg": "menuentry 'Arch Linux install medium' {}\n",
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
    assert iso.iso_version(b, epoch) == f"26.09.{b['ISO_RELEASE']}"
    assert iso.iso_filename(b, iso.iso_version(b, epoch)) == f"{b.name}-26.09.{b['ISO_RELEASE']}-x86_64.iso"
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
    assert not (prof / "efiboot").exists()  # systemd-boot: UEFI boots with GRUB
    assert "Arch Linux" not in (prof / "grub/grub.cfg").read_text()
    assert not (air / "root/.automated_script.sh").exists()
    assert not (air / "etc/systemd/system/multi-user.target.wants/sshd.service").is_symlink()
    assert not (air / "etc/systemd/system/multi-user.target.wants/iwd.service").is_symlink()
    assert not (air / "etc/systemd/network").exists()
    assert not (air / "etc/resolv.conf").is_symlink()
    # Build-only hooks carry archiso's marker, so its zzzz99 hook deletes them
    # before the ISO is sealed (they would otherwise act on installs too).
    rank = air / "etc/pacman.d/hooks/eos-rankmirrors.hook"
    assert "Target = endeavouros-mirrorlist" in rank.read_text()
    assert rank.read_text().startswith("# remove from airootfs!")
    # Kept: keyring initialisation and the archiso initramfs.
    assert (air / "etc/systemd/system/multi-user.target.wants/pacman-init.service").is_symlink()
    assert (air / "etc/mkinitcpio.conf.d/archiso.conf").is_file()

    # profiledef.sh parses and names the ISO after distro.conf.
    out = subprocess.run(["bash", "-c", 'declare -A file_permissions; source profiledef.sh; '
                          'echo "$iso_name|$iso_label|$iso_version|${bootmodes[*]}|${file_permissions[/etc/shadow]}"'],
                         cwd=prof, capture_output=True, text=True, check=True).stdout.strip()
    assert out == f"{b.name}|{b['ISO_LABEL_PREFIX']}_202609|26.09.{b['ISO_RELEASE']}|bios.syslinux uefi.grub|0:0:400"

    # Boot menus are branded and keep archiso's placeholders.
    grub = (prof / "grub/grub.cfg").read_text()
    assert "archisosearchuuid=%ARCHISO_UUID%" in grub and "source /boot/grub/menu.cfg" in grub
    assert "img_loop=${iso_path}" in (prof / "grub/loopback.cfg").read_text()
    menu = (prof / "grub/menu.cfg").read_text()
    assert f'menuentry "{b.pretty_name} live" --class {b.id}' in menu and "@" not in menu
    assert "/%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux ${archiso_params}" in menu
    assert f"themes/{b.id}" in menu and "io\\.systemd\\.boot\\.kernel-cmdline-extra" in menu
    safe = (prof / "syslinux/archiso_sys-linux.cfg").read_text()
    assert f"{b.id}.safe_graphics=1" in safe and "nomodeset" in safe and "Arch Linux" not in safe
    # archiso copies the live system into RAM by itself unless told not to.
    for text in (menu, safe):
        entries = [ln for ln in text.splitlines() if ln.lstrip().startswith(("APPEND", "linux /%INSTALL_DIR%"))]
        assert entries and all("copytoram=" in ln for ln in entries)
        assert sum("copytoram=y" in ln for ln in entries) == 1
    assert "@" not in (prof / "syslinux/archiso_head.cfg").read_text()

    packages = (prof / "packages.x86_64").read_text().split()
    for name in (f"{b.id}-installer", f"{b.id}-desktop", "linux", "greetd", "cage", "mkinitcpio-archiso",
                 "illogical-impulse-hyprland", "memtest86+-efi", "edk2-shell", "modemmanager",
                 "linux-firmware-liquidio", "linux-firmware-marvell", "linux-firmware-mellanox",
                 "linux-firmware-nfp", "linux-firmware-qcom", "linux-firmware-qlogic"):
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
    assert info["profile"] == "ai" and info["offline"] == "full" and info["version"] == f"26.09.{b['ISO_RELEASE']}" and info["codename"] == b["ISO_CODENAME"]
    assert (air / f"etc/{b.id}/live").is_file()

    # Live session: greetd autologin, NetworkManager, the live user service.
    live_setup_unit = air / f"etc/systemd/system/{b.id}-live-setup.service"
    assert "Wants=NetworkManager.service" in live_setup_unit.read_text()
    assert "After=systemd-sysusers.service systemd-tmpfiles-setup.service NetworkManager.service" in live_setup_unit.read_text()
    systemd = air / "etc/systemd/system"
    assert os.readlink(systemd / "display-manager.service").endswith("/greetd.service")
    for unit in ("NetworkManager.service", "ModemManager.service", "bluetooth.service", f"{b.id}-live-setup.service"):
        assert (systemd / "multi-user.target.wants" / unit).is_symlink()
    greetd = (air / "etc/greetd/config.toml").read_text()
    assert f'user = "{b["LIVE_USER"]}"' in greetd and f"{b.id}-live-session" in greetd
    sudoers = (air / f"etc/sudoers.d/10-{b.id}-live").read_text()
    assert sudoers.strip().endswith(f"{b['LIVE_USER']} ALL=(ALL:ALL) NOPASSWD: ALL")
    assert (air / "etc/shadow").read_text().startswith("root:!*:")  # no empty root password
    for script in (f"{b.id}-live-session", f"{b.id}-live-setup"):
        subprocess.run(["bash", "-n", str(air / f"usr/lib/{b.id}/bin/{script}")], check=True)


def test_nano_uses_only_lxqt_and_mate_live_desktops(tmp_path, releng):
    b = load_branding()
    opts = iso.Options(edition="nano", profile="standard", offline="minimal",
                       build=tmp_path / "build", releng=releng)
    prof = iso.assemble(opts, b, epoch=1790393700)
    packages = set((prof / "packages.x86_64").read_text().split())

    assert {"lxqt-session", "lxqt-panel", "pcmanfm-qt", "qterminal", "openbox",
            "mate-session-manager", "mate-panel", "marco", "caja",
            "mate-terminal", "sddm", "network-manager-applet",
            "nm-connection-editor", "udisks2", "gvfs", "modemmanager",
            "networkmanager", "wpa_supplicant",
            "linux-firmware-liquidio", "linux-firmware-marvell", "linux-firmware-mellanox",
            "linux-firmware-nfp", "linux-firmware-qcom", "linux-firmware-qlogic",
            "mkinitcpio-nfs-utils", "nbd"} <= packages
    assert {f"{b.id}-installer", f"{b.id}-branding", f"{b.id}-core",
            f"{b.id}-welcome"} <= packages
    assert "hyprland-plus" not in packages
    assert not any(name.startswith("illogical-impulse-") for name in packages)
    assert "plasma-desktop" not in packages and "greetd" not in packages
    assert not {"noto-fonts", "python-pip", "python315", "python315-pip", "gvfs-smb"} & packages

    air = prof / "airootfs"
    systemd = air / "etc/systemd/system"
    assert os.readlink(systemd / "display-manager.service") == "/usr/lib/systemd/system/sddm.service"
    for unit in ("NetworkManager.service", "ModemManager.service", "NetworkManager-wait-online.service"):
        assert (systemd / "multi-user.target.wants" / unit).is_symlink()
    assert (systemd / "dbus-org.freedesktop.NetworkManager.service").is_symlink()
    assert (air / f"etc/{b.id}/nano").is_file()
    sddm = (air / "etc/sddm.conf.d/10-nexora-nano.conf").read_text()
    assert f"User={b['LIVE_USER']}" in sddm
    assert "Session=lxqt.desktop" in sddm
    assert "SessionDir=/etc/nexora/xsessions" in sddm
    assert "WaylandSessionDir=/etc/nexora/wayland-sessions" in sddm
    live_setup = (air / f"usr/lib/{b.id}/bin/{b.id}-live-setup").read_text()
    assert f"/etc/{b.id}/nano" in live_setup
    assert 'for session in lxqt mate' in live_setup
    assert 'source="/usr/share/xsessions/$session.desktop"' in live_setup
    assert "reset-desktop --yes" in live_setup


def test_standard_edition_keeps_greetd_and_halcyon(tmp_path, releng):
    b = load_branding()
    opts = iso.Options(edition="standard", build=tmp_path / "build", releng=releng)
    prof = iso.assemble(opts, b, epoch=1790393700)
    packages = set((prof / "packages.x86_64").read_text().split())
    assert "hyprland-plus" in packages and "illogical-impulse-hyprland" in packages
    assert "lxqt-session" not in packages and "mate-session-manager" not in packages
    systemd = prof / "airootfs/etc/systemd/system"
    assert os.readlink(systemd / "display-manager.service") == "/usr/lib/systemd/system/greetd.service"


def test_boot_menu_theme_goes_onto_the_iso(tmp_path, releng, monkeypatch):
    b = load_branding()
    src = tmp_path / "src"
    shutil.copytree(iso.paths.DATA_ROOT / "iso", src / "iso")
    (src / "packages").symlink_to(iso.paths.DATA_ROOT / "packages")
    theme = src / "branding/generated/grub"
    (theme / "icons").mkdir(parents=True)
    (theme / "theme.txt").write_text("title-text: \"\"\n")
    (theme / "icons" / f"{b.id}.png").write_bytes(b"png")
    monkeypatch.setattr(iso.paths, "DATA_ROOT", src)
    prof = iso.assemble(iso.Options(build=tmp_path / "build", releng=releng), b, epoch=1790393700)
    assert (prof / f"grub/themes/{b.id}/theme.txt").is_file()
    assert (prof / f"grub/themes/{b.id}/icons/{b.id}.png").is_file()


def test_offline_repository_leaves_out_debug_packages(tmp_path):
    b = load_branding()
    opts = iso.Options(build=tmp_path / "build")
    opts.repo.mkdir(parents=True)
    names = ["llama.cpp-git-b1.r0.abc-1-x86_64.pkg.tar.zst", "llama.cpp-git-debug-b1.r0.abc-1-x86_64.pkg.tar.zst",
             "llama.cpp-git-debug-b1.r0.abc-1-x86_64.pkg.tar.zst.sig", f"{b.id}-core-1.0-1-any.pkg.tar.zst"]
    for name in names:
        (opts.repo / name).write_bytes(b"pkg")
    runner = iso.util.Runner(dry_run=True)
    out = iso.offline_repository(opts, b, runner, tmp_path / "pacman.conf")
    assert sorted(f.name for f in out.iterdir()) == sorted([names[0], names[3]])


def test_iso_files_and_the_fat32_limit(tmp_path, monkeypatch):
    listing = ("-rw-r--r--    1 0        0        4294967296 Oct 28 22:16 '/arch/x86_64/airootfs.sfs'\n"
               "-rw-r--r--    1 0        0              37 Oct 28 22:16 '/boot/1234.uuid'\n")
    monkeypatch.setattr(iso.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, listing, ""))
    files = iso.iso_files(tmp_path / "x.iso")
    assert files == {"/arch/x86_64/airootfs.sfs": 2**32, "/boot/1234.uuid": 37}
    assert [f.split()[0] for f in iso.too_big_for_fat32(files)] == ["/arch/x86_64/airootfs.sfs"]
    assert iso.too_big_for_fat32({"/arch/x86_64/airootfs.sfs": 2**32 - 1}) == []


def test_nano_offline_repository_keeps_only_live_and_profile_dependencies(tmp_path, monkeypatch):
    from types import SimpleNamespace

    b = load_branding()
    opts = iso.Options(edition="nano", profile="minimal", offline="minimal",
                       build=tmp_path / "build")
    opts.repo.mkdir(parents=True)
    names = [
        "nexora-installer-1-1-any.pkg.tar.zst",
        "nexora-core-1-1-any.pkg.tar.zst",
        "nexora-desktop-1-1-any.pkg.tar.zst",
        "illogical-shell-1-1-any.pkg.tar.zst",
        "required-dep-1-1-any.pkg.tar.zst",
        "nexora-ai-1-1-any.pkg.tar.zst",
        "llama.cpp-vulkan-1-1-x86_64.pkg.tar.zst",
    ]
    for name in names:
        (opts.repo / name).write_bytes(b"pkg")

    metadata = {
        names[0]: ("nexora-installer", ["nexora-core"]),
        names[1]: ("nexora-core", []),
        names[2]: ("nexora-desktop", ["illogical-shell"]),
        names[3]: ("illogical-shell", ["required-dep"]),
        names[4]: ("required-dep", []),
        names[5]: ("nexora-ai", []),
        names[6]: ("llama.cpp-vulkan", []),
    }
    monkeypatch.setattr(iso, "package_metadata", lambda path: metadata[path.name])
    monkeypatch.setattr(iso, "live_packages", lambda _b, _edition: ["nexora-installer"])
    monkeypatch.setattr(iso, "select_packages",
                        lambda _profile, branding=None: SimpleNamespace(packages=["nexora-desktop"]))

    out = iso.offline_repository(opts, b, iso.util.Runner(dry_run=True), tmp_path / "pacman.conf")
    included = {p.name for p in out.glob("*.pkg.tar.*")}
    assert included == set(names[:5])
    assert "nexora-ai-1-1-any.pkg.tar.zst" not in included
    assert "llama.cpp-vulkan-1-1-x86_64.pkg.tar.zst" not in included


def test_offline_sets_keep_conflicting_stacks_apart():
    b = load_branding()
    for profile in ("minimal", "standard", "developer", "ai"):
        base = set(iso.offline_sets(b, profile)[0])
        assert {"archlinux-keyring", "endeavouros-keyring"} <= base
    sets = iso.offline_sets(b, "standard")
    base = set(sets[0])
    assert {"linux", "linux-headers", "grub", "sbctl", "llama.cpp-vulkan",
            "archlinux-keyring", "endeavouros-keyring"} <= base
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
    mk = next(c for c in cmds if "mkarchiso" in c)
    assert mk.startswith("unshare --mount --propagation private -- mkarchiso ")  # its mounts stay private
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

    # Not a real ISO 9660 image: its file listing (xorriso) is stood in for.
    monkeypatch.setattr(iso, "iso_files", lambda path: {"/arch/x86_64/airootfs.sfs": 3 * 2**30})
    info = iso.finish(opts, b, 1790393700, util.Runner(dry_run=True))
    assert info["largest_file"] == 3 * 2**30
    name = f"{b.name}-26.09.{b['ISO_RELEASE']}-x86_64.iso"
    assert info["iso"] == name and (opts.dist / name).is_file()
    root = opts.dist.parent
    sha = (root / "checksums" / f"{name}.sha256").read_text().split()
    assert sha[1] == name and len(sha[0]) == 64
    subprocess.run(["sha256sum", "-c", str(root / "checksums" / f"{name}.sha256")], cwd=opts.dist, check=True,
                   capture_output=True)
    meta = json.loads((root / "metadata" / f"{Path(name).stem}.json").read_text())
    assert meta["live_packages"] == 2 and meta["sha256"] == sha[0]


def test_nano_size_limit_fails_at_the_exact_boundary(tmp_path, releng, monkeypatch):
    b = load_branding()
    opts = iso.Options(edition="nano", build=tmp_path / "build",
                       dist=tmp_path / "out" / "dist", releng=releng)
    opts.out.mkdir(parents=True)
    (opts.out / "nano.iso").write_bytes(b"12345678")
    monkeypatch.setattr(iso, "NANO_SIZE_LIMIT", 8)
    monkeypatch.setattr(iso, "iso_files", lambda _path: {"/arch/x86_64/airootfs.sfs": 7})
    from distrokit import util

    with pytest.raises(SystemExit, match="exceeds the strict 8-byte limit by 0 bytes"):
        iso.finish(opts, b, 1790393700, util.Runner(dry_run=True))


def test_finish_reads_the_package_list_from_the_iso(tmp_path, releng, monkeypatch):
    # mkarchiso -r removes its work directory, list and all: the ISO has a copy.
    b = load_branding()
    opts = iso.Options(build=tmp_path / "build", dist=tmp_path / "out" / "dist", releng=releng)
    opts.out.mkdir(parents=True)
    (opts.out / "whatever.iso").write_bytes(b"iso9660")
    monkeypatch.setattr(iso, "iso_files", lambda path: {})
    asked = []

    def extract(path, inside, dest):
        asked.append(inside)
        dest.write_text("base 3-2\nlinux 6.16-1\nmesa 25.2-1\n")
        return True

    monkeypatch.setattr(iso, "extract_from_iso", extract)
    from distrokit import util

    info = iso.finish(opts, b, 1790393700, util.Runner(dry_run=True))
    assert asked == ["/arch/pkglist.x86_64.txt"] and info["live_packages"] == 3
    assert (opts.dist.parent / "metadata" / f"{b.name}-26.09.{b['ISO_RELEASE']}-x86_64.packages.txt").is_file()


def test_user_packages_join_the_repository(tmp_path):
    b = load_branding()
    mine = tmp_path / "mine"
    mine.mkdir()
    (mine / "mytool-1.0-1-x86_64.pkg.tar.zst").write_bytes(b"pkg")
    (mine / "mytool-1.0-1-x86_64.pkg.tar.zst.sig").write_bytes(b"sig")
    (mine / "notes.txt").write_text("not a package")
    opts = iso.Options(build=tmp_path / "build", user_packages=mine)
    runner = iso.util.Runner(dry_run=True)
    added = iso.add_user_packages(opts, b, runner)
    assert [p.name for p in added] == ["mytool-1.0-1-x86_64.pkg.tar.zst"]
    cmd = runner.recorded[-1]
    assert cmd[:2] == ["repo-add", "--remove"] and cmd[2].endswith(f"{b.repo_name}.db.tar.gz")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert iso.user_package_files(empty) == []


def test_finish_refuses_a_file_too_big_for_fat32(tmp_path, releng, monkeypatch):
    b = load_branding()
    opts = iso.Options(build=tmp_path / "build", dist=tmp_path / "out" / "dist", releng=releng)
    opts.out.mkdir(parents=True)
    (opts.out / "whatever.iso").write_bytes(b"iso9660")
    monkeypatch.setattr(iso, "iso_files", lambda path: {"/arch/x86_64/airootfs.sfs": 2**32})
    from distrokit import util

    with pytest.raises(SystemExit, match="airootfs.sfs .* FAT32"):
        iso.finish(opts, b, 1790393700, util.Runner(dry_run=True))


def test_mounts_left_under_the_build_directory(tmp_path):
    build = tmp_path / "my build"
    mountinfo = "\n".join([
        "22 1 0:21 / / rw,relatime - ext4 /dev/sda1 rw",
        f"90 22 0:5 / {tmp_path}/my\\040build/iso-work/x86_64/airootfs/proc rw - proc proc rw",
        f"91 22 0:6 / {tmp_path}/my\\040build/iso-work/x86_64/airootfs/dev/pts rw - devpts devpts rw",
        f"92 22 0:7 / {tmp_path}/my\\040build/iso-work/x86_64/airootfs/dev rw - devtmpfs dev rw",
        f"93 22 0:8 / {tmp_path}/my\\040buildings rw - tmpfs tmpfs rw",
    ])
    points = iso.mounts_under(build, mountinfo)
    ends = [p.rsplit("airootfs", 1)[1] for p in points]
    assert ends.index("/dev/pts") < ends.index("/dev")  # nested mounts first
    assert len(points) == 3 and all(p.startswith(f"{tmp_path}/my build/") for p in points)
    assert iso.mounts_under(tmp_path / "other", mountinfo) == []
