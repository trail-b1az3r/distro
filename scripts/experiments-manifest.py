#!/usr/bin/env python3
"""Write the public packages.json of a CI pacman source (nexora-experiments, or nexora-experiments-extra: beta).

    experiments-manifest.py PACKAGE_DIR OUTPUT_JSON [--repo NAME] [--branch B] [--commit SHA] [--run URL]

Each package's name, version and architecture come from the .PKGINFO inside its archive (makepkg writes it first),
so this needs only zstd, not pacman: `pacman -Qp` takes no --print-format, and its plain output has no architecture.
"""

from __future__ import annotations

import argparse
import datetime
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from distrokit.experiments import EXTRA, MAIN, OTHER, OWN  # noqa: E402

SOURCES = {
    MAIN: "latest successful Arch package build on main; refreshed nightly and on main pushes",
    EXTRA: "beta: latest successful Arch package build of a development branch (beta, claude/**)",
}
SUFFIXES = (".pkg.tar.zst", ".pkg.tar.xz", ".pkg.tar.gz", ".pkg.tar.bz2", ".pkg.tar")


def pkginfo(archive: Path) -> dict[str, str]:
    """The .PKGINFO fields (first value of each key) of a pacman package archive."""
    if archive.name.endswith(".zst"):
        data = subprocess.run(["zstd", "-dcq", str(archive)], check=True, capture_output=True).stdout
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:")
    else:
        tar = tarfile.open(archive, mode="r:*")
    with tar:
        for member in tar:
            if member.name.removeprefix("./") == ".PKGINFO":
                text = tar.extractfile(member).read().decode()
                break
        else:
            raise ValueError(f"{archive.name}: no .PKGINFO, not a pacman package")
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(" = ")
        if sep and not key.startswith("#"):
            fields.setdefault(key.strip(), value.strip())
    for key in ("pkgname", "pkgver", "arch"):
        if not fields.get(key):
            raise ValueError(f"{archive.name}: .PKGINFO has no {key}")
    return fields


def component(name: str, distro_id: str = "nexora") -> str:
    """The `<cli> experiments` component a package belongs to, or "" for a dependency built alongside."""
    for own in OWN:
        if name == f"{distro_id}-{own}":
            return own
    for key, names in OTHER.items():
        if name in (n.format(id=distro_id) for n in names):
            return key
    return ""


def manifest(directory: Path, repo: str = MAIN, branch: str = "", commit: str = "", run: str = "") -> dict:
    packages = []
    for archive in sorted(p for p in directory.iterdir() if p.name.endswith(SUFFIXES)):
        info = pkginfo(archive)
        packages.append({"name": info["pkgname"], "version": info["pkgver"], "arch": info["arch"],
                         "filename": archive.name, "component": component(info["pkgname"]),
                         "builddate": int(info.get("builddate", "0") or 0)})
    if not packages:
        raise SystemExit(f"package manifest would be empty: no packages in {directory}")
    data = {
        "schema": 2,
        "repository": repo,
        "beta": repo == EXTRA,
        "source": SOURCES.get(repo, repo),
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "components": sorted({p["component"] for p in packages if p["component"]}),
        "packages": packages,
    }
    for key, value in (("branch", branch), ("commit", commit), ("run", run)):
        if value:
            data[key] = value
    return data


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repo", default=MAIN, choices=sorted(SOURCES))
    parser.add_argument("--branch", default="")
    parser.add_argument("--commit", default="")
    parser.add_argument("--run", default="")
    a = parser.parse_args(argv)
    data = manifest(a.directory, a.repo, a.branch, a.commit, a.run)
    a.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(f"Wrote the {a.repo} manifest for {len(data['packages'])} CI packages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
