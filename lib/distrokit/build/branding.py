"""Generate every branded asset from ``distro.conf``.

    python3 -m distrokit.build.branding [--quick]

* ``*.in`` templates under ``branding/`` are rendered into
  ``branding/generated/`` (logo, application icons, theme files).
* SVGs are rasterised (rsvg-convert, or Qt's SVG renderer when available).
* Wallpapers, the boot splash, the GRUB and SDDM backgrounds and the
  syslinux splash are drawn procedurally with Pillow and NumPy, so renaming or
  recolouring the distribution regenerates them all. Nothing is copied from
  another distribution's artwork.

``--quick`` renders only the vector files (used by tests and development).
Outputs are build products (see .gitignore); ``build.sh`` runs this first.
"""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
from pathlib import Path

from .. import paths
from ..branding import Branding, load as load_branding

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def render_templates(root: Path, out_dir: Path, b: Branding) -> list[Path]:
    """Render branding/**/X.in to branding/generated/**/X."""
    out = []
    for tmpl in sorted(root.rglob("*.in")):
        rel = tmpl.relative_to(root)
        if rel.parts[0] == "generated":
            continue
        target = out_dir / rel.with_suffix("")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(b.render(tmpl.read_text()))
        out.append(target)
    return out


def rasterise(svg: Path, png: Path, width: int, height: int | None = None) -> None:
    height = height or width
    png.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-w", str(width), "-h", str(height), "-o", str(png), str(svg)], check=True)
        return
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication, QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer
    except ImportError as exc:
        raise RuntimeError("rasterising SVG needs rsvg-convert (librsvg) or PySide6") from exc
    QGuiApplication.instance() or QGuiApplication(["branding", "-platform", "offscreen"])
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    QSvgRenderer(str(svg)).render(painter)
    painter.end()
    image.save(str(png))


# ---------------------------------------------------------------------------
# Procedural artwork
# ---------------------------------------------------------------------------


def _np():
    import numpy as np  # noqa: PLC0415 - optional dependency of the build only

    return np


def aurora(b: Branding, width: int, height: int, *, light: bool = False, seed: int = 7, variant: str = "aurora"):
    """Flowing ribbons of the brand colours over a deep background."""
    np = _np()
    from PIL import Image

    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    u, v = x / width, y / height
    bg = np.array(hex_rgb(b["BRAND_BG"]), np.float32) / 255
    c1 = np.array(hex_rgb(b["BRAND_ACCENT"]), np.float32) / 255
    c2 = np.array(hex_rgb(b["BRAND_ACCENT_2"]), np.float32) / 255
    if light:
        bg = np.array([0.93, 0.94, 0.98], np.float32) * 0.9 + c1 * 0.1
    img = np.ones((height, width, 3), np.float32) * bg
    # Vertical vignette gradient.
    shade = (0.75 + 0.35 * (1 - v))[..., None] if not light else (1.0 - 0.06 * v)[..., None]
    img *= shade
    if variant == "aurora":
        for i in range(5):
            phase = rng.uniform(0, 2 * math.pi)
            freq = rng.uniform(1.2, 2.4)
            amp = rng.uniform(0.06, 0.12)
            centre = 0.35 + i * 0.09 + amp * np.sin(2 * math.pi * freq * u + phase) + 0.04 * np.sin(7 * u + phase)
            width_band = 0.035 + 0.02 * i
            band = np.exp(-(((v - centre) / width_band) ** 2))
            glow = np.exp(-(((v - centre) / (width_band * 4)) ** 2)) * 0.35
            mix = (u * 0.8 + 0.1 * i)[..., None].clip(0, 1)
            colour = c1 * (1 - mix) + c2 * mix
            strength = (0.55 - i * 0.07) * (band + glow)[..., None]
            if light:
                a = (strength * 0.75).clip(0, 0.85)
                img = img * (1 - a) + (colour * 0.85 + 0.15) * a
            else:
                img = img * (1 - strength * 0.6) + colour * strength
    else:  # orbit
        cx, cy = 0.72, 0.62
        r = np.sqrt(((u - cx) * width / height) ** 2 + (v - cy) ** 2)
        for i, radius in enumerate((0.22, 0.34, 0.48, 0.66)):
            ring = np.exp(-(((r - radius) / 0.004) ** 2)) * (0.9 - i * 0.18)
            angle = (np.arctan2(v - cy, (u - cx) * width / height) + math.pi) / (2 * math.pi)
            colour = c1 * (1 - angle[..., None]) + c2 * angle[..., None]
            img = img + colour * ring[..., None] * 0.8
        glow = np.exp(-((r / 0.5) ** 2))[..., None]
        img = img + (c1 * 0.5 + c2 * 0.5) * glow * (0.10 if light else 0.22)
    # Fine grain keeps gradients from banding on 8-bit displays.
    img += rng.normal(0, 0.006, img.shape).astype(np.float32)
    return Image.fromarray((img.clip(0, 1) * 255).astype(np.uint8), "RGB")


