"""Shared package selection for Nexora ISO editions."""

from __future__ import annotations

from pathlib import Path

from ..branding import Branding
from ..profiles import read_list

NANO_SIZE_LIMIT = 1_990_000_000  # strict: the ISO must be smaller than this
NANO_LIVE_LISTS = ("base", "nano-desktop", "live")
NANO_LIVE_EXTRA = ("linux", "amd-ucode", "intel-ucode")
NANO_EXCLUDE = {
    "7zip", "archinstall", "base-devel", "btop", "cage", "ddrescue",
    "ffmpegthumbs", "gparted", "greetd", "htop", "kdegraphics-thumbnailers",
    "kate", "kio-extras", "lsof", "man-db", "man-pages", "mdxl",
    "noto-fonts-cjk", "openssh",
    "open-vm-tools", "qemu-guest-agent", "rsync", "spice-vdagent",
    "testdisk", "texinfo", "unzip", "vim", "virtualbox-guest-utils",
    "hyperv", "zip",
}


def nano_live_packages(branding: Branding, data_root: Path | None = None) -> list[str]:
    """The compact Nano live package set, without optional/redundant tools."""
    packages: list[str] = []
    for name in NANO_LIVE_LISTS:
        packages += read_list(name, branding, data_root=data_root)
    packages = [name for name in packages if name not in NANO_EXCLUDE]
    return list(dict.fromkeys(packages + list(NANO_LIVE_EXTRA)))
