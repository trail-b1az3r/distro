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
    "noto-fonts", "noto-fonts-cjk", "openssh",
    "open-vm-tools", "qemu-guest-agent", "rsync", "spice-vdagent",
    # Not needed in the live session; keep the standard Python runtime for the installer.
    "python-pip", "python315", "python315-pip",
    # Keep Nano within its strict size budget. The default firmware set covers
    # common consumer hardware; optional server, switch, and SoC firmware stays
    # available on the standard ISO.
    "linux-firmware-liquidio", "linux-firmware-marvell", "linux-firmware-mellanox",
    "linux-firmware-nfp", "linux-firmware-qcom", "linux-firmware-qlogic",
    # Optional SMB file sharing pulls in Samba and its large dependency set.
    "gvfs-smb",
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
