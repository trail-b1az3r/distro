from pathlib import Path

from distrokit import boot, util
from distrokit.branding import load as load_branding


def make_kernel(root: Path, pkgbase: str, version: str, fallback: bool = True) -> None:
    mod = root / "usr/lib/modules" / version
    mod.mkdir(parents=True)
    (mod / "pkgbase").write_text(pkgbase + "\n")
    (mod / "vmlinuz").write_bytes(b"k")
    (root / "boot").mkdir(exist_ok=True)
    (root / "boot" / f"vmlinuz-{pkgbase}").write_bytes(b"k")
    (root / "boot" / f"initramfs-{pkgbase}.img").write_bytes(b"i")
    if fallback:
        (root / "boot" / f"initramfs-{pkgbase}-fallback.img").write_bytes(b"i")


def test_cmdline_fragments_merge(tmp_path):
    b = load_branding()
    boot.set_fragment("00-root", ["root=UUID=abc", "rw", "rootflags=subvol=@"], tmp_path, b)
    boot.set_fragment("10-quiet", boot.QUIET_PARAMS, tmp_path, b)
    boot.set_fragment("20-gpu", ["nvidia_drm.modeset=1"], tmp_path, b)
    boot.set_fragment("90-local", ["loglevel=4"], tmp_path, b)  # user override wins
    params = boot.read_cmdline(tmp_path, b)
    assert params[0] == "root=UUID=abc"
    assert "loglevel=4" in params and "loglevel=3" not in params
    assert params.count("rw") == 1
    boot.set_fragment("20-gpu", [], tmp_path, b)
    assert "nvidia_drm.modeset=1" not in boot.read_cmdline(tmp_path, b)


def test_systemd_boot_entries_per_kernel(tmp_path):
    b = load_branding()
    make_kernel(tmp_path, "linux", "6.16.8-arch1-1")
    make_kernel(tmp_path, "linux-surface", "6.16.3-surface-1", fallback=False)
    boot.set_fragment("00-root", ["root=UUID=abc", "rw"], tmp_path, b)
    boot.set_fragment("10-quiet", boot.QUIET_PARAMS, tmp_path, b)
    boot.save_config(boot.BootConfig("systemd-boot", "uefi", "/boot", "ESPUUID", default_kernel="linux-surface"), tmp_path, b)
    # A stale entry for a removed kernel is cleaned up.
    entries = tmp_path / "boot/loader/entries"
    entries.mkdir(parents=True)
    (entries / "nexora-linux-zen.conf").write_text("stale")
    (entries / "windows.conf").write_text("keep")
    msg = boot.update(tmp_path, util.Runner(), b)
    assert "entries written" in msg
    names = sorted(p.name for p in entries.iterdir())
    assert "nexora-linux.conf" in names and "nexora-linux-fallback.conf" in names
    assert "nexora-linux-surface.conf" in names and "nexora-linux-surface-fallback.conf" not in names
    assert "nexora-linux-surface-diagnostic.conf" in names
    assert "nexora-linux-zen.conf" not in names and "windows.conf" in names
    main = (entries / "nexora-linux.conf").read_text()
    assert "options root=UUID=abc rw quiet splash" in main
    diag = (entries / "nexora-linux-diagnostic.conf").read_text()
    assert "systemd.unit=multi-user.target" in diag and " quiet" not in diag and "splash" not in diag
    loader = (tmp_path / "boot/loader/loader.conf").read_text()
    assert "default nexora-linux-surface.conf" in loader and "editor no" in loader


def test_grub_defaults_edit():
    b = load_branding()
    text = 'GRUB_DEFAULT=0\nGRUB_TIMEOUT=5\nGRUB_DISTRIBUTOR="Arch"\nGRUB_CMDLINE_LINUX_DEFAULT="loglevel=3 quiet"\n#GRUB_DISABLE_OS_PROBER=false\n'
    out = boot.grub_defaults(text, b, ["root=UUID=x", "rw", "rootflags=subvol=@", "rd.luks.name=u=cryptroot", "quiet", "splash"])
    assert 'GRUB_DISTRIBUTOR="Nexora"' in out
    # grub-mkconfig adds root= and rootflags= itself.
    assert 'GRUB_CMDLINE_LINUX_DEFAULT="rd.luks.name=u=cryptroot quiet splash"' in out
    assert 'GRUB_DISABLE_OS_PROBER="false"' in out and "#GRUB_DISABLE_OS_PROBER" not in out
    assert out.count("GRUB_TIMEOUT=") == 1


def test_grub_custom_cfg(tmp_path):
    b = load_branding()
    make_kernel(tmp_path, "linux", "6.16.8-arch1-1")
    cfg = boot.grub_custom_cfg(b, boot.installed_kernels(tmp_path), ["root=UUID=x", "rw", "quiet"], "AAAA-BBBB")
    assert "search --no-floppy --fs-uuid --set=root AAAA-BBBB" in cfg
    assert "linux /vmlinuz-linux root=UUID=x rw systemd.unit=multi-user.target" in cfg
