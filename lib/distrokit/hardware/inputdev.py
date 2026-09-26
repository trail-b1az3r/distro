"""Input devices: touchpads, touchscreens, pens and keyboards.

udev's classification (``ID_INPUT_TOUCHPAD`` etc. in ``/run/udev/data``) is
used when present. Without udev data (a bare chroot, a container) the kernel's
input properties from ``/proc/bus/input/devices`` are used instead:
``INPUT_PROP_POINTER`` marks indirect devices such as touchpads and
``INPUT_PROP_DIRECT`` marks devices that sit on a display.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .sysroot import SysRoot

INPUT_PROP_POINTER = 0x1
INPUT_PROP_DIRECT = 0x2


@dataclass
class InputDevice:
    name: str
    kind: str  # touchpad | touchscreen | pen | keyboard | mouse | other
    bus: str
    event: str

    def to_dict(self) -> dict:
        return asdict(self)


_BUS = {"0003": "usb", "0011": "ps2", "0018": "i2c", "0019": "host", "0005": "bluetooth", "001c": "spi", "0006": "virtual"}


def _udev_props(sysroot: SysRoot, event: str) -> dict[str, str]:
    m = re.match(r"event(\d+)$", event)
    if not m:
        return {}
    dev = sysroot.read(f"/sys/class/input/{event}/dev")
    candidates = [f"/run/udev/data/c{dev}"] if dev else []
    candidates.append(f"/run/udev/data/c13:{64 + int(m.group(1))}")
    for cand in candidates:
        text = sysroot.read(cand)
        if text:
            props = {}
            for line in text.splitlines():
                if line.startswith("E:") and "=" in line:
                    k, v = line[2:].split("=", 1)
                    props[k] = v
            return props
    return {}


def _classify(name: str, props_bits: int, handlers: str, udev: dict[str, str]) -> str:
    if udev:
        if udev.get("ID_INPUT_TOUCHSCREEN") == "1":
            return "touchscreen"
        if udev.get("ID_INPUT_TABLET") == "1":
            return "pen"
        if udev.get("ID_INPUT_TOUCHPAD") == "1":
            return "touchpad"
        if udev.get("ID_INPUT_KEYBOARD") == "1":
            return "keyboard"
        if udev.get("ID_INPUT_MOUSE") == "1":
            return "mouse"
        return "other"
    lname = name.lower()
    if re.search(r"\b(pen|stylus)\b", lname):
        return "pen"
    if props_bits & INPUT_PROP_DIRECT or "touchscreen" in lname:
        return "touchscreen"
    if props_bits & INPUT_PROP_POINTER or re.search(r"touch ?pad|trackpad|clickpad", lname):
        return "touchpad"
    if "kbd" in handlers.split() or "keyboard" in lname:
        return "keyboard"
    if "mouse" in handlers or "mouse" in lname:
        return "mouse"
    return "other"


def detect_input(sysroot: SysRoot) -> list[InputDevice]:
    text = sysroot.read("/proc/bus/input/devices")
    devices = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        name = bus = handlers = ""
        prop = 0
        for line in block.splitlines():
            if line.startswith("N: Name="):
                name = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("I: "):
                m = re.search(r"Bus=([0-9a-fA-F]{4})", line)
                bus = _BUS.get(m.group(1).lower(), m.group(1)) if m else ""
            elif line.startswith("H: Handlers="):
                handlers = line.split("=", 1)[1].strip()
            elif line.startswith("B: PROP="):
                try:
                    prop = int(line.split("=", 1)[1].split()[-1], 16)
                except ValueError:
                    prop = 0
        event = next((h for h in handlers.split() if h.startswith("event")), "")
        kind = _classify(name, prop, handlers, _udev_props(sysroot, event) if event else {})
        devices.append(InputDevice(name=name, kind=kind, bus=bus, event=event))
    return devices
