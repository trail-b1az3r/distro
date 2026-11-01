#!/usr/bin/env python3
"""Convert Nexora's canonical SVG logo mark into a colour-limited Fastfetch logo.

Example:
  python3 scripts/generate_fastfetch_logo.py branding/generated/logo/logo-mark.svg branding/generated/fastfetch/logo.ansi
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from distrokit.build.branding import ansi_logo, rasterise  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="rendered Nexora logo-mark.svg")
    parser.add_argument("output", type=Path, help="destination .ansi file")
    parser.add_argument("--columns", type=int, default=24, help="terminal logo width (default: 24)")
    parser.add_argument("--max-colors", type=int, choices=range(1, 10), default=9,
                        help="maximum visible colours (1-9; default: 9)")
    args = parser.parse_args()

    if not args.source.is_file():
        parser.error(f"logo source does not exist: {args.source}")
    temporary_png = args.output.with_suffix(".render.png")
    try:
        rasterise(args.source, temporary_png, 256)
        ansi = ansi_logo(temporary_png, cols=args.columns, max_colors=args.max_colors)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(ansi, encoding="utf-8")
    finally:
        temporary_png.unlink(missing_ok=True)

    print(f"Generated {args.output} at {args.columns} columns using at most {args.max_colors} colours")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
