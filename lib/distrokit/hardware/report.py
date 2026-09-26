"""The hardware report: everything the installer and tools need to know about
the machine, gathered in one pass."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import util
from . import display, graphics, inputdev, network, pci, platform, storage
from .sysroot import SysRoot


@dataclass
class HardwareReport:
    cpu: platform.CpuInfo
    memory: platform.MemoryInfo
    chassis: platform.ChassisInfo
    firmware: platform.FirmwareInfo
    virt: platform.VirtInfo
    gpus: list[graphics.Gpu]
    topology: graphics.GpuTopology
    displays: list[display.Display]
    disks: list[storage.Disk]
    network: list[network.NetAdapter]
    bluetooth: list[network.BluetoothAdapter]
    inputs: list[inputdev.InputDevice]
    usb: list[pci.UsbDevice] = field(default_factory=list)

    # -- convenience ---------------------------------------------------------
    @property
    def has_touchscreen(self) -> bool:
        return any(d.kind == "touchscreen" for d in self.inputs)

    @property
    def has_touchpad(self) -> bool:
        return any(d.kind == "touchpad" for d in self.inputs)

    @property
    def has_pen(self) -> bool:
        return any(d.kind == "pen" for d in self.inputs)

    @property
    def wifi(self) -> list[network.NetAdapter]:
        return [n for n in self.network if n.kind == "wifi"]

    @property
    def external_displays(self) -> list[display.Display]:
        return [d for d in self.displays if not d.internal]

    @property
    def installable_disks(self) -> list[storage.Disk]:
        return [d for d in self.disks if d.installable]

    def gpu(self, slot: str) -> graphics.Gpu | None:
        return next((g for g in self.gpus if g.slot == slot), None)

    @property
    def nvidia(self) -> list[graphics.Gpu]:
        return [g for g in self.gpus if g.vendor == "nvidia"]

    @property
    def best_compute_gpu(self) -> graphics.Gpu | None:
        """The GPU most useful for local AI: discrete first, then most VRAM."""
        real = [g for g in self.gpus if g.vendor in ("nvidia", "amd", "intel")]
        if not real:
            return None
        return max(real, key=lambda g: (g.kind == "discrete", g.vram_bytes, g.vendor == "nvidia"))

    # -- serialisation -------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu": self.cpu.to_dict(),
            "memory": self.memory.to_dict(),
            "chassis": self.chassis.to_dict(),
            "firmware": self.firmware.to_dict(),
            "virtualization": self.virt.to_dict(),
            "gpus": [g.to_dict() for g in self.gpus],
            "gpu_topology": self.topology.to_dict(),
            "displays": [d.to_dict() for d in self.displays],
            "disks": [d.to_dict() for d in self.disks],
            "network": [n.to_dict() for n in self.network],
            "bluetooth": [b.to_dict() for b in self.bluetooth],
            "input": {
                "touchscreen": self.has_touchscreen,
                "touchpad": self.has_touchpad,
                "pen": self.has_pen,
                "devices": [d.to_dict() for d in self.inputs if d.kind != "other"],
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=False)

    # -- human summary -------------------------------------------------------
    def summary_rows(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        rows.append(("System", self.chassis.description or "Unknown"))
        kind = "Virtual machine" if self.chassis.kind == "vm" else self.chassis.kind.capitalize()
        rows.append(("Type", kind + (f" ({self.virt.kind})" if self.virt.is_virtual else "")))
        rows.append(("CPU", f"{self.cpu.model} ({self.cpu.cores} cores / {self.cpu.threads} threads)"))
        for gpu in self.gpus:
            label = "GPU" if len(self.gpus) == 1 else f"GPU ({gpu.kind})"
            vram = ""
            if gpu.vram_bytes:
                vram = f", {gpu.vram_gib:g} GB VRAM" + (" (estimated)" if gpu.vram_source == "estimate" else "")
            rows.append((label, f"{gpu.display_name}{vram}"))
        if not self.gpus:
            rows.append(("GPU", "None detected"))
        rows.append(("RAM", f"{self.memory.marketing_gb()} GB"))
        for disk in self.disks:
            if disk.live_medium or disk.size_bytes < 2**30:
                continue
            rows.append(("Storage", f"{disk.description} — {disk.model or disk.name}"))
        for d in self.displays:
            where = "Built-in" if d.internal else f"External ({d.connector})"
            rows.append(("Display", f"{where} {d.width} × {d.height}" + (f", {d.diagonal_inches:g}\"" if d.diagonal_inches else "")))
        for w in self.wifi:
            rows.append(("Wi-Fi", f"{w.vendor} {w.name}".strip()))
        for b in self.bluetooth:
            rows.append(("Bluetooth", f"{b.vendor} {b.name}".strip()))
        extras = []
        if self.has_touchpad:
            extras.append("touchpad")
        if self.has_touchscreen:
            extras.append("touchscreen")
        if self.has_pen:
            extras.append("pen")
        if extras:
            rows.append(("Input", ", ".join(extras)))
        fw = self.firmware
        boot = "UEFI" if fw.uefi else "BIOS (legacy)"
        if fw.uefi:
            boot += f", Secure Boot {'on' if fw.secure_boot else 'off' if fw.secure_boot is False else 'unknown'}"
        rows.append(("Firmware", boot))
        if self.chassis.surface:
            rows.append(("Surface", f"Microsoft {self.chassis.surface_model}"))
        return rows

    def summary(self) -> str:
        return util.table(self.summary_rows())


def _name_apu_graphics(gpus: list[graphics.Gpu], cpu: platform.CpuInfo) -> None:
    """pci.ids often names AMD APU graphics only by codename ("Phoenix1");
    the CPU model string carries the marketing name ("w/ Radeon 780M Graphics")."""
    m = re.search(r"(Radeon(?: \w+)? Graphics)", cpu.model)
    if not m:
        return
    for gpu in gpus:
        if gpu.vendor == "amd" and gpu.kind == "integrated" and "radeon" not in gpu.model.lower():
            gpu.model = f"{m.group(1)} ({gpu.model})" if gpu.model else m.group(1)


def detect(root: str | Path = "/", lsblk: dict[str, Any] | None = None, live_label_prefix: str = "") -> HardwareReport:
    sysroot = SysRoot(root)
    cpu = platform.detect_cpu(sysroot)
    virt = platform.detect_virt(sysroot, cpu)
    chassis = platform.detect_chassis(sysroot, virtual=virt.is_virtual)
    pci_devices = pci.list_pci(sysroot)
    usb_devices = pci.list_usb(sysroot)
    displays = display.detect_displays(sysroot)
    gpus = graphics.detect_gpus(sysroot, pci_devices, displays)
    _name_apu_graphics(gpus, cpu)
    if lsblk is None:
        fixture = sysroot.path("/lsblk.json")
        if not sysroot.is_live_root and fixture.is_file():
            lsblk = json.loads(fixture.read_text())
        elif sysroot.is_live_root:
            lsblk = storage.run_lsblk()
    return HardwareReport(
        cpu=cpu,
        memory=platform.detect_memory(sysroot),
        chassis=chassis,
        firmware=platform.detect_firmware(sysroot),
        virt=virt,
        gpus=gpus,
        topology=graphics.topology(gpus, chassis.portable),
        displays=displays,
        disks=storage.detect_storage(sysroot, lsblk, live_label_prefix),
        network=network.detect_network(sysroot, pci_devices),
        bluetooth=network.detect_bluetooth(sysroot, pci_devices, usb_devices),
        inputs=inputdev.detect_input(sysroot),
        usb=usb_devices,
    )
