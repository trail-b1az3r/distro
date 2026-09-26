"""CPU, memory, chassis, firmware and virtualisation detection."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .. import util
from .sysroot import SysRoot

# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------


@dataclass
class CpuInfo:
    vendor: str  # "intel" | "amd" | "other"
    vendor_id: str
    model: str
    family: int
    model_number: int
    cores: int
    threads: int
    flags: list[str] = field(default_factory=list)
    hypervisor: bool = False

    @property
    def microcode_package(self) -> str | None:
        return {"intel": "intel-ucode", "amd": "amd-ucode"}.get(self.vendor)

    @property
    def x86_64_level(self) -> int:
        f = set(self.flags)
        if {"avx512f", "avx512bw", "avx512cd", "avx512dq", "avx512vl"} <= f:
            return 4
        if {"avx", "avx2", "bmi1", "bmi2", "fma", "movbe", "xsave"} <= f:
            return 3
        if {"cx16", "lahf_lm", "popcnt", "sse4_1", "sse4_2", "ssse3"} <= f:
            return 2
        return 1

    def to_dict(self) -> dict:
        d = asdict(self)
        d["microcode_package"] = self.microcode_package
        d["x86_64_level"] = self.x86_64_level
        d.pop("flags")
        d["notable_flags"] = sorted(set(self.flags) & {"avx", "avx2", "avx512f", "avx_vnni", "amx_tile", "f16c", "fma", "vmx", "svm"})
        return d


def _clean_cpu_model(name: str) -> str:
    name = re.sub(r"\((R|TM|tm|r)\)", "", name)
    name = re.sub(r"\bCPU\b", "", name)
    name = re.sub(r"\s+\d+-Core Processor", "", name)
    name = re.sub(r"@\s*[\d.]+\s*GHz", "", name)
    name = re.sub(r"\bProcessor\b", "", name) if "Core" in name else name
    return re.sub(r"\s{2,}", " ", name).strip()


def detect_cpu(sysroot: SysRoot) -> CpuInfo:
    text = sysroot.read("/proc/cpuinfo")
    blocks = [b for b in text.split("\n\n") if b.strip()]
    first: dict[str, str] = {}
    physical_cores: set[tuple[str, str]] = set()
    for block in blocks:
        entry: dict[str, str] = {}
        for line in block.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                entry[k.strip()] = v.strip()
        if not first:
            first = entry
        physical_cores.add((entry.get("physical id", "0"), entry.get("core id", entry.get("processor", "0"))))
    vendor_id = first.get("vendor_id", "")
    vendor = {"GenuineIntel": "intel", "AuthenticAMD": "amd", "HygonGenuine": "amd"}.get(vendor_id, "other")
    flags = first.get("flags", "").split()
    threads = len(blocks)
    cores = len(physical_cores) if physical_cores else threads
    try:
        cpu_cores_field = int(first.get("cpu cores", "0"))
    except ValueError:
        cpu_cores_field = 0
    if cpu_cores_field and cores < cpu_cores_field:
        cores = cpu_cores_field

    def as_int(key: str) -> int:
        try:
            return int(first.get(key, "0"))
        except ValueError:
            return 0

    return CpuInfo(
        vendor=vendor,
        vendor_id=vendor_id,
        model=_clean_cpu_model(first.get("model name", "Unknown CPU")),
        family=as_int("cpu family"),
        model_number=as_int("model"),
        cores=cores,
        threads=threads,
        flags=flags,
        hypervisor="hypervisor" in flags,
    )


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


@dataclass
class MemoryInfo:
    total_bytes: int
    swap_bytes: int

    @property
    def total_gib(self) -> float:
        return self.total_bytes / 2**30

    def marketing_gb(self) -> int:
        """Round MemTotal (which excludes reserved memory) to the installed size."""
        gib = self.total_gib
        for size in (1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024):
            if gib <= size * 1.0 and gib >= size * 0.85:
                return size
        return round(gib)

    def to_dict(self) -> dict:
        return {
            "total_bytes": self.total_bytes,
            "swap_bytes": self.swap_bytes,
            "total_gib": round(self.total_gib, 1),
            "installed_gb": self.marketing_gb(),
        }


def detect_memory(sysroot: SysRoot) -> MemoryInfo:
    values = {}
    for line in sysroot.read("/proc/meminfo").splitlines():
        m = re.match(r"^(\w+):\s+(\d+)\s*kB", line)
        if m:
            values[m.group(1)] = int(m.group(2)) * 1024
    return MemoryInfo(total_bytes=values.get("MemTotal", 0), swap_bytes=values.get("SwapTotal", 0))


# ---------------------------------------------------------------------------
# Chassis
# ---------------------------------------------------------------------------

# SMBIOS chassis types (DMTF DSP0134, table 17)
_CHASSIS = {
    3: "desktop", 4: "desktop", 5: "desktop", 6: "desktop", 7: "desktop",
    8: "laptop", 9: "laptop", 10: "laptop", 11: "handheld", 12: "laptop", 13: "desktop",
    14: "laptop", 15: "desktop", 16: "desktop", 17: "server", 23: "server", 24: "desktop",
    28: "server", 29: "server",
    30: "tablet", 31: "convertible", 32: "detachable", 35: "desktop", 36: "desktop",
}


@dataclass
class ChassisInfo:
    kind: str  # desktop | laptop | convertible | detachable | tablet | handheld | server | vm | unknown
    chassis_type: int
    sys_vendor: str
    product_name: str
    product_family: str
    product_version: str
    board_vendor: str
    board_name: str
    bios_vendor: str
    bios_version: str
    has_battery: bool
    has_lid: bool
    surface: bool
    surface_model: str

    @property
    def portable(self) -> bool:
        return self.kind in ("laptop", "convertible", "detachable", "tablet", "handheld") or self.has_battery

    @property
    def description(self) -> str:
        vendor = self.sys_vendor.replace(" Corporation", "").replace(" Inc.", "").strip()
        name = self.product_version if self.product_name.lower() in ("", "to be filled by o.e.m.") else self.product_name
        if vendor.lower() in name.lower():
            return name
        return f"{vendor} {name}".strip()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["portable"] = self.portable
        d["description"] = self.description
        return d


_SURFACE_ACPI_PREFIX = "MSHW"


def detect_chassis(sysroot: SysRoot, virtual: bool = False) -> ChassisInfo:
    dmi = "/sys/class/dmi/id"

    def r(name: str) -> str:
        value = sysroot.read(f"{dmi}/{name}")
        return "" if value.lower() in ("default string", "system product name", "system manufacturer") else value

    ctype = sysroot.read_int(f"{dmi}/chassis_type", 2) or 2
    has_battery = any(
        sysroot.read(f"/sys/class/power_supply/{ps}/type") == "Battery"
        and sysroot.read(f"/sys/class/power_supply/{ps}/scope", "System") != "Device"
        for ps in sysroot.listdir("/sys/class/power_supply")
    )
    has_lid = bool(sysroot.listdir("/proc/acpi/button/lid"))
    vendor = r("sys_vendor")
    product = r("product_name")
    family = r("product_family")
    surface = False
    surface_model = ""
    if "microsoft" in vendor.lower() and ("surface" in product.lower() or "surface" in family.lower()):
        surface = True
        surface_model = product or family
    elif any(dev.startswith(_SURFACE_ACPI_PREFIX) for dev in sysroot.listdir("/sys/bus/acpi/devices")):
        # Surface-specific ACPI devices (MSHWxxxx) without matching DMI strings,
        # e.g. boards with replaced firmware tables.
        surface = True
        surface_model = product or "Microsoft Surface"

    kind = _CHASSIS.get(ctype, "unknown")
    if virtual:
        kind = "vm"
    elif kind in ("unknown", "desktop") and has_battery and has_lid:
        kind = "laptop"
    return ChassisInfo(
        kind=kind,
        chassis_type=ctype,
        sys_vendor=vendor,
        product_name=product,
        product_family=family,
        product_version=r("product_version"),
        board_vendor=r("board_vendor"),
        board_name=r("board_name"),
        bios_vendor=r("bios_vendor"),
        bios_version=r("bios_version"),
        has_battery=has_battery,
        has_lid=has_lid,
        surface=surface,
        surface_model=surface_model,
    )


# ---------------------------------------------------------------------------
# Firmware
# ---------------------------------------------------------------------------

_EFI_GLOBAL = "8be4df61-93ca-11d2-aa0d-00e098032b8c"


@dataclass
class FirmwareInfo:
    uefi: bool
    platform_bits: int  # 64, 32 (IA32 UEFI) or 0 on BIOS
    secure_boot: bool | None  # None = unknown
    setup_mode: bool | None
    tpm: bool

    @property
    def mode(self) -> str:
        if not self.uefi:
            return "bios"
        return "uefi" if self.platform_bits != 32 else "uefi-ia32"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mode"] = self.mode
        return d


def _efivar_bool(sysroot: SysRoot, name: str) -> bool | None:
    data = sysroot.read_bytes(f"/sys/firmware/efi/efivars/{name}-{_EFI_GLOBAL}")
    if len(data) >= 5:
        return data[4] == 1
    return None


def detect_firmware(sysroot: SysRoot) -> FirmwareInfo:
    uefi = sysroot.is_dir("/sys/firmware/efi")
    bits = sysroot.read_int("/sys/firmware/efi/fw_platform_size", 64 if uefi else 0) if uefi else 0
    return FirmwareInfo(
        uefi=uefi,
        platform_bits=bits or 0,
        secure_boot=_efivar_bool(sysroot, "SecureBoot") if uefi else False,
        setup_mode=_efivar_bool(sysroot, "SetupMode") if uefi else None,
        tpm=bool(sysroot.listdir("/sys/class/tpm")),
    )


# ---------------------------------------------------------------------------
# Virtualisation
# ---------------------------------------------------------------------------


@dataclass
class VirtInfo:
    kind: str  # none | kvm | qemu | vmware | oracle | microsoft | xen | other
    product: str

    @property
    def is_virtual(self) -> bool:
        return self.kind != "none"

    @property
    def guest_list(self) -> str | None:
        return {
            "kvm": "virt-qemu",
            "qemu": "virt-qemu",
            "vmware": "virt-vmware",
            "oracle": "virt-virtualbox",
            "microsoft": "virt-hyperv",
        }.get(self.kind)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "product": self.product, "is_virtual": self.is_virtual}


def detect_virt(sysroot: SysRoot, cpu: CpuInfo) -> VirtInfo:
    vendor = sysroot.read("/sys/class/dmi/id/sys_vendor").lower()
    product = sysroot.read("/sys/class/dmi/id/product_name")
    plower = product.lower()
    if sysroot.is_live_root:
        rc, out = util.run_quiet(["systemd-detect-virt", "--vm"])
        kind = out.strip()
        if rc == 0 and kind and kind != "none":
            return VirtInfo(kind=kind, product=product)
        if rc == 1:
            return VirtInfo(kind="none", product=product)
    if "qemu" in vendor or "qemu" in plower or "kvm" in plower:
        return VirtInfo("kvm", product)
    if "vmware" in vendor or "vmware" in plower:
        return VirtInfo("vmware", product)
    if "innotek" in vendor or "virtualbox" in plower:
        return VirtInfo("oracle", product)
    if "microsoft" in vendor and plower == "virtual machine":
        return VirtInfo("microsoft", product)
    if "xen" in vendor:
        return VirtInfo("xen", product)
    if cpu.hypervisor:
        return VirtInfo("other", product)
    return VirtInfo("none", product)