def plymouth_assets(b: Branding, out: Path, logo_png: Path) -> None:
    from PIL import Image, ImageDraw

    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(logo_png, out / "logo.png")
    accent = hex_rgb(b["BRAND_ACCENT"])
    accent2 = hex_rgb(b["BRAND_ACCENT_2"])
    # Progress bar: track and fill, 360x6.
    track = Image.new("RGBA", (360, 6), (255, 255, 255, 40))
    ImageDraw.Draw(track).rounded_rectangle((0, 0, 359, 5), 3, fill=(255, 255, 255, 40))
    track.save(out / "progress-track.png")
    fill = Image.new("RGBA", (360, 6), (0, 0, 0, 0))
    d = ImageDraw.Draw(fill)
    for x in range(360):
        t = x / 359
        col = tuple(int(accent[i] * (1 - t) + accent2[i] * t) for i in range(3)) + (255,)
        d.line((x, 0, x, 5), fill=col)
    fill.save(out / "progress-fill.png")
    # Password prompt: entry box and bullet.
    entry = Image.new("RGBA", (360, 48), (0, 0, 0, 0))
    ImageDraw.Draw(entry).rounded_rectangle((0, 0, 359, 47), 14, fill=(255, 255, 255, 28), outline=accent + (200,), width=2)
    entry.save(out / "entry.png")
    bullet = Image.new("RGBA", (14, 14), (0, 0, 0, 0))
    ImageDraw.Draw(bullet).ellipse((1, 1, 12, 12), fill=(232, 236, 248, 255))
    bullet.save(out / "bullet.png")
    lock = Image.new("RGBA", (28, 28), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lock)
    ld.rounded_rectangle((4, 12, 23, 26), 4, fill=accent2 + (255,))
    ld.arc((8, 2, 19, 18), 180, 360, fill=accent2 + (255,), width=3)
    lock.save(out / "lock.png")


def generate(quick: bool = False, b: Branding | None = None, log=print) -> None:
    b = b or load_branding()
    root = paths.data("branding")
    gen = root / "generated"
    rendered = render_templates(root, gen, b)
    log(f"rendered {len(rendered)} templates")
    if quick:
        return
    logo_mark = gen / "logo" / "logo-mark.svg"
    app_icons = sorted((gen / "icons" / "apps").glob("*.svg"))
    icons = gen / "icons" / "hicolor"
    for size in ICON_SIZES:
        rasterise(logo_mark, icons / f"{size}x{size}" / "apps" / f"{b.id}.png", size)
        for app in app_icons:
            rasterise(app, icons / f"{size}x{size}" / "apps" / f"{b.id}-{app.stem}.png", size)
    (icons / "scalable" / "apps").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(logo_mark, icons / "scalable" / "apps" / f"{b.id}.svg")
    for app in app_icons:
        shutil.copyfile(app, icons / "scalable" / "apps" / f"{b.id}-{app.stem}.svg")
    log("icons done")

    walls = gen / "wallpapers"
    walls.mkdir(parents=True, exist_ok=True)
    aurora(b, 3840, 2160).save(walls / f"{b.id}-default.png", optimize=True)
    aurora(b, 3840, 2160, variant="orbit", seed=11).save(walls / f"{b.id}-orbit.png", optimize=True)
    aurora(b, 3840, 2160, light=True, seed=5).save(walls / f"{b.id}-light.png", optimize=True)
    log("wallpapers done")

    logo256 = gen / "logo-256.png"
    rasterise(logo_mark, logo256, 256)
    rasterise(gen / "logo" / "logo.svg", gen / "logo-wordmark.png", 880, 256)
    plymouth_assets(b, gen / "plymouth", logo256)

    bg = aurora(b, 1920, 1080, seed=3)
    grub_dir = gen / "grub"
    grub_dir.mkdir(parents=True, exist_ok=True)
    from PIL import ImageEnhance

    ImageEnhance.Brightness(bg).enhance(0.7).save(grub_dir / "background.png")
    sddm_dir = gen / "sddm"
    sddm_dir.mkdir(parents=True, exist_ok=True)
    bg.save(sddm_dir / "background.png")
    rasterise(logo_mark, sddm_dir / "logo.png", 192)
    rasterise(logo_mark, grub_dir / "logo.png", 128)
    splash = ImageEnhance.Brightness(aurora(b, 640, 480, seed=3)).enhance(0.55)
    syslinux = gen / "syslinux"
    syslinux.mkdir(parents=True, exist_ok=True)
    from PIL import Image

    logo_small = gen / "logo-96.png"
    rasterise(logo_mark, logo_small, 96)
    mark = Image.open(logo_small).convert("RGBA")
    splash = splash.convert("RGBA")
    splash.alpha_composite(mark, (272, 64))
    splash.convert("RGB").save(syslinux / "splash.png")
    log("boot artwork done")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--quick", action="store_true", help="only render templates (no raster artwork)")
    a = p.parse_args(argv)
    generate(quick=a.quick)
    return 0


if __name__ == "__main__":
    sys.exit(main())
