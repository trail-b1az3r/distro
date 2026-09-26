"""Hardware detection from sysfs, procfs and udev data.

Entry point: :func:`detect`, which returns a :class:`HardwareReport`.
"""

from .report import HardwareReport, detect

__all__ = ["HardwareReport", "detect"]
