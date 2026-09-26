"""Lookups in the PCI and USB ID databases shipped by hwdata."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .sysroot import SysRoot

PCI_IDS_CANDIDATES = ("/usr/share/hwdata/pci.ids", "/usr/share/misc/pci.ids", "/usr/share/pci.ids")
USB_IDS_CANDIDATES = ("/usr/share/hwdata/usb.ids", "/usr/share/misc/usb.ids", "/usr/share/usb.ids")


@dataclass
class IdDatabase:
    vendors: dict[int, str] = field(default_factory=dict)
    devices: dict[tuple[int, int], str] = field(default_factory=dict)
    subsystems: dict[tuple[int, int, int, int], str] = field(default_factory=dict)

    def vendor(self, vid: int) -> str:
        return self.vendors.get(vid, f"{vid:04x}")

    def device(self, vid: int, did: int) -> str:
        return self.devices.get((vid, did), "")

    def subsystem(self, vid: int, did: int, svid: int, sdid: int) -> str:
        return self.subsystems.get((vid, did, svid, sdid), "")


def parse_ids(text: str) -> IdDatabase:
    """Parse pci.ids / usb.ids. Only vendor/device/subsystem entries are kept;
    the class tables at the end of the file (lines starting with ``C``) stop parsing."""
    db = IdDatabase()
    vendor: int | None = None
    device: int | None = None
    for raw in text.splitlines():
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith("C ") or raw.startswith("AT ") or raw.startswith("HID "):
            break
        if raw.startswith("\t\t"):
            if vendor is None or device is None:
                continue
            parts = raw.strip().split(None, 2)
            if len(parts) == 3:
                try:
                    svid, sdid = int(parts[0], 16), int(parts[1], 16)
                except ValueError:
                    continue
                db.subsystems[(vendor, device, svid, sdid)] = parts[2]
        elif raw.startswith("\t"):
            if vendor is None:
                continue
            parts = raw.strip().split(None, 1)
            if len(parts) == 2:
                try:
                    device = int(parts[0], 16)
                except ValueError:
                    continue
                db.devices[(vendor, device)] = parts[1]
        else:
            parts = raw.split(None, 1)
            if len(parts) == 2:
                try:
                    vendor = int(parts[0], 16)
                except ValueError:
                    vendor = None
                    continue
                device = None
                db.vendors[vendor] = parts[1]
    return db


_CACHE: dict[str, IdDatabase] = {}


def _load(sysroot: SysRoot, candidates: tuple[str, ...]) -> IdDatabase:
    for candidate in candidates:
        path = sysroot.path(candidate)
        key = str(path)
        if key in _CACHE:
            return _CACHE[key]
        if path.is_file():
            db = parse_ids(Path(path).read_text(encoding="utf-8", errors="replace"))
            _CACHE[key] = db
            return db
    return IdDatabase()


def pci_ids(sysroot: SysRoot) -> IdDatabase:
    return _load(sysroot, PCI_IDS_CANDIDATES)


def usb_ids(sysroot: SysRoot) -> IdDatabase:
    return _load(sysroot, USB_IDS_CANDIDATES)


# Short vendor names for display. pci.ids uses long legal names
# ("Advanced Micro Devices, Inc. [AMD/ATI]").
SHORT_VENDOR = {
    0x10DE: "NVIDIA",
    0x1002: "AMD",
    0x1022: "AMD",
    0x8086: "Intel",
    0x14E4: "Broadcom",
    0x10EC: "Realtek",
    0x168C: "Qualcomm Atheros",
    0x17CB: "Qualcomm",
    0x14C3: "MediaTek",
    0x0E8D: "MediaTek",
    0x11AB: "Marvell",
    0x1B4B: "Marvell",
    0x144D: "Samsung",
    0x15B7: "Western Digital",
    0x1987: "Phison",
    0x1C5C: "SK hynix",
    0x1E0F: "Kioxia",
    0x2646: "Kingston",
    0x1AF4: "Red Hat (virtio)",
    0x1B36: "Red Hat (QXL)",
    0x1234: "QEMU",
    0x15AD: "VMware",
    0x80EE: "VirtualBox",
    0x1414: "Microsoft",
    0x045E: "Microsoft",
    0x0BDA: "Realtek",
    0x8087: "Intel",
    0x0A5C: "Broadcom",
    0x0CF3: "Qualcomm Atheros",
    0x13D3: "IMC Networks",
    0x0489: "Foxconn",
}


def short_vendor(vid: int, db: IdDatabase | None = None) -> str:
    if vid in SHORT_VENDOR:
        return SHORT_VENDOR[vid]
    if db:
        name = db.vendor(vid)
        for suffix in (", Inc.", " Inc.", " Corporation", " Corp.", " Co., Ltd.", " Ltd.", " GmbH"):
            name = name.replace(suffix, "")
        return name
    return f"{vid:04x}"


def marketing_name(device_name: str) -> str:
    """'AD103 [GeForce RTX 4080 SUPER]' -> 'GeForce RTX 4080 SUPER'."""
    if "[" in device_name and device_name.rstrip().endswith("]"):
        return device_name[device_name.index("[") + 1 : device_name.rindex("]")].strip()
    return device_name.strip()


def codename(device_name: str) -> str:
    """'AD103 [GeForce RTX 4080 SUPER]' -> 'AD103'."""
    if "[" in device_name:
        return device_name[: device_name.index("[")].strip()
    return ""
