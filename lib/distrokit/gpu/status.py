"""What the graphics stack is actually doing right now."""

from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import pkg, util
from ..branding import Branding, load as load_branding
from ..hardware.report import HardwareReport
from . import apply as gpu_apply
from .plan import build_plan, stack

KERNEL_DRIVER = {
    "nvidia-open": ("nvidia",),
    "nvidia-580xx": ("nvidia",),
    "nouveau": ("nouveau",),
    "amdgpu": ("amdgpu",),
    "radeon": ("radeon",),
    "intel": ("i915", "xe"),
    "intel-discrete": ("i915", "xe"),
    "intel-legacy": ("i915",),
    "virtual": (),
}

VULKAN_ICD = {
    "nvidia": "nvidia_icd.json",
    "nouveau": "nouveau_icd",
    "amdgpu": "radeon_icd",
    "i915": "intel_icd",
    "xe": "intel_icd",
}


@dataclass
class GpuStatus:
    slot: str
    vendor: str
    model: str
    role: str
    expected_stack: str
    stack_label: str
    driver: str
    vram: str
    vulkan: str
    cuda: str
    rocm: str
    vaapi: str
    wayland: str
    status: str
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _vulkan_devices() -> list[str]:
    if not util.which("vulkaninfo"):
        return []
    rc, out = util.run_quiet(["vulkaninfo", "--summary"], timeout=20)
    if rc != 0:
        return []
    return [m.strip() for m in re.findall(r"deviceName\s*=\s*(.+)", out)]


def _icd_present(root: Path, driver: str) -> bool:
    name = VULKAN_ICD.get(driver)
    if not name:
        return False
    for d in ("usr/share/vulkan/icd.d", "etc/vulkan/icd.d"):
        if glob.glob(str(root / d / f"{name}*")):
            return True
    return False


def _cuda(root: Path) -> str:
    lib = any(Path(p).exists() for p in (root / "usr/lib/libcuda.so.1", root / "usr/lib/libcuda.so"))
    if not lib:
        return "Not available"
    toolkit = (root / "opt/cuda/bin/nvcc").exists()
    if str(root) == "/" and util.which("nvidia-smi"):
        rc, out = util.run_quiet(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"])
        if rc == 0:
            return f"Available (driver {out.strip().splitlines()[0]}" + (", toolkit installed)" if toolkit else ")")
        return "Driver installed, not loaded (reboot?)"
    return "Available" + (" (toolkit installed)" if toolkit else "")


def _rocm(root: Path) -> str:
    if (root / "opt/rocm/bin/rocminfo").exists():
        return "Installed"
    return "Not installed"


def gather(report: HardwareReport, root: Path | str = "/", branding: Branding | None = None) -> list[GpuStatus]:
    root = Path(root)
    branding = branding or load_branding()
    state = gpu_apply.load_state(root, branding)
    configured = {c["slot"]: c for c in (state or {}).get("plan", {}).get("choices", [])}
    live_plan = build_plan(report, branding=branding, overrides={s: c["stack"] for s, c in configured.items()
                                                                 if report.gpu(s)})
    installed = pkg.installed_packages(root)
    vk_devices = _vulkan_devices() if str(root) == "/" else []
    session = os.environ.get("XDG_SESSION_TYPE", "")
    results = []
    for choice in live_plan.choices:
        gpu = report.gpu(choice.slot)
        assert gpu is not None
        s = stack(choice.stack)
        problems = []
        missing = [p for p in s.get("packages", []) if p not in installed and not p.endswith("-dkms")]
        dkms = [p for p in s.get("packages", []) if p.endswith("-dkms")]
        if dkms and not any(p in installed for p in dkms + list(s.get("prebuilt", {}).values())):
            missing += dkms
        if missing:
            problems.append("missing packages: " + ", ".join(missing))
        expected = KERNEL_DRIVER.get(choice.stack, ())
        driver = gpu.driver_in_use or "none"
        if expected and driver not in expected:
            if driver == "none":
                problems.append(f"no kernel driver bound (expected {'/'.join(expected)})")
            else:
                problems.append(f"running {driver}, expected {'/'.join(expected)} — reboot if you just changed drivers")
        if choice.slot not in configured:
            status = "Not configured" if state is None else "New hardware (not configured)"
        elif problems:
            status = "Needs attention"
        else:
            status = "Configured"

        if gpu.vendor in ("nvidia", "amd", "intel"):
            if vk_devices:
                hit = any(gpu.model.split()[-1] in d for d in vk_devices) or any(gpu.vendor in d.lower() for d in vk_devices)
                vulkan = "Available" if hit else "Not detected by vulkaninfo"
            else:
                vulkan = "Available" if _icd_present(root, driver) else ("Not available" if not s.get("vulkan", "").startswith("yes") else "Driver not loaded")
        else:
            vulkan = "Software / virtual"
        vram = ""
        if gpu.vram_bytes:
            vram = f"{gpu.vram_gib:g} GB" + (" (estimated)" if gpu.vram_source == "estimate" else "")
        elif gpu.kind == "integrated":
            vram = "Shared with system memory"
        results.append(
            GpuStatus(
                slot=gpu.slot,
                vendor={"nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel"}.get(gpu.vendor, gpu.vendor_name),
                model=gpu.model,
                role=choice.role,
                expected_stack=choice.stack,
                stack_label=s["label"],
                driver=driver,
                vram=vram,
                vulkan=vulkan,
                cuda=_cuda(root) if gpu.vendor == "nvidia" and choice.stack.startswith("nvidia-") else "Not applicable",
                rocm=_rocm(root) if gpu.vendor == "amd" and gpu.extras.get("rocm", "none") != "none" else "Not applicable",
                vaapi=s.get("vaapi", ""),
                wayland=("Supported" if s.get("wayland", "").startswith("yes") else "Limited")
                + (f" (current session: {session})" if session and str(root) == "/" else ""),
                status=status,
                problems=problems,
            )
        )
    return results


def render(statuses: list[GpuStatus], style: util.Style | None = None) -> str:
    style = style or util.style
    if not statuses:
        return "GPU Detection\nNo display adapters found."
    blocks = []
    for st in statuses:
        rows = [("Vendor", st.vendor), ("Model", st.model)]
        if st.role not in ("only",):
            rows.append(("Role", st.role))
        rows += [("Driver", st.driver), ("Stack", st.stack_label)]
        if st.vram:
            rows.append(("VRAM", st.vram))
        if st.vendor == "AMD":
            rows.append(("Mesa", "Installed"))
        rows += [("Vulkan", st.vulkan)]
        if st.cuda != "Not applicable":
            rows.append(("CUDA", st.cuda))
        if st.rocm != "Not applicable":
            rows.append(("ROCm", st.rocm))
        rows += [("VA-API", st.vaapi), ("Wayland", st.wayland), ("Status", st.status)]
        text = util.table(rows)
        for p in st.problems:
            text += "\n" + style.warn(p)
        blocks.append(text)
    return style.header("GPU Detection") + "\n" + "\n\n".join(blocks)


def to_json(statuses: list[GpuStatus]) -> str:
    return json.dumps([s.to_dict() for s in statuses], indent=2)
