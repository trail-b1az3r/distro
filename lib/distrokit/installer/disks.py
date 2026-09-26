"""Partition planning.

``plan_disks()`` turns the disk choices into a :class:`DiskPlan`: the partition
table changes (as an sfdisk script), what gets formatted and encrypted, the
mount table, and a plain-language description of every destructive action,
which the installer shows before anything is written.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from .. import util
from ..hardware.storage import Disk, Partition
from .config import InstallConfig, resolve_bootloader

MiB = 2**20
GiB = 2**30

ESP_TYPE = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
XBOOTLDR_TYPE = "BC13C2FF-59E6-4262-A352-B275FD6F7172"
BIOS_BOOT_TYPE = "21686148-6449-6E6F-744E-656564454649"
SWAP_TYPE = "0657FD6D-A4AB-43C4-84E5-0933C84B4F4F"
ROOT_X86_64_TYPE = "4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709"
HOME_TYPE = "933AC7E1-2EB4-4F13-B844-0E14E2AEF915"
LINUX_FS_TYPE = "0FC63DAF-8483-4772-8E79-3D69D8477DE4"

ESP_SIZE = 1 * GiB
MIN_ESP_FOR_BOOT = 900 * MiB  # kernels + initramfs (with GPU modules) for several kernels
MIN_ROOT = 20 * GiB

BTRFS_SUBVOLUMES = (("@", "/"), ("@home", "/home"), ("@log", "/var/log"), ("@pkg", "/var/cache/pacman/pkg"))
BTRFS_OPTIONS = "noatime,compress=zstd:1"


class DiskPlanError(ValueError):
    pass


def partition_path(disk: str, number: int) -> str:
    return f"{disk}p{number}" if disk[-1].isdigit() else f"{disk}{number}"


@dataclass
class Volume:
    role: str  # esp | xbootldr | bios_boot | boot | root | home | swap
    mountpoint: str  # "" for none, "swap" for swap
    fs: str  # vfat | ext4 | btrfs | xfs | swap | none
    size_bytes: int = 0  # 0 = rest of the region
    start_bytes: int = 0  # 0 = let sfdisk place it
    type_guid: str = ""
    label: str = ""
    number: int = 0  # partition number (new partitions)
    device: str = ""  # partition path, known for existing ones and after partitioning
    format: bool = True
    encrypt: bool = False
    mapper: str = ""
    existing: bool = False

    @property
    def fs_device(self) -> str:
        return f"/dev/mapper/{self.mapper}" if self.encrypt else self.device

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["size"] = util.human_bytes(self.size_bytes) if self.size_bytes else "rest"
        return d


@dataclass
class DiskPlan:
    mode: str
    disk: str
    firmware: str
    bootloader: str
    new_table: bool
    volumes: list[Volume] = field(default_factory=list)
    sfdisk_script: str = ""
    esp_mount: str = "/boot"
    boot_dir: str = "/boot"
    swapfile_bytes: int = 0
    summary: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def volume(self, role: str) -> Volume | None:
        return next((v for v in self.volumes if v.role == role), None)

    @property
    def new_volumes(self) -> list[Volume]:
        return [v for v in self.volumes if not v.existing]

    @property
    def destructive(self) -> bool:
        return self.new_table or any(v.format for v in self.volumes)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["volumes"] = [v.to_dict() for v in self.volumes]
        return d


def swap_size(cfg: InstallConfig, ram_bytes: int) -> int:
    if cfg.disk.swap_size_gib:
        return cfg.disk.swap_size_gib * GiB
    ram_gib = math.ceil(ram_bytes / GiB)
    if cfg.disk.hibernation:
        return ram_gib * GiB  # room for a full hibernation image
    return min(max(ram_gib // 2, 2), 8) * GiB


def _describe_partition(p: Partition) -> str:
    bits = [p.path, util.human_bytes(p.size_bytes)]
    if p.label:
        bits.append(f"“{p.label}”")
    bits.append(p.role_hint)
    return ", ".join(bits)


def _script_line(v: Volume) -> str:
    parts = []
    if v.start_bytes:
        parts.append(f"start={v.start_bytes // 512}")
    if v.size_bytes:
        parts.append(f"size={v.size_bytes // 512}")
    parts.append(f"type={v.type_guid}")
    if v.label:
        parts.append(f'name="{v.label}"')
    return ", ".join(parts)


def _data_volumes(cfg: InstallConfig, available: int, swap_bytes: int, start: int = 0) -> list[Volume]:
    """swap, root (and home) laid out in ``available`` bytes starting at ``start``."""
    d = cfg.disk
    vols: list[Volume] = []
    cursor = start
    if d.swap == "partition":
        vols.append(Volume("swap", "swap", "swap", swap_bytes, cursor, SWAP_TYPE, "swap",
                           encrypt=d.encrypt, mapper="cryptswap" if d.encrypt else ""))
        available -= swap_bytes
        cursor = cursor + swap_bytes if cursor else 0
    if available < MIN_ROOT:
        raise DiskPlanError(f"Not enough space: {util.human_bytes(available)} left for the system, at least {util.human_bytes(MIN_ROOT)} needed.")
    if d.separate_home:
        home_bytes = d.home_size_gib * GiB if d.home_size_gib else 0
        if home_bytes:
            root_bytes = available - home_bytes
        else:
            root_bytes = int(min(max(available * 0.35, 30 * GiB), 120 * GiB))
            root_bytes = min(root_bytes, available - 10 * GiB)
        if root_bytes < MIN_ROOT or available - root_bytes < 5 * GiB:
            raise DiskPlanError("Not enough space for separate root and /home partitions.")
        root_bytes = root_bytes // MiB * MiB
        vols.append(Volume("root", "/", d.filesystem, root_bytes, cursor, ROOT_X86_64_TYPE, "root",
                           encrypt=d.encrypt, mapper="cryptroot" if d.encrypt else ""))
        vols.append(Volume("home", "/home", d.filesystem, 0, cursor + root_bytes if cursor else 0, HOME_TYPE, "home",
                           encrypt=d.encrypt, mapper="crypthome" if d.encrypt else ""))
    else:
        vols.append(Volume("root", "/", d.filesystem, 0, cursor, ROOT_X86_64_TYPE, "root",
                           encrypt=d.encrypt, mapper="cryptroot" if d.encrypt else ""))
    return vols


def plan_disks(cfg: InstallConfig, disk: Disk | None, *, uefi: bool, ram_bytes: int,
               all_disks: list[Disk] | None = None, required_bytes: int = 0) -> DiskPlan:
    d = cfg.disk
    bootloader = resolve_bootloader(cfg, uefi)
    firmware = "uefi" if uefi else "bios"
    swap_bytes = swap_size(cfg, ram_bytes)

    if d.mode == "erase":
        if disk is None:
            raise DiskPlanError("No disk selected.")
        if not disk.installable:
            raise DiskPlanError(f"{disk.path} cannot be used (live medium, read-only or too small).")
        if d.disk_size_bytes and d.disk_size_bytes != disk.size_bytes:
            raise DiskPlanError(f"{disk.path} is not the disk that was selected (size changed). Re-scan disks.")
        plan = DiskPlan("erase", disk.path, firmware, bootloader, new_table=True)
        vols: list[Volume] = []
        usable = disk.size_bytes - 2 * MiB - 1 * MiB  # alignment and backup GPT
        if uefi:
            vols.append(Volume("esp", "/boot", "vfat", ESP_SIZE, 0, ESP_TYPE, "EFI"))
            usable -= ESP_SIZE
        else:
            vols.append(Volume("bios_boot", "", "none", 1 * MiB, 0, BIOS_BOOT_TYPE, "BIOS boot", format=False))
            usable -= 1 * MiB
            if d.encrypt:
                vols.append(Volume("boot", "/boot", "ext4", ESP_SIZE, 0, LINUX_FS_TYPE, "boot"))
                usable -= ESP_SIZE
        vols += _data_volumes(cfg, usable, swap_bytes)
        for i, v in enumerate(vols, 1):
            v.number = i
            v.device = partition_path(disk.path, i)
        plan.volumes = vols
        plan.sfdisk_script = "label: gpt\n" + "".join(_script_line(v) + "\n" for v in vols)
        plan.summary.append(f"ERASE the whole disk {disk.model or disk.name} ({disk.path}, {util.human_size_marketing(disk.size_bytes)}).")
        if disk.partitions:
            plan.summary.append("These partitions and everything on them will be permanently deleted:")
            plan.summary += [f"  • {_describe_partition(p)}" for p in disk.partitions]
            if disk.existing_systems:
                plan.summary.append(f"The disk currently contains: {', '.join(disk.existing_systems)}. It will no longer boot.")
        else:
            plan.summary.append("The disk has no partitions; any data on it will be overwritten.")

    elif d.mode == "free-space":
        if disk is None:
            raise DiskPlanError("No disk selected.")
        if disk.partition_table not in ("gpt", ""):
            raise DiskPlanError(f"{disk.path} uses an {disk.partition_table.upper()} partition table; installing into free space needs GPT. Use manual partitioning.")
        regions = disk.free_regions()
        if not regions:
            raise DiskPlanError(f"{disk.path} has no unallocated space.")
        region = next((r for r in regions if r.start_bytes == d.region_start_bytes), None) if d.region_start_bytes else None
        region = region or max(regions, key=lambda r: r.size_bytes)
        plan = DiskPlan("free-space", disk.path, firmware, bootloader, new_table=False)
        vols = []
        cursor = region.start_bytes
        available = region.size_bytes
        if uefi:
            esp = next((p for p in disk.partitions if p.is_esp), None)
            if esp is None:
                # Look on the other disks too (Windows on another drive).
                for other in all_disks or []:
                    esp = next((p for p in other.partitions if p.is_esp), None)
                    if esp:
                        break
            if esp is not None and esp.size_bytes >= MIN_ESP_FOR_BOOT:
                vols.append(Volume("esp", "/boot", "vfat", esp.size_bytes, device=esp.path, format=False, existing=True))
                plan.summary.append(f"Use the existing EFI system partition {esp.path} for boot files (it is not formatted).")
            else:
                if esp is not None:
                    vols.append(Volume("esp", "/efi", "vfat", esp.size_bytes, device=esp.path, format=False, existing=True))
                    plan.esp_mount = "/efi"
                    plan.summary.append(
                        f"The existing EFI system partition {esp.path} ({util.human_bytes(esp.size_bytes)}) is too small for kernels; "
                        "it keeps only the boot loader, and a new 1 GiB boot partition holds the kernels."
                    )
                    vols.append(Volume("xbootldr", "/boot", "vfat", ESP_SIZE, cursor, XBOOTLDR_TYPE, "boot"))
                else:
                    vols.append(Volume("esp", "/boot", "vfat", ESP_SIZE, cursor, ESP_TYPE, "EFI"))
                cursor += ESP_SIZE
                available -= ESP_SIZE
        else:
            if not any(p.parttype.upper() == BIOS_BOOT_TYPE for p in disk.partitions):
                vols.append(Volume("bios_boot", "", "none", 1 * MiB, cursor, BIOS_BOOT_TYPE, "BIOS boot", format=False))
                cursor += 1 * MiB
                available -= 1 * MiB
            if d.encrypt:
                vols.append(Volume("boot", "/boot", "ext4", ESP_SIZE, cursor, LINUX_FS_TYPE, "boot"))
                cursor += ESP_SIZE
                available -= ESP_SIZE
        data = _data_volumes(cfg, available - 1 * MiB, swap_bytes, cursor)
        # The last volume takes the rest of the region, not the rest of the disk.
        used = sum(v.size_bytes for v in data if v.size_bytes)
        data[-1].size_bytes = (available - 1 * MiB - used) // MiB * MiB
        vols += data
        taken = {p.number for p in disk.partitions}
        n = 1
        for v in vols:
            if v.existing:
                continue
            while n in taken:
                n += 1
            v.number = n
            v.device = partition_path(disk.path, n)
            taken.add(n)
        plan.volumes = vols
        plan.sfdisk_script = "".join(_script_line(v) + "\n" for v in vols if not v.existing)
        new = [v for v in vols if not v.existing]
        plan.summary.insert(0, f"Create {len(new)} new partitions in {util.human_bytes(region.size_bytes)} of unallocated space on "
                               f"{disk.model or disk.name} ({disk.path}). Existing partitions are not changed.")

    elif d.mode == "manual":
        plan = DiskPlan("manual", "", firmware, bootloader, new_table=False)
        role_for = {"/": "root", "/home": "home", "/boot": "boot", "/efi": "esp", "swap": "swap"}
        by_path = {p.path: (dk, p) for dk in (all_disks or []) for p in dk.partitions}
        for m in cfg.disk.mounts:
            if m.device not in by_path:
                raise DiskPlanError(f"{m.device} is not a partition on an available disk.")
            dk, part = by_path[m.device]
            if dk.live_medium:
                raise DiskPlanError(f"{m.device} is on the installation medium.")
            role = role_for.get(m.mountpoint, "data")
            if m.mountpoint == "/boot" and part.is_esp:
                role = "esp"
            fs = m.filesystem if m.format else (part.fstype or "")
            v = Volume(role, m.mountpoint, fs, part.size_bytes, device=m.device, format=m.format,
                       encrypt=m.encrypt, mapper={"root": "cryptroot", "home": "crypthome"}.get(role, "") if m.encrypt else "",
                       existing=True)
            plan.volumes.append(v)
            if m.format:
                enc = " with LUKS2 encryption" if m.encrypt else ""
                plan.summary.append(f"FORMAT {m.device} ({_describe_partition(part)}) as {fs}{enc} for {m.mountpoint}. All data on it will be lost.")
            else:
                plan.summary.append(f"Use {m.device} ({part.fstype or 'unknown'}) as {m.mountpoint} without formatting.")
            if not m.format and m.mountpoint == "/":
                plan.warnings.append("Installing onto an unformatted root partition keeps its old files; this can cause conflicts.")
        esp = plan.volume("esp")
        if esp and esp.mountpoint == "/efi":
            plan.esp_mount = "/efi"
        root = plan.volume("root")
        if root is None:
            raise DiskPlanError("Assign a partition to /.")
        if uefi and esp is None:
            raise DiskPlanError("Assign the EFI system partition to /boot or /efi.")
        if esp is not None and esp.mountpoint == "/boot" and esp.size_bytes < 400 * MiB:
            plan.warnings.append(f"The EFI partition {esp.device} is small ({util.human_bytes(esp.size_bytes)}); kernels may not fit.")
        if plan.esp_mount == "/efi" and plan.volume("boot") is None:
            if root.encrypt:
                raise DiskPlanError("With the EFI partition at /efi and an encrypted root, add an unencrypted /boot partition.")
            if bootloader == "systemd-boot":
                raise DiskPlanError("systemd-boot reads kernels from the EFI partition or a /boot partition: mount the EFI partition at /boot, or add a /boot partition.")
        if cfg.disk.swap == "partition" and plan.volume("swap") is None:
            raise DiskPlanError("Swap is set to 'partition' but no partition is assigned to swap.")
    else:
        raise DiskPlanError(f"unknown mode {d.mode}")

    if d.swap == "file":
        plan.swapfile_bytes = swap_bytes
    if d.encrypt or any(v.encrypt for v in plan.volumes):
        enc = [v for v in plan.volumes if v.encrypt]
        plan.summary.append("Encrypt " + ", ".join(f"{v.role} ({v.device})" for v in enc)
                            + " with LUKS2. The passphrase is needed at every boot; if it is lost, the data cannot be recovered.")
    root = plan.volume("root")
    if required_bytes and root and root.size_bytes and root.size_bytes < required_bytes:
        plan.warnings.append(f"The root partition ({util.human_bytes(root.size_bytes)}) is smaller than the "
                             f"{util.human_bytes(required_bytes)} this installation needs.")
    return plan


def format_commands(plan: DiskPlan) -> list[tuple[str, list[str], str | None]]:
    """(description, argv, stdin) for creating filesystems. LUKS commands
    read the passphrase from stdin (``--key-file=-``); it never appears in
    argv or logs."""
    cmds: list[tuple[str, list[str], str | None]] = []
    for v in plan.volumes:
        if not v.format or v.fs == "none":
            continue
        dev = v.device
        if v.encrypt:
            cmds.append((f"Encrypt {dev}", ["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode",
                                             "--pbkdf", "argon2id", "--label", f"{v.role}-luks", "--key-file=-", dev], "PASSPHRASE"))
            cmds.append((f"Unlock {dev}", ["cryptsetup", "open", "--key-file=-", dev, v.mapper], "PASSPHRASE"))
            dev = v.fs_device
        label = {"esp": "EFI", "xbootldr": "BOOT", "boot": "BOOT", "root": "ROOT", "home": "HOME", "swap": "SWAP"}.get(v.role, "DATA")
        if v.fs == "vfat":
            cmds.append((f"Format {dev} (FAT32)", ["mkfs.fat", "-F", "32", "-n", label, dev], None))
        elif v.fs == "ext4":
            cmds.append((f"Format {dev} (ext4)", ["mkfs.ext4", "-F", "-q", "-L", label, dev], None))
        elif v.fs == "btrfs":
            cmds.append((f"Format {dev} (Btrfs)", ["mkfs.btrfs", "-f", "-q", "-L", label, dev], None))
        elif v.fs == "xfs":
            cmds.append((f"Format {dev} (XFS)", ["mkfs.xfs", "-f", "-L", label, dev], None))
        elif v.fs == "swap":
            cmds.append((f"Create swap on {dev}", ["mkswap", "-L", label, dev], None))
    return cmds


def mount_table(plan: DiskPlan) -> list[tuple[str, str, str, str]]:
    """(device, mountpoint, fstype, options) in mount order, relative to the
    target root. Btrfs roots get subvolumes."""
    table: list[tuple[str, str, str, str]] = []
    root = plan.volume("root")
    assert root is not None
    home_separate = plan.volume("home") is not None
    if root.fs == "btrfs":
        for sub, mp in BTRFS_SUBVOLUMES:
            if mp == "/home" and home_separate:
                continue
            table.append((root.fs_device, mp, "btrfs", f"{BTRFS_OPTIONS},subvol={sub}"))
    else:
        table.append((root.fs_device, "/", root.fs, "noatime" if root.fs in ("ext4", "xfs") else "defaults"))
    home = plan.volume("home")
    if home is not None:
        opts = BTRFS_OPTIONS if home.fs == "btrfs" else "noatime"
        table.append((home.fs_device, "/home", home.fs, opts))
    for role in ("boot", "xbootldr", "esp"):
        v = plan.volume(role)
        if v is not None and v.mountpoint:
            table.append((v.fs_device, v.mountpoint, v.fs or "vfat", "umask=0077" if v.fs == "vfat" else "defaults"))
    # /boot before /efi is fine; /boot/efi layouts are not used.
    table.sort(key=lambda t: (t[1].count("/") if t[1] != "/" else 0, t[1]))
    return table
