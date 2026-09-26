"""Choose the acceleration backend for local AI from the detected hardware.

Nothing is hard-coded to a vendor: the backend follows from the GPU manager's
plan (which driver stack drives which GPU) and falls back to the CPU.
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from typing import Any

from .. import paths
from ..gpu.plan import GpuPlan
from ..hardware.report import HardwareReport

DESCRIPTIONS = {
    "cuda": "NVIDIA CUDA",
    "cuda_legacy": "NVIDIA CUDA 12.6 (Maxwell/Pascal/Volta)",
    "rocm": "AMD ROCm (HIP)",
    "xpu": "Intel oneAPI (XPU)",
    "vulkan": "Vulkan (llama.cpp); PyTorch on CPU",
    "cpu": "CPU only",
}


@dataclass
class Backend:
    name: str
    description: str
    torch_index: str
    llama_package: str
    gpu: str
    env: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _toml(*parts: str) -> dict[str, Any]:
    with paths.data(*parts).open("rb") as fh:
        return tomllib.load(fh)


def select(report: HardwareReport, plan: GpuPlan, override: str = "") -> Backend:
    hyp = _toml("ai", "hypernix", "hypernix.toml")
    runtime = _toml("ai", "runtime", "llama-server.toml")["packages"]
    name = override or plan.compute_backend
    gpu = report.best_compute_gpu
    if name == "cuda" and gpu is not None:
        stack = next((c.stack for c in plan.choices if c.slot == gpu.slot), "")
        if stack == "nvidia-580xx":
            name = "cuda_legacy"
    if name not in DESCRIPTIONS:
        raise ValueError(f"unknown backend {name!r}; choose one of {', '.join(DESCRIPTIONS)}")
    env: dict[str, str] = {}
    if name == "rocm" and "HSA_OVERRIDE_GFX_VERSION" in plan.env:
        env["HSA_OVERRIDE_GFX_VERSION"] = plan.env["HSA_OVERRIDE_GFX_VERSION"]
    torch_key = name if name in hyp["torch_index"] else "cpu"
    # llama.cpp: Vulkan is the prebuilt default on every GPU; CPU-only
    # machines get the plain build.
    llama = runtime["cpu"] if name == "cpu" else runtime[runtime.get("default_gpu", "vulkan")]
    return Backend(
        name=name,
        description=DESCRIPTIONS[name],
        torch_index=hyp["torch_index"][torch_key],
        llama_package=llama,
        gpu=gpu.display_name if gpu and name != "cpu" else "",
        env=env,
    )
