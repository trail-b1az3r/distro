"""Block devices: disks, partitions, free space and existing systems.

Sizes, partition geometry, transport and rotation come from sysfs. Filesystem
types, labels and mount points need ``lsblk`` (libblkid); on a live machine it
is run automatically, and tests pass its JSON output in directly.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .. import util
from .sysroot import SysRoot

SECTOR = 512
MiB = 1024 * 1024
GiB = 1024 * MiB

ESP_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
MSFT_RESERVED_GUID = "e3c9e316-0b5c-4db8-817d-f92df00215ae"
MSFT_BASIC_DATA_GUID = "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"
LINUX_SWAP_GUID = "0657fd6d-a4ab-43c4-84e5-0933c84b4f4f"

_SKIP = re.compile(r"^(loop|ram|zram|sr|fd|nbd|dm-|md|mtdblock)")

LSBLK_COLUMNS = "NAME,PATH,SIZE,TYPE,FSTYPE,FSVER,LABEL,PARTLABEL,UUID,PARTUUID,PARTTYPE,MOUNTPOINTS,PKNAME,RM,RO,TRAN,MODEL,PTTYPE"


@dataclass
class Partition:
    name: str
    path: str
    number: int
    start_bytes: int
    size_bytes: int
    fstype: str = ""
    label: str = ""
    partlabel: str = ""
    uuid: str = ""
    parttype: str = ""
    mountpoints: list[str] = field(default_factory=list)

    @property
    def end_bytes(self) -> int:
        return self.start_bytes + self.size_bytes

    @property
    def is_esp(self) -> bool:
        return self.parttype.lower() == ESP_GUID or self.parttype.lower() == "0xef"

    @property
    def role_hint(self) -> str:
        pt = self.parttype.lower()
        if self.is_esp:
            return "EFI system partition"
        if pt == MSFT_RESERVED_GUID:
            return "Microsoft reserved"
        if self.fstype == "ntfs" or pt == MSFT_BASIC_DATA_GUID and self.fstype in ("ntfs", ""):
            return "Windows data"
        if self.fstype == "swap" or pt == LINUX_SWAP_GUID:
            return "Linux swap"
        if self.fstype == "crypto_LUKS":
            return "Encrypted (LUKS)"
        if self.fstype in ("ext4", "btrfs", "xfs", "f2fs"):
            return "Linux filesystem"
        return self.fstype or "Unknown"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["size"] = util.human_bytes(self.size_bytes)
        d["role"] = self.role_hint
        d["is_esp"] = self.is_esp
        return d


@dataclass
class FreeRegion:
    start_bytes: int
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {"start_bytes": self.start_bytes, "size_bytes": self.size_bytes, "size": util.human_bytes(self.size_bytes)}


@dataclass
class Disk:
    name: str
    path: str
    size_bytes: int
    model: str
    vendor: str
    transport: str  # nvme | sata | usb | mmc | virtio | scsi | other
    rotational: bool
    removable: bool
    read_only: bool
    logical_sector: int
    partition_table: str = ""
    partitions: list[Partition] = field(default_factory=list)
    live_medium: bool = False
    mounted: bool = False

    @property
    def kind(self) -> str:
        if self.transport == "nvme":
            return "NVMe SSD"
        if self.transport == "usb":
            return "USB drive"
        if self.transport == "mmc":
            return "eMMC/SD"
        if self.transport == "virtio":
            return "Virtual disk"
        return "HDD" if self.rotational else "SSD"

    @property
    def installable(self) -> bool:
        return not (self.live_medium or self.read_only) and self.size_bytes >= 16 * GiB

    @property
    def description(self) -> str:
        return f"{util.human_size_marketing(self.size_bytes)} {self.kind}"

    def free_regions(self, minimum: int = 1 * GiB) -> list[FreeRegion]:
        """Unpartitioned gaps large enough to install into (GPT geometry)."""
        first = 1 * MiB
        last = self.size_bytes - 1 * MiB  # backup GPT header and alignment slack
        regions = []
        cursor = first
        for part in sorted(self.partitions, key=lambda p: p.start_bytes):
            if part.start_bytes - cursor >= minimum:
                regions.append(FreeRegion(_align_up(cursor), part.start_bytes - _align_up(cursor)))
            cursor = max(cursor, part.end_bytes)
        if last - cursor >= minimum:
            regions.append(FreeRegion(_align_up(cursor), last - _align_up(cursor)))
        return [r for r in regions if r.size_bytes >= minimum]

    @property
    def existing_systems(self) -> list[str]:
        found = []
        roles = {p.role_hint for p in self.partitions}
        if "Windows data" in roles or "Microsoft reserved" in roles:
            found.append("Windows")
        if "Linux filesystem" in roles or "Encrypted (LUKS)" in roles:
            found.append("Linux")
        return found

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["partitions"] = [p.to_dict() for p in self.partitions]
        d["kind"] = self.kind
        d["size"] = util.human_bytes(self.size_bytes)
        d["description"] = self.description
        d["installable"] = self.installable
        d["free_regions"] = [r.to_dict() for r in self.free_regions()]
        d["largest_free_bytes"] = max((r.size_bytes for r in self.free_regions()), default=0)
        d["existing_systems"] = self.existing_systems
        d["has_esp"] = any(p.is_esp for p in self.partitions)
        return d


def _align_up(value: int, align: int = MiB) -> int:
    return (value + align - 1) // align * align


def _transport(sysroot: SysRoot, name: str) -> str:
    real = sysroot.realpath(f"/sys/block/{name}")
    if name.startswith("nvme") or "/nvme" in real:
        return "nvme"
    if "/usb" in real:
        return "usb"
    if name.startswith("mmcblk") or "/mmc" in real:
        return "mmc"
    if name.startswith("vd") or "/virtio" in real:
        return "virtio"
    if "/ata" in real:
        return "sata"
    if name.startswith("sd"):
        return "scsi"
    return "other"


def run_lsblk() -> dict[str, Any] | None:
    rc, out = util.run_quiet(["lsblk", "-J", "-b", "-o", LSBLK_COLUMNS], timeout=15)
    if rc != 0 or not out.strip():
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def _flatten_lsblk(data: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    def walk(nodes: list[dict[str, Any]]) -> None:
        for node in nodes:
            out[node.get("name", "")] = node
            walk(node.get("children", []) or [])

    if data:
        walk(data.get("blockdevices", []))
    return out


def _mountpoints(node: dict[str, Any]) -> list[str]:
    mps = node.get("mountpoints")
    if mps is None:
        mp = node.get("mountpoint")
        mps = [mp] if mp else []
    return [m for m in mps if m]


def detect_storage(sysroot: SysRoot, lsblk: dict[str, Any] | None = None, live_label_prefix: str = "") -> list[Disk]:
    info = _flatten_lsblk(lsblk)
    disks = []
    for name in sysroot.listdir("/sys/block"):
        if _SKIP.match(name):
            continue
        base = f"/sys/block/{name}"
        sectors = sysroot.read_int(f"{base}/size", 0) or 0
        if sectors == 0:
            continue
        model = sysroot.read(f"{base}/device/model") or info.get(name, {}).get("model") or ""
        vendor = sysroot.read(f"{base}/device/vendor")
        if vendor.upper() == "ATA" or vendor.lower().startswith("0x"):
            vendor = ""
        disk = Disk(
            name=name,
            path=f"/dev/{name}",
            size_bytes=sectors * SECTOR,
            model=" ".join(f"{vendor} {model}".split()),
            vendor=vendor,
            transport=_transport(sysroot, name),
            rotational=sysroot.read(f"{base}/queue/rotational") == "1",
            removable=sysroot.read(f"{base}/removable") == "1",
            read_only=sysroot.read(f"{base}/ro") == "1",
            logical_sector=sysroot.read_int(f"{base}/queue/logical_block_size", 512) or 512,
            partition_table=(info.get(name, {}).get("pttype") or ""),
        )
        for child in sysroot.listdir(base):
            if not sysroot.exists(f"{base}/{child}/partition"):
                continue
            node = info.get(child, {})
            part = Partition(
                name=child,
                path=f"/dev/{child}",
                number=sysroot.read_int(f"{base}/{child}/partition", 0) or 0,
                start_bytes=(sysroot.read_int(f"{base}/{child}/start", 0) or 0) * SECTOR,
                size_bytes=(sysroot.read_int(f"{base}/{child}/size", 0) or 0) * SECTOR,
                fstype=node.get("fstype") or "",
                label=node.get("label") or "",
                partlabel=node.get("partlabel") or "",
                uuid=node.get("uuid") or "",
                parttype=(node.get("parttype") or "").lower(),
                mountpoints=_mountpoints(node),
            )
            disk.partitions.append(part)
        disk.partitions.sort(key=lambda p: p.number)
        all_mounts = _mountpoints(info.get(name, {})) + [m for p in disk.partitions for m in p.mountpoints]
        disk.mounted = bool(all_mounts)
        labels = [info.get(name, {}).get("label") or ""] + [p.label for p in disk.partitions]
        if any(m.startswith("/run/archiso") for m in all_mounts) or (
            live_label_prefix and any(lbl.startswith(live_label_prefix) for lbl in labels if lbl)
        ):
            disk.live_medium = True
        disks.append(disk)
    return disks
