"""Locales, keyboard layouts and time zones for the installer, read from the
live system's own data files (glibc, xkeyboard-config, tzdata)."""

from __future__ import annotations

import gzip
import re
from dataclasses import dataclass
from pathlib import Path

# xkb layout -> console keymap (kbd). Layouts not listed map to the same name
# when kbd has it, and to "us" otherwise.
CONSOLE_KEYMAP = {
    "us": "us", "gb": "uk", "de": "de-latin1", "fr": "fr-latin1", "es": "es", "it": "it", "pt": "pt-latin1",
    "br": "br-abnt2", "ru": "ru", "se": "sv-latin1", "no": "no-latin1", "dk": "dk-latin1", "fi": "fi",
    "pl": "pl2", "cz": "cz-qwertz", "sk": "sk-qwertz", "hu": "hu", "nl": "nl", "be": "be-latin1", "ch": "de_CH-latin1",
    "jp": "jp106", "tr": "trq", "gr": "gr", "ua": "ua", "latam": "la-latin1", "ca": "cf", "ie": "uk", "is": "is-latin1",
    "ro": "ro", "si": "slovene", "hr": "croat", "rs": "sr-latin", "bg": "bg_bds-utf8", "il": "us", "ara": "us",
    "kr": "us", "cn": "us", "tw": "us", "in": "us", "th": "us", "vn": "us", "ee": "et", "lt": "lt", "lv": "lv",
}
VARIANT_KEYMAP = {("us", "dvorak"): "dvorak", ("us", "colemak"): "colemak", ("fr", "bepo"): "fr-bepo",
                  ("de", "nodeadkeys"): "de-latin1-nodeadkeys"}

FALLBACK_LAYOUTS = [
    ("us", "English (US)"), ("gb", "English (UK)"), ("de", "German"), ("fr", "French"), ("es", "Spanish"),
    ("it", "Italian"), ("pt", "Portuguese"), ("br", "Portuguese (Brazil)"), ("ru", "Russian"), ("pl", "Polish"),
    ("nl", "Dutch"), ("se", "Swedish"), ("no", "Norwegian"), ("dk", "Danish"), ("fi", "Finnish"), ("ch", "German (Switzerland)"),
    ("cz", "Czech"), ("hu", "Hungarian"), ("tr", "Turkish"), ("jp", "Japanese"), ("kr", "Korean"), ("ua", "Ukrainian"),
    ("latam", "Spanish (Latin American)"), ("ca", "French (Canada)"),
]


@dataclass
class Layout:
    code: str
    name: str
    variants: list[tuple[str, str]]


def keyboard_layouts(root: Path = Path("/")) -> list[Layout]:
    base = root / "usr" / "share" / "X11" / "xkb" / "rules" / "base.lst"
    if not base.is_file():
        return [Layout(c, n, []) for c, n in FALLBACK_LAYOUTS]
    layouts: dict[str, Layout] = {}
    section = ""
    for line in base.read_text(errors="replace").splitlines():
        if line.startswith("! "):
            section = line[2:].strip()
            continue
        if not line.strip():
            continue
        if section == "layout":
            code, name = line.split(None, 1)
            layouts[code] = Layout(code, name.strip(), [])
        elif section == "variant":
            m = re.match(r"\s*(\S+)\s+(\S+):\s*(.*)", line)
            if m and m.group(2) in layouts:
                layouts[m.group(2)].variants.append((m.group(1), m.group(3).strip()))
    return sorted(layouts.values(), key=lambda lay: lay.name.lower())


def console_keymap(layout: str, variant: str = "", root: Path = Path("/")) -> str:
    if (layout, variant) in VARIANT_KEYMAP:
        return VARIANT_KEYMAP[(layout, variant)]
    km = CONSOLE_KEYMAP.get(layout, layout)
    kbd = root / "usr" / "share" / "kbd" / "keymaps"
    if kbd.is_dir() and not any(kbd.rglob(f"{km}.map.gz")):
        return "us"
    return km


def locales(root: Path = Path("/")) -> list[str]:
    path = root / "usr" / "share" / "i18n" / "SUPPORTED"
    if not path.is_file():
        return ["en_US.UTF-8", "en_GB.UTF-8", "de_DE.UTF-8", "fr_FR.UTF-8", "es_ES.UTF-8", "it_IT.UTF-8",
                "pt_BR.UTF-8", "ru_RU.UTF-8", "ja_JP.UTF-8", "zh_CN.UTF-8"]
    out = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == "UTF-8":
            out.append(parts[0])
    return out


def timezones(root: Path = Path("/")) -> list[str]:
    from .config import available_timezones

    zones = sorted(z for z in available_timezones(root) if "/" in z or z == "UTC")
    return zones or ["UTC"]


def locale_gen_line(locale: str) -> str:
    """'de_DE.UTF-8' -> 'de_DE.UTF-8 UTF-8' as written in /etc/locale.gen."""
    return f"{locale} UTF-8" if locale.endswith(".UTF-8") else locale


def read_gz_or_plain(path: Path) -> str:
    if path.suffix == ".gz":
        return gzip.decompress(path.read_bytes()).decode(errors="replace")
    return path.read_text(errors="replace")
