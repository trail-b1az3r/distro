"""GPU detection and classification.

Each display-class PCI device becomes a :class:`Gpu` with:

* vendor, marketing model and chip codename (from the PCI ID database),
* architecture and driver branch (``hardware/detection/gpu-families.toml``),
* whether it is integrated or discrete,
* video memory (from the running driver when it reports it, otherwise an
  estimate from ``gpu-vram.tsv`` that is labelled as such),
* the displays connected to it.

Nothing here assumes a particular vendor or that a discrete GPU exists.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .. import paths, util
from . import ids
from .display import Display
from .pci import PciDevice
from .sysroot import SysRoot

NVIDIA, AMD, INTEL = 0x10DE, 0x1002, 0x8086
VIRTUAL_VENDORS = {0x1AF4: "virtio", 0x1B36: "qxl", 0x1234: "bochs", 0x15AD: "vmware", 0x80EE: "virtualbox", 0x1414: "hyperv"}


@dataclass
class Gpu:
    slot: str
    vendor: str  # nvidia | amd | intel | virtio | qxl | bochs | vmware | virtualbox | hyperv | other
    vendor_name: str
    pci_id: str
    model: str
    codename: str
    architecture: str
    kind: str  # integrated | discrete | virtual
    boot_vga: bool
    driver_in_use: str
    vram_bytes: int = 0
    vram_source: str = ""  # driver | nvidia-smi | estimate | shared | ""
    driver_branch: str = ""  # NVIDIA: open | legacy580 | nouveau; AMD: amdgpu | radeon; Intel: i915/xe
    extras: dict[str, Any] = field(default_factory=dict)
    connectors: list[str] = field(default_factory=list)

    @property
    def is_nvidia(self) -> bool:
        return self.vendor == "nvidia"

    @property
    def has_internal_display(self) -> bool:
        return any(c.split("-")[0] in ("eDP", "LVDS", "DSI") for c in self.connectors)

    @property
    def vram_gib(self) -> float:
        return round(self.vram_bytes / 2**30, 1)

    @property
    def display_name(self) -> str:
        vendor = {"nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel"}.get(self.vendor, self.vendor_name)
        model = self.model or "Graphics"
        return model if model.lower().startswith(vendor.lower()) else f"{vendor} {model}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["display_name"] = self.display_name
        d["vram_gib"] = self.vram_gib
        return d


@lru_cache(maxsize=4)
def _families(data_root: str) -> dict[str, Any]:
    with (Path(data_root) / "hardware" / "detection" / "gpu-families.toml").open("rb") as fh:
        return tomllib.load(fh)


@lru_cache(maxsize=4)
def _vram_table(data_root: str) -> list[tuple[str, re.Pattern[str], int]]:
    rows = []
    path = Path(data_root) / "hardware" / "detection" / "gpu-vram.tsv"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        vendor, pattern, gib = line.split("\t")
        rows.append((vendor, re.compile(pattern, re.IGNORECASE), int(gib)))
    return rows


def families() -> dict[str, Any]:
    return _families(str(paths.DATA_ROOT))


def classify_nvidia(codename: str, device_id: int) -> tuple[str, str]:
    """Return (architecture, driver branch) for an NVIDIA GPU."""
    table = families()["nvidia"]
    prefixes = sorted(table["prefixes"].items(), key=lambda kv: -len(kv[0]))
    code = codename.upper()
    for prefix, spec in prefixes:
        if code.startswith(prefix):
            return spec["arch"], spec["branch"]
    for branch, ranges in table["device_id_ranges"].items():
        for lo, hi in ranges:
            if lo <= device_id <= hi:
                return "unknown", branch
    return "unknown", "nouveau"


def classify_amd(name: str) -> dict[str, Any]:
    table = families()["amd"]["codenames"]
    for code in sorted(table, key=len, reverse=True):
        if re.search(rf"(?<![\w]){re.escape(code)}(?![\w])", name, re.IGNORECASE):
            spec = dict(table[code])
            spec["codename"] = code
            return spec
    return {}


def classify_intel(name: str) -> dict[str, Any]:
    for rule in families()["intel"]["rules"]:
        if re.search(rule["match"], name, re.IGNORECASE):
            return rule
    return {"family": "unknown"}


def rocm_support(gfx: str) -> tuple[str, str]:
    """("native" | "override" | "none", HSA_OVERRIDE_GFX_VERSION value)."""
    rocm = families()["amd"]["rocm"]
    if gfx in rocm["native"]:
        return "native", ""
    if gfx in rocm.get("override", {}):
        return "override", rocm["override"][gfx]
    return "none", ""


def estimate_vram(vendor: str, model: str) -> int:
    """Estimated VRAM in bytes from the model name, or 0 when unknown.

    pci.ids sometimes lists several models under one device ID
    ("Radeon RX 7900 XT/7900 XTX/7900 GRE"); then the smallest matching
    size is returned, so the estimate never overstates the card.
    """
    table = _vram_table(str(paths.DATA_ROOT))
    candidates = [model]
    if "/" in model:
        head = re.match(r"^(.*?\b(?:RX|RTX|GTX|Arc)\s+)", model)
        prefix = head.group(1) if head else ""
        first, *rest = model.split("/")
        candidates = [first] + [prefix + r.strip() if prefix and not r.strip().startswith(prefix.strip()) else r.strip() for r in rest]
    sizes = []
    for cand in candidates:
        for v, pattern, gib in table:
            if v == vendor and pattern.search(cand):
                sizes.append(gib)
                break
    return min(sizes) * 2**30 if sizes else 0


def _nvidia_smi_vram(sysroot: SysRoot) -> dict[str, int]:
    if not sysroot.is_live_root or not util.which("nvidia-smi"):
        return {}
    rc, out = util.run_quiet(["nvidia-smi", "--query-gpu=pci.bus_id,memory.total", "--format=csv,noheader,nounits"])
    result = {}
    if rc == 0:
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 2:
                bus = parts[0].lower()
                # nvidia-smi prints 00000000:01:00.0; sysfs uses 0000:01:00.0
                slot = bus[-12:] if len(bus) >= 12 else bus
                try:
                    result[slot] = int(float(parts[1])) * 2**20
                except ValueError:
                    pass
    return result


def detect_gpus(sysroot: SysRoot, pci_devices: list[PciDevice], displays: list[Display]) -> list[Gpu]:
    db = ids.pci_ids(sysroot)
    smi = _nvidia_smi_vram(sysroot)
    gpus = []
    for dev in pci_devices:
        if not dev.is_display:
            continue
        full_name = dev.name or f"Device {dev.device_id:04x}"
        model = ids.marketing_name(dev.subsystem_name) if dev.subsystem_name and dev.vendor_id == AMD else ""
        model = model or ids.marketing_name(full_name)
        code = ids.codename(full_name)
        extras: dict[str, Any] = {}
        vram = 0
        vram_source = ""
        if dev.vendor_id == NVIDIA:
            vendor = "nvidia"
            arch, branch = classify_nvidia(code, dev.device_id)
            kind = "discrete"
            if dev.slot in smi:
                vram, vram_source = smi[dev.slot], "nvidia-smi"
        elif dev.vendor_id == AMD:
            vendor = "amd"
            spec = classify_amd(full_name) or classify_amd(dev.subsystem_name)
            arch = spec.get("family", "unknown")
            branch = "radeon" if spec.get("legacy") else "amdgpu"
            kind = "integrated" if spec.get("integrated") else "discrete"
            code = spec.get("codename", code)
            if spec.get("gfx"):
                extras["gfx"] = spec["gfx"]
                support, override = rocm_support(spec["gfx"])
                extras["rocm"] = support
                if override:
                    extras["hsa_override_gfx_version"] = override
            if spec.get("si"):
                extras["kernel_params"] = ["radeon.si_support=0", "amdgpu.si_support=1"]
            elif spec.get("cik"):
                extras["kernel_params"] = ["radeon.cik_support=0", "amdgpu.cik_support=1"]
            sys_vram = sysroot.read_int(f"{dev.sysfs}/mem_info_vram_total", 0) or 0
            if sys_vram:
                vram, vram_source = sys_vram, "driver"
                # APUs have a small carve-out; very large carve-outs (Strix Halo)
                # are still integrated, which the codename already told us.
        elif dev.vendor_id == INTEL:
            vendor = "intel"
            rule = classify_intel(full_name)
            arch = rule.get("family", "unknown")
            kind = "discrete" if rule.get("discrete") else "integrated"
            branch = dev.driver if dev.driver in ("i915", "xe") else ("xe" if arch == "xe2" else "i915")
            if rule.get("legacy_vaapi"):
                extras["legacy_vaapi"] = True
        elif dev.vendor_id in VIRTUAL_VENDORS:
            vendor = VIRTUAL_VENDORS[dev.vendor_id]
            arch, branch, kind = "virtual", dev.driver, "virtual"
        else:
            vendor = "other"
            arch, branch, kind = "unknown", dev.driver, "discrete"

        if not vram and vendor in ("nvidia", "amd", "intel"):
            if kind == "integrated":
                vram_source = "shared"
            else:
                vram = estimate_vram(vendor, model)
                vram_source = "estimate" if vram else ""

        card_connectors = [d.connector for d in displays if d.pci_slot == dev.slot]
        gpus.append(
            Gpu(
                slot=dev.slot,
                vendor=vendor,
                vendor_name=ids.short_vendor(dev.vendor_id, db),
                pci_id=f"{dev.vendor_id:04x}:{dev.device_id:04x}",
                model=model,
                codename=code,
                architecture=arch,
                kind=kind,
                boot_vga=dev.boot_vga,
                driver_in_use=dev.driver,
                vram_bytes=vram,
                vram_source=vram_source,
                driver_branch=branch,
                extras=extras,
                connectors=card_connectors,
            )
        )
    # Integrated first, then discrete, each in PCI order: matches how
    # firmware usually enumerates them and keeps output stable.
    gpus.sort(key=lambda g: ({"integrated": 0, "discrete": 1, "virtual": 2}[g.kind], g.slot))
    return gpus


@dataclass
class GpuTopology:
    """How the GPUs of a machine relate to each other."""

    mode: str  # none | single | hybrid | multi
    primary: Gpu | None  # drives the internal panel / boot display
    offload: Gpu | None  # render-offload GPU on hybrid systems

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "primary": self.primary.slot if self.primary else None,
            "offload": self.offload.slot if self.offload else None,
        }


def topology(gpus: list[Gpu], portable: bool) -> GpuTopology:
    real = [g for g in gpus if g.kind != "virtual"] or gpus
    if not real:
        return GpuTopology("none", None, None)
    if len(real) == 1:
        return GpuTopology("single", real[0], None)
    integrated = [g for g in real if g.kind == "integrated"]
    discrete = [g for g in real if g.kind == "discrete"]
    if integrated and discrete:
        igpu, dgpu = integrated[0], discrete[0]
        if portable:
            # A laptop's panel is on the iGPU (PRIME offload to the dGPU)
            # unless a MUX switch has routed it to the dGPU.
            if dgpu.has_internal_display:
                return GpuTopology("multi", dgpu, None)
            return GpuTopology("hybrid", igpu, dgpu)
        # Desktop: whichever GPU has the monitors drives the desktop. Monitors
        # on the iGPU with a headless dGPU is a render/compute-offload setup.
        if igpu.connectors and not dgpu.connectors:
            return GpuTopology("hybrid", igpu, dgpu)
        if dgpu.connectors and not igpu.connectors:
            return GpuTopology("multi", dgpu, None)
        boot = next((g for g in (dgpu, igpu) if g.boot_vga), dgpu)
        return GpuTopology("multi", boot, None)
    # Several discrete GPUs (or several iGPU-less cards): the boot GPU is primary.
    boot = next((g for g in real if g.boot_vga), real[0])
    return GpuTopology("multi", boot, None)
