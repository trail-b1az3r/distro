"""Read-only access to /sys, /proc, /run and /dev under a configurable root.

Detection code never opens absolute paths directly; it goes through a
:class:`SysRoot`. On a real machine the root is ``/``; in tests it is a
directory populated from a fixture, which is how detection logic is tested
against recorded hardware without mocking.
"""

from __future__ import annotations

import os
from pathlib import Path


class SysRoot:
    def __init__(self, root: str | Path = "/"):
        self.root = Path(root)

    @property
    def is_live_root(self) -> bool:
        return str(self.root) == "/"

    def path(self, absolute: str) -> Path:
        return self.root / absolute.lstrip("/")

    def exists(self, absolute: str) -> bool:
        return self.path(absolute).exists()

    def is_dir(self, absolute: str) -> bool:
        return self.path(absolute).is_dir()

    def read(self, absolute: str, default: str = "") -> str:
        try:
            return self.path(absolute).read_text(encoding="utf-8", errors="replace").strip()
        except (OSError, ValueError):
            return default

    def read_bytes(self, absolute: str) -> bytes:
        try:
            return self.path(absolute).read_bytes()
        except OSError:
            return b""

    def read_int(self, absolute: str, default: int | None = None, base: int = 0) -> int | None:
        raw = self.read(absolute)
        if not raw:
            return default
        try:
            return int(raw.split()[0], base)
        except ValueError:
            return default

    def listdir(self, absolute: str) -> list[str]:
        try:
            return sorted(os.listdir(self.path(absolute)))
        except OSError:
            return []

    def readlink_name(self, absolute: str) -> str:
        """Basename of a symlink's target (e.g. the driver bound to a device)."""
        try:
            return os.path.basename(os.readlink(self.path(absolute)))
        except OSError:
            return ""

    def realpath(self, absolute: str) -> str:
        """Resolve a sysfs symlink, returned relative to the root (as absolute path)."""
        p = self.path(absolute)
        try:
            resolved = Path(os.path.realpath(p))
        except OSError:
            return ""
        try:
            return "/" + str(resolved.relative_to(self.root.resolve()))
        except ValueError:
            return str(resolved)
