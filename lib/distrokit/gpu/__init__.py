"""The GPU manager: detect GPUs, plan a driver configuration, apply it and
report its status. Used by the installer and by ``<cli> gpu``."""

from .plan import GpuPlan, build_plan, recommend

__all__ = ["GpuPlan", "build_plan", "recommend"]
