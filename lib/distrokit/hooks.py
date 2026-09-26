"""Actions run by pacman hooks (``/usr/share/libalpm/hooks``).

    <id>-update-boot     after kernels, initramfs or boot loader packages change
    <id>-os-release      after ``filesystem`` or ``lsb-release`` are upgraded

Both are non-interactive and idempotent. They print one line each, which
pacman shows as the hook's output.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import __version__, boot, util
from .branding import Branding, load as load_branding


def os_release_files(b: Branding, version: str = __version__) -> dict[str, str]:
    """The identity files the distribution owns the contents of."""
    return {
        "usr/lib/os-release": b.os_release(version),
        "etc/lsb-release": (f'DISTRIB_ID="{b.name}"\nDISTRIB_RELEASE="rolling"\n'
                            f'DISTRIB_DESCRIPTION="{b.pretty_name}"\n'),
        "etc/issue": f"{b.pretty_name} \\r (\\l)\n\n",
    }


def write_os_release(root: Path | str = "/", b: Branding | None = None) -> list[str]:
    """Rewrite os-release, lsb-release and issue. ``filesystem`` and
    ``lsb-release`` ship Arch Linux's versions and restore them on every
    upgrade; this hook puts ours back."""
    b = b or load_branding()
    root = Path(root)
    changed = []
    for rel, content in os_release_files(b).items():
        path = root / rel
        if rel == "etc/lsb-release" and not path.exists():
            continue  # lsb-release is optional
        current = path.read_text() if path.is_file() else None
        if current != content:
            util.atomic_write(path, content, 0o644)
            changed.append("/" + rel)
    etc = root / "etc" / "os-release"
    if not etc.is_symlink() and not etc.exists():
        etc.symlink_to("../usr/lib/os-release")
    return changed


def _root(argv: list[str] | None) -> Path:
    args = sys.argv[1:] if argv is None else argv
    return Path(args[0]) if args else Path("/")


def update_boot_main(argv: list[str] | None = None) -> int:
    root = _root(argv)
    b = load_branding()
    if os.path.isdir("/run/archiso") and str(root) == "/":
        print("live system: boot entries are managed by the ISO")
        return 0
    try:
        print(boot.update(root, util.Runner(), b))
    except Exception as exc:  # noqa: BLE001 - a hook must not abort the transaction
        print(f"could not update boot entries: {exc}. Run `sudo {b.cli} repair boot`.", file=sys.stderr)
        return 1
    return 0


def os_release_main(argv: list[str] | None = None) -> int:
    root = _root(argv)
    changed = write_os_release(root)
    print("identity files: " + (", ".join(changed) if changed else "up to date"))
    return 0
