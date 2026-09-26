"""JSON Schema of the installer configuration (installer/schema.json).

Generated from the dataclasses in :mod:`distrokit.installer.config`, so it
cannot drift from what the installer accepts; the test suite checks that the
committed file is current.

    python3 -m distrokit.installer.schema > installer/schema.json
"""

from __future__ import annotations

import json
import sys
import typing
from dataclasses import MISSING, fields, is_dataclass
from typing import Any

from . import config as cfg

ENUMS: dict[tuple[str, str], list[str]] = {
    ("DiskConfig", "mode"): ["erase", "free-space", "manual"],
    ("DiskConfig", "filesystem"): ["btrfs", "ext4"],
    ("DiskConfig", "swap"): ["zram", "partition", "file", "none"],
    ("MountSpec", "mountpoint"): ["/", "/home", "/boot", "/efi", "swap"],
    ("MountSpec", "filesystem"): ["", "btrfs", "ext4", "xfs", "vfat", "swap"],
    ("UserConfig", "shell"): ["bash", "fish"],
    ("AiConfig", "download"): ["now", "first-boot"],
    ("AiConfig", "backend"): ["", "cuda", "cuda_legacy", "rocm", "xpu", "vulkan", "cpu"],
    ("InstallConfig", "bootloader"): ["auto", "systemd-boot", "grub"],
    ("InstallConfig", "secure_boot"): ["off", "sbctl"],
}
DESCRIPTIONS: dict[tuple[str, str], str] = {
    ("InstallConfig", "profile"): "minimal | standard | developer | ai (profiles/*.toml)",
    ("InstallConfig", "features"): "Overrides of the profile's features (profiles/features.toml), e.g. {\"office\": false}",
    ("InstallConfig", "gpu_overrides"): "PCI slot -> driver stack (hardware/gpu/drivers.toml), e.g. {\"0000:01:00.0\": \"nouveau\"}",
    ("InstallConfig", "kernels"): "Kernel packages: linux, linux-lts, linux-zen, ...",
    ("InstallConfig", "kernel_params"): "Extra kernel parameters (the root file system is set by the installer)",
    ("InstallConfig", "offline"): "Use only the ISO's offline repository",
    ("UserConfig", "password"): "May be empty in the file and given as INSTALL_USER_PASSWORD",
    ("UserConfig", "root_password"): "Empty: root login disabled (sudo only). Or INSTALL_ROOT_PASSWORD",
    ("DiskConfig", "passphrase"): "LUKS passphrase (8+ characters). May be given as INSTALL_DISK_PASSPHRASE",
    ("DiskConfig", "disk"): "Whole disk, e.g. /dev/nvme0n1 (erase and free-space modes)",
    ("DiskConfig", "mounts"): "Manual mode: existing partitions and where to mount them",
    ("AiConfig", "model"): "Catalogue model id (ai/models/catalog.toml), or empty",
    ("AiConfig", "custom_model"): "CustomModel fields: source huggingface|url|path|hypernix, repo, file, url, path, ...",
}


def _type_schema(tp: Any) -> dict[str, Any]:
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if is_dataclass(tp):
        return {"$ref": f"#/$defs/{tp.__name__}"}
    if origin in (typing.Union, getattr(__import__("types"), "UnionType", None)):
        return {"anyOf": [_type_schema(a) for a in args]}
    if origin is list:
        return {"type": "array", "items": _type_schema(args[0]) if args else {}}
    if origin is dict:
        return {"type": "object", "additionalProperties": _type_schema(args[1]) if len(args) == 2 else {}}
    return {bool: {"type": "boolean"}, int: {"type": "integer"}, str: {"type": "string"},
            type(None): {"type": "null"}}.get(tp, {})


def _object(klass) -> dict[str, Any]:
    hints = typing.get_type_hints(klass)
    props: dict[str, Any] = {}
    for f in fields(klass):
        s = _type_schema(hints[f.name])
        if (klass.__name__, f.name) in ENUMS:
            s["enum"] = ENUMS[(klass.__name__, f.name)]
        if (klass.__name__, f.name) in DESCRIPTIONS:
            s["description"] = DESCRIPTIONS[(klass.__name__, f.name)]
        if f.default is not MISSING and not is_dataclass(hints[f.name]):
            s["default"] = f.default
        elif f.default_factory is not MISSING and not is_dataclass(hints[f.name]):  # type: ignore[misc]
            s["default"] = f.default_factory()  # type: ignore[misc]
        props[f.name] = s
    required = [f.name for f in fields(klass) if f.default is MISSING and f.default_factory is MISSING]  # type: ignore[misc]
    out: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": props}
    if required:
        out["required"] = required
    return out


def schema() -> dict[str, Any]:
    defs = {k.__name__: _object(k) for k in (cfg.UserConfig, cfg.DiskConfig, cfg.MountSpec, cfg.AiConfig)}
    root = _object(cfg.InstallConfig)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Installer configuration",
        "description": "Unattended installation: <id>-installer --config FILE (see docs/installation.md).",
        **root,
        "$defs": defs,
    }


def main() -> int:
    sys.stdout.write(json.dumps(schema(), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
