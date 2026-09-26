"""Connected displays from DRM connectors and their EDID."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .sysroot import SysRoot

DRM = "/sys/class/drm"
INTERNAL_TYPES = ("eDP", "LVDS", "DSI")


@dataclass
class Edid:
    manufacturer: str
    product_code: int
    name: str
    width_mm: int
    height_mm: int
    preferred_width: int
    preferred_height: int


def parse_edid(data: bytes) -> Edid | None:
    """Parse the base EDID block. Returns None for anything that isn't EDID 1.x."""
    if len(data) < 128 or data[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return None
    word = (data[8] << 8) | data[9]
    manufacturer = "".join(chr(((word >> shift) & 0x1F) + 64) for shift in (10, 5, 0))
    product = data[10] | (data[11] << 8)
    width_mm = data[21] * 10
    height_mm = data[22] * 10
    name = ""
    pref_w = pref_h = 0
    for offset in (54, 72, 90, 108):
        desc = data[offset : offset + 18]
        if desc[0] or desc[1]:
            # Detailed timing descriptor; the first one is the preferred mode.
            if not pref_w:
                pref_w = desc[2] | ((desc[4] & 0xF0) << 4)
                pref_h = desc[5] | ((desc[7] & 0xF0) << 4)
                w_mm = desc[12] | ((desc[14] & 0xF0) << 4)
                h_mm = desc[13] | ((desc[14] & 0x0F) << 8)
                if w_mm and h_mm:
                    width_mm, height_mm = w_mm, h_mm
        elif desc[3] == 0xFC:
            name = desc[5:18].split(b"\x0a")[0].decode("ascii", "replace").strip()
    return Edid(manufacturer, product, name, width_mm, height_mm, pref_w, pref_h)


# Scales Hyprland accepts cleanly are those that divide the resolution into
# whole logical pixels.
_SCALES = (1.0, 1.25, 1.333333, 1.5, 1.6, 1.666667, 1.75, 2.0, 2.4, 2.5, 3.0)


def recommend_scale(width: int, height: int, width_mm: int, internal: bool) -> float:
    if not (width and height and width_mm) or width_mm < 50:
        return 1.0
    dpi = width / (width_mm / 25.4)
    # Laptop panels are viewed from closer, so they need less scaling per DPI.
    target = dpi / (110.0 if internal else 96.0)
    if target < 1.15:
        return 1.0
    best = 1.0
    best_err = abs(target - 1.0)
    for scale in _SCALES:
        lw, lh = width / scale, height / scale
        if abs(lw - round(lw)) > 1e-3 or abs(lh - round(lh)) > 1e-3:
            continue
        err = abs(target - scale)
        if err < best_err - 1e-9:
            best, best_err = scale, err
    return round(best, 6)


@dataclass
class Display:
    connector: str  # Hyprland output name, e.g. "eDP-1", "DP-2", "HDMI-A-1"
    card: str
    pci_slot: str
    internal: bool
    width: int
    height: int
    width_mm: int
    height_mm: int
    manufacturer: str
    name: str
    recommended_scale: float

    @property
    def diagonal_inches(self) -> float:
        if not (self.width_mm and self.height_mm):
            return 0.0
        return round(((self.width_mm**2 + self.height_mm**2) ** 0.5) / 25.4, 1)

    @property
    def dpi(self) -> int:
        if not self.width_mm:
            return 0
        return round(self.width / (self.width_mm / 25.4))

    @property
    def hidpi(self) -> bool:
        return self.recommended_scale > 1.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["diagonal_inches"] = self.diagonal_inches
        d["dpi"] = self.dpi
        d["hidpi"] = self.hidpi
        d["resolution"] = f"{self.width} × {self.height}" if self.width else "unknown"
        return d


def detect_displays(sysroot: SysRoot) -> list[Display]:
    displays = []
    for entry in sysroot.listdir(DRM):
        if "-" not in entry or not entry.startswith("card"):
            continue
        base = f"{DRM}/{entry}"
        if sysroot.read(f"{base}/status") != "connected":
            continue
        card, connector = entry.split("-", 1)
        ctype = connector.rsplit("-", 1)[0]
        internal = ctype in INTERNAL_TYPES
        edid = parse_edid(sysroot.read_bytes(f"{base}/edid"))
        modes = sysroot.read(f"{base}/modes").splitlines()
        width = height = 0
        if edid and edid.preferred_width:
            width, height = edid.preferred_width, edid.preferred_height
        elif modes:
            try:
                w, h = modes[0].split("x", 1)
                width, height = int(w), int(h.rstrip("i"))
            except ValueError:
                pass
        width_mm = edid.width_mm if edid else 0
        height_mm = edid.height_mm if edid else 0
        pci_slot = sysroot.realpath(f"{DRM}/{card}/device").rsplit("/", 1)[-1]
        displays.append(
            Display(
                connector=connector,
                card=card,
                pci_slot=pci_slot,
                internal=internal,
                width=width,
                height=height,
                width_mm=width_mm,
                height_mm=height_mm,
                manufacturer=edid.manufacturer if edid else "",
                name=(edid.name if edid else "") or ("Built-in display" if internal else connector),
                recommended_scale=recommend_scale(width, height, width_mm, internal),
            )
        )
    displays.sort(key=lambda d: (not d.internal, d.connector))
    return displays
