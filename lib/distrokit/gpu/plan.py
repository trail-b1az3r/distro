"""Decide the graphics driver configuration for a machine.

``build_plan(report)`` looks at every GPU in the hardware report, picks a
driver stack for each (``hardware/gpu/drivers.toml``), and merges them into a
single :class:`GpuPlan`: packages, kernel parameters, initramfs modules,
modprobe options, udev rules, services and session environment.

The plan is pure data. :mod:`distrokit.gpu.apply` carries it out, so the plan
can be shown to the user (and tested) before anything changes.
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .. import paths
from ..branding import Branding, load as load_branding
from ..hardware.graphics import Gpu
from ..hardware.report import HardwareReport

TURING_PLUS = {"turing", "ampere", "ada", "hopper", "blackwell", "unknown"}
AMPERE_PLUS = {"ampere", "ada", "blackwell"}
INTEL_COMPUTE_FAMILIES = {"xe-lp", "xe-lpg", "xe-hpg", "xe2"}


@lru_cache(maxsize=4)
def _drivers(data_root: str) -> dict[str, Any]:
    with (Path(data_root) / "hardware" / "gpu" / "drivers.toml").open("rb") as fh:
        return tomllib.load(fh)


def drivers() -> dict[str, Any]:
    return _drivers(str(paths.DATA_ROOT))


def stack(stack_id: str) -> dict[str, Any]:
    return drivers()["stack"][stack_id]


def stacks_for_vendor(vendor: str) -> list[str]:
    target = "virtual" if vendor not in ("nvidia", "amd", "intel") else vendor
    return [sid for sid, s in drivers()["stack"].items() if s["vendor"] == target]


@dataclass
class GpuChoice:
    slot: str
    display_name: str
    vendor: str
    architecture: str
    stack: str
    recommended: str
    reason: str
    role: str  # primary | offload | secondary | only

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        s = stack(self.stack)
        d["label"] = s["label"]
        d["vulkan"] = s.get("vulkan", "")
        d["cuda"] = s.get("cuda", "")
        d["wayland"] = s.get("wayland", "")
        d["vaapi"] = s.get("vaapi", "")
        d["overridden"] = self.stack != self.recommended
        return d


@dataclass
class GpuPlan:
    mode: str  # none | single | hybrid | multi
    choices: list[GpuChoice] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)
    aur_packages: list[str] = field(default_factory=list)
    compute_packages: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    kernel_params: list[str] = field(default_factory=list)
    initramfs_modules: list[str] = field(default_factory=list)
    drop_kms_hook: bool = False
    modprobe: list[str] = field(default_factory=list)
    udev_rules: str = ""
    services: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    compute_backend: str = "cpu"  # cuda | rocm | vulkan | xpu | cpu

    @property
    def all_packages(self) -> list[str]:
        out: list[str] = []
        for p in self.packages + self.aur_packages + self.compute_packages:
            if p not in out:
                out.append(p)
        return out

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["choices"] = [c.to_dict() for c in self.choices]
        d["all_packages"] = self.all_packages
        return d

    def describe(self) -> list[str]:
        lines = []
        for c in self.choices:
            tag = f" [{c.role}]" if c.role not in ("only",) else ""
            override = " (your choice; recommended: " + stack(c.recommended)["label"] + ")" if c.stack != c.recommended else ""
            lines.append(f"{c.display_name}{tag}: {stack(c.stack)['label']}{override}")
        if self.mode == "hybrid":
            lines.append("Hybrid graphics: the integrated GPU drives the display; the discrete GPU renders on demand.")
        return lines + self.notes


def recommend(gpu: Gpu) -> tuple[str, str]:
    """(stack id, reason) for one GPU."""
    if gpu.vendor == "nvidia":
        if gpu.driver_branch == "open":
            return "nvidia-open", f"{gpu.architecture.capitalize()} GPU: NVIDIA's open kernel modules are the supported driver."
        if gpu.driver_branch == "legacy580":
            return "nvidia-580xx", (
                f"{gpu.architecture.capitalize()} GPU: current NVIDIA drivers dropped it; the 580 series is the last that supports it."
            )
        return "nouveau", f"{gpu.architecture.capitalize()} GPU: no NVIDIA driver with Wayland support exists for it, so the open-source driver is used."
    if gpu.vendor == "amd":
        if gpu.driver_branch == "radeon":
            return "radeon", "Pre-GCN Radeon: the radeon driver with Mesa OpenGL."
        return "amdgpu", "AMDGPU with Mesa: the upstream, open-source stack. No proprietary software needed."
    if gpu.vendor == "intel":
        if gpu.kind == "discrete":
            return "intel-discrete", "Intel Arc: Mesa with the oneVPL media runtime."
        if gpu.extras.get("legacy_vaapi"):
            return "intel-legacy", "Older Intel graphics: Mesa with the i965 VA-API driver."
        return "intel", "Intel graphics: Mesa with the iHD VA-API driver."
    return "virtual", "Virtual or unknown GPU: Mesa's generic drivers."


def _add(target: list[str], items: list[str] | tuple[str, ...]) -> None:
    for item in items:
        if item and item not in target:
            target.append(item)


def build_plan(
    report: HardwareReport,
    *,
    kernels: list[str] | None = None,
    compute: bool = False,
    multilib: bool = True,
    overrides: dict[str, str] | None = None,
    branding: Branding | None = None,
) -> GpuPlan:
    branding = branding or load_branding()
    kernels = kernels or ["linux"]
    overrides = overrides or {}
    data = drivers()
    topo = report.topology
    plan = GpuPlan(mode=topo.mode)
    _add(plan.packages, data["common"]["packages"])
    if multilib:
        _add(plan.packages, data["common"]["packages_32bit"])

    chosen_stacks: list[str] = []
    for gpu in report.gpus:
        rec, reason = recommend(gpu)
        chosen = overrides.get(gpu.slot, rec)
        if chosen not in data["stack"]:
            raise ValueError(f"unknown driver stack {chosen!r} for {gpu.slot}")
        if data["stack"][chosen]["vendor"] not in (gpu.vendor, "virtual"):
            raise ValueError(f"stack {chosen} does not drive {gpu.vendor} GPUs")
        if topo.mode in ("single", "none"):
            role = "only"
        elif topo.primary and gpu.slot == topo.primary.slot:
            role = "primary"
        elif topo.offload and gpu.slot == topo.offload.slot:
            role = "offload"
        else:
            role = "secondary"
        plan.choices.append(GpuChoice(gpu.slot, gpu.display_name, gpu.vendor, gpu.architecture, chosen, rec, reason, role))
        if chosen not in chosen_stacks:
            chosen_stacks.append(chosen)
        _add(plan.kernel_params, gpu.extras.get("kernel_params", []))

    for sid in chosen_stacks:
        s = data["stack"][sid]
        pkgs = list(s.get("packages", []))
        if s.get("dkms") and s.get("prebuilt"):
            prebuilt = s["prebuilt"]
            if len(kernels) == 1 and kernels[0] in prebuilt:
                pkgs = [prebuilt[kernels[0]] if p.endswith("-dkms") else p for p in pkgs]
        if s.get("dkms") and any(p.endswith("-dkms") for p in pkgs):
            _add(pkgs, [f"{k}-headers" for k in kernels])
        if multilib:
            pkgs += s.get("packages_32bit", [])
        target = plan.aur_packages if s.get("source") == "aur" else plan.packages
        # Kernel headers always come from the repositories.
        _add(target, [p for p in pkgs if not p.endswith("-headers")])
        _add(plan.packages, [p for p in pkgs if p.endswith("-headers")])
        _add(plan.kernel_params, s.get("kernel_params", []))
        _add(plan.initramfs_modules, s.get("initramfs_modules", []))
        _add(plan.modprobe, s.get("modprobe", []))
        _add(plan.services, s.get("services", []))
        plan.drop_kms_hook = plan.drop_kms_hook or bool(s.get("drop_kms_hook"))

    # Conflicts: anything another stack of the same vendor would install and
    # this plan does not use. Removing them keeps a switched system clean.
    wanted = set(plan.all_packages)
    for sid in chosen_stacks:
        _add(plan.conflicts, [c for c in data["stack"][sid].get("conflicts", []) if c not in wanted])
    vendors = {g.vendor for g in report.gpus}
    if "nvidia" not in vendors:
        # No NVIDIA hardware: NVIDIA driver packages have no business here.
        for sid in ("nvidia-open", "nvidia-580xx"):
            s = data["stack"][sid]
            candidates = list(s["packages"]) + list(s.get("packages_32bit", [])) + list(s.get("prebuilt", {}).values())
            # egl-wayland is harmless without NVIDIA and other packages may use it.
            _add(plan.conflicts, [p for p in candidates if p not in wanted and p != "egl-wayland"])
        _add(plan.conflicts, [p for p in ("nvidia-prime", "cudnn", "cuda") if p not in wanted])

    # Session environment and hybrid setup.
    primary = next((c for c in plan.choices if c.role in ("only", "primary")), None)
    offload = next((c for c in plan.choices if c.role == "offload"), None)
    if primary and not offload:
        _apply_env(plan, data["stack"][primary.stack].get("env_primary", {}))
    if topo.mode == "hybrid" and topo.primary and topo.offload:
        plan.env["AQ_DRM_DEVICES"] = f"/dev/dri/{branding.id}-primary-card:/dev/dri/{branding.id}-offload-card"
        plan.udev_rules += _drm_symlink_rules(branding, topo.primary.slot, topo.offload.slot)
        if offload and offload.vendor == "nvidia" and offload.stack.startswith("nvidia-"):
            hyb = data["hybrid"]["nvidia"]
            _add(plan.packages, hyb["packages"])
            if topo.offload.architecture in TURING_PLUS:
                _add(plan.modprobe, hyb["modprobe_turing_plus"])
                plan.udev_rules += hyb["udev_turing_plus"].strip() + "\n"
            if topo.offload.architecture in AMPERE_PLUS and report.chassis.portable:
                _add(plan.services, hyb["services"])
            plan.notes.append("Run a program on the NVIDIA GPU with: prime-run <program>")
        elif offload:
            plan.notes.append("Run a program on the discrete GPU with: DRI_PRIME=1 <program>")
    elif topo.mode == "multi" and topo.primary:
        plan.udev_rules += _drm_symlink_rules(branding, topo.primary.slot, None)
        plan.env["AQ_DRM_DEVICES"] = f"/dev/dri/{branding.id}-primary-card"
        # Keep the other GPUs usable for rendering and compute; the compositor
        # just starts on the one with the monitors.

    # Compute toolkits.
    best = report.best_compute_gpu
    plan.compute_backend = compute_backend(best, next((c.stack for c in plan.choices if best and c.slot == best.slot), ""))
    if compute and best:
        best_stack = next(c.stack for c in plan.choices if c.slot == best.slot)
        s = data["stack"][best_stack]
        comp = list(s.get("compute", []))
        if best.vendor == "amd" and best.extras.get("rocm", "none") == "none":
            comp = []
            plan.notes.append(f"{best.display_name} is not supported by ROCm; local AI will use Vulkan acceleration.")
        if best.vendor == "amd" and best.extras.get("hsa_override_gfx_version"):
            plan.env["HSA_OVERRIDE_GFX_VERSION"] = best.extras["hsa_override_gfx_version"]
        if best.vendor == "intel" and best.architecture not in INTEL_COMPUTE_FAMILIES:
            comp = []
        if best.vendor == "nvidia" and best_stack == "nvidia-580xx":
            plan.notes.append("CUDA 13 does not support this GPU; AI tools use PyTorch's CUDA 12.6 runtime instead.")
        _add(plan.compute_packages, comp)

    if any(c.stack == "nouveau" and c.vendor == "nvidia" for c in plan.choices):
        g = next(c for c in plan.choices if c.stack == "nouveau")
        if g.architecture in ("kepler", "fermi", "tesla", "curie"):
            plan.notes.append(f"{g.display_name}: NVK Vulkan needs Maxwell or newer; OpenGL works.")
    return plan


def _apply_env(plan: GpuPlan, env: dict[str, str]) -> None:
    for k, v in env.items():
        plan.env.setdefault(k, v)


def _drm_symlink_rules(branding: Branding, primary: str, offload: str | None) -> str:
    rules = [f'# Stable names for the compositor (see AQ_DRM_DEVICES in /etc/{branding.id}/gpu.env)']
    rules.append(f'KERNEL=="card*", SUBSYSTEM=="drm", KERNELS=="{primary}", SYMLINK+="dri/{branding.id}-primary-card"')
    if offload:
        rules.append(f'KERNEL=="card*", SUBSYSTEM=="drm", KERNELS=="{offload}", SYMLINK+="dri/{branding.id}-offload-card"')
    return "\n".join(rules) + "\n"


def compute_backend(gpu: Gpu | None, stack_id: str) -> str:
    """The acceleration backend local AI tools should use on this GPU."""
    if gpu is None:
        return "cpu"
    if gpu.vendor == "nvidia" and stack_id.startswith("nvidia-"):
        return "cuda"
    if gpu.vendor == "amd" and stack_id == "amdgpu":
        return "rocm" if gpu.extras.get("rocm", "none") != "none" else "vulkan"
    if gpu.vendor == "intel" and gpu.architecture in INTEL_COMPUTE_FAMILIES:
        return "xpu" if gpu.kind == "discrete" or gpu.architecture in ("xe-lpg", "xe2") else "vulkan"
    if gpu.vendor in ("nvidia", "intel", "amd"):
        return "vulkan" if stack(stack_id).get("vulkan", "no").startswith("yes") else "cpu"
    return "cpu"
