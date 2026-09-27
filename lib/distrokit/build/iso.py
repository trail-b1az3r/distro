"""Build the live ISO.

    python3 -m distrokit.build.iso build   [--profile standard] [--offline minimal|full] [--clean] [--debug]
    python3 -m distrokit.build.iso profile --out DIR [...]     # only assemble the archiso profile
    python3 -m distrokit.build.iso info                        # what would be built

``build.sh`` in the repository root is the front end (it also runs the whole
build in a container). Steps:

1. artwork (``distrokit.build.branding``)
2. the distribution repository (``distrokit.build.packages``): our packages,
   the dots' meta packages and every AUR package, built in dependency order
3. the offline repository carried on the ISO: ``minimal`` holds the
   distribution repository (the installer downloads the rest); ``full`` adds
   every package an installation can need, so it works with no network
4. the archiso profile: archiso's releng profile with iso/ laid over it,
   package list, pacman configuration and build information generated here
5. mkarchiso, then ``dist/<Name>-<version>-x86_64.iso`` with checksums in
   ``checksums/`` and build metadata in ``metadata/``

Inputs are pinned for reproducibility: SOURCE_DATE_EPOCH defaults to the
commit time, ARCHIVE_DATE pins Arch packages to the Arch Linux Archive, AUR
packages are pinned in packages/aur.lock.json and the dots by the submodule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .. import __version__, pacmanconf, paths, util
from ..branding import Branding, load as load_branding
from ..profiles import load_editors, load_profiles, read_list, select_packages
from . import packages as pkgbuild
from . import stage

RELENG = Path("/usr/share/archiso/configs/releng")
LIVE_LISTS = ["base", "desktop", "browser", "live"]
LIVE_EXTRA = ["linux", "amd-ucode", "intel-ucode"]

# releng pieces the distribution replaces or does not want: its boot menus,
# the root autologin with Arch's install script, systemd-networkd/iwd/resolved
# (NetworkManager manages the network here), sshd with an empty root
# password, and the speech/sound helpers of packages that are not installed.
RELENG_REMOVE = [
    "efiboot/loader/entries",
    "grub",
    "syslinux",
    "packages.x86_64",
    "packages.aarch64",
    "pacman.conf",
    "profiledef.sh",
    "airootfs/root/.automated_script.sh",
    "airootfs/root/.zlogin",
    "airootfs/etc/motd",
    "airootfs/etc/hostname",
    "airootfs/etc/passwd",
    "airootfs/etc/shadow",
    "airootfs/etc/resolv.conf",
    "airootfs/etc/ssh/sshd_config.d/10-archiso.conf",
    "airootfs/etc/systemd/network",
    "airootfs/etc/systemd/networkd.conf.d",
    "airootfs/etc/systemd/resolved.conf.d",
    "airootfs/etc/systemd/system/getty@tty1.service.d",
    "airootfs/etc/systemd/system/cloud-init.target.wants",
    "airootfs/etc/systemd/system/dbus-org.freedesktop.network1.service",
    "airootfs/etc/systemd/system/dbus-org.freedesktop.resolve1.service",
    "airootfs/etc/systemd/system/multi-user.target.wants/iwd.service",
    "airootfs/etc/systemd/system/multi-user.target.wants/sshd.service",
    "airootfs/etc/systemd/system/multi-user.target.wants/systemd-networkd.service",
    "airootfs/etc/systemd/system/multi-user.target.wants/systemd-resolved.service",
    "airootfs/etc/systemd/system/multi-user.target.wants/livecd-talk.service",
    "airootfs/etc/systemd/system/multi-user.target.wants/ModemManager.service",
    "airootfs/etc/systemd/system/dbus-org.freedesktop.ModemManager1.service",
    "airootfs/etc/systemd/system/sockets.target.wants/pcscd.socket",
    "airootfs/etc/systemd/system/network-online.target.wants/systemd-networkd-wait-online.service",
    "airootfs/etc/systemd/system/systemd-networkd-wait-online.service.d",
    "airootfs/etc/systemd/system/sockets.target.wants/systemd-networkd.socket",
    "airootfs/etc/systemd/system/sound.target.wants/livecd-alsa-unmuter.service",
    "airootfs/etc/systemd/system/livecd-alsa-unmuter.service",
    "airootfs/etc/systemd/system/livecd-talk.service",
    "airootfs/usr/local/bin/livecd-sound",
    "airootfs/usr/local/share/livecd-sound",
    "airootfs/usr/local/bin/Installation_guide",
]

SQUASHFS = {
    "release": "'-comp' 'xz' '-Xbcj' 'x86' '-b' '1M' '-Xdict-size' '1M'",
    "debug": "'-comp' 'zstd' '-Xcompression-level' '3' '-b' '1M'",
}


@dataclass
class Options:
    profile: str = "standard"
    offline: str = "minimal"  # minimal | full
    clean: bool = False
    debug: bool = False
    skip_packages: bool = False
    dist: Path = Path("dist")
    build: Path = Path("build")
    releng: Path = RELENG
    archive_date: str = ""
    sign_key: str = ""
    multilib: bool = True
    profile_out: Path | None = None

    @property
    def repo(self) -> Path:
        return self.build / "repo"

    @property
    def offline_repo(self) -> Path:
        return self.build / "offline-repo"

    @property
    def profile_dir(self) -> Path:
        return self.profile_out or self.build / "iso-profile"

    @property
    def work(self) -> Path:
        return self.build / "iso-work"

    @property
    def out(self) -> Path:
        return self.build / "iso-out"


# ---------------------------------------------------------------------------
# Names and versions
# ---------------------------------------------------------------------------


def source_epoch(src: Path | None = None) -> int:
    if os.environ.get("SOURCE_DATE_EPOCH"):
        return int(os.environ["SOURCE_DATE_EPOCH"])
    return pkgbuild.source_version(src or paths.DATA_ROOT)[1] or int(time.time())


def iso_version(b: Branding, epoch: int) -> str:
    return time.strftime(b.get("ISO_VERSION_FORMAT", "%Y.%m"), time.gmtime(epoch))


def iso_label(b: Branding, epoch: int) -> str:
    return f"{b['ISO_LABEL_PREFIX']}_{time.strftime('%Y%m', time.gmtime(epoch))}"[:32]


def iso_filename(b: Branding, version: str) -> str:
    return f"{b.name}-{version}-x86_64.iso"


def git_commit(path: Path) -> str:
    try:
        return pkgbuild.git_output(["rev-parse", "HEAD"], path)
    except (OSError, subprocess.CalledProcessError):
        return ""


# ---------------------------------------------------------------------------
# Package sets
# ---------------------------------------------------------------------------


def live_packages(b: Branding) -> list[str]:
    pk: list[str] = []
    for name in LIVE_LISTS:
        pk += read_list(name, b)
    return list(dict.fromkeys(pk + LIVE_EXTRA))


def offline_sets(b: Branding, profile_id: str, multilib: bool = True) -> list[list[str]]:
    """Package sets for a complete offline repository. Each set installs
    together; separate sets hold alternatives that conflict (driver stacks,
    prebuilt vs DKMS modules). GPU compute toolkits (CUDA, ROCm: many GB) and
    non-redistributable software stay online-only."""
    root = paths.DATA_ROOT
    profile = load_profiles()[profile_id]
    base = list(select_packages(profile, branding=b).packages)
    for extra in ("grub", "laptop", "intel-laptop", "snapshots", "firewall", "virt-qemu", "virt-virtualbox",
                  "virt-vmware", "virt-hyperv"):
        base += read_list(extra, b)
    base += ["linux", "linux-headers", "amd-ucode", "intel-ucode", "sbctl", "zram-generator"]
    with (root / "ai" / "runtime" / "llama-server.toml").open("rb") as fh:
        llama = tomllib.load(fh)["packages"]
    base += [llama["vulkan"], llama["cpu"]]
    editors = load_editors()
    editor = editors.get(b.get("CODE_EDITOR", "code"))
    if editor and not editor.redistributable:
        base = [p for p in base if p != editor.package]
    with (root / "hardware" / "gpu" / "drivers.toml").open("rb") as fh:
        drivers = tomllib.load(fh)
    common = drivers.get("common", {})
    base += common.get("packages", []) + (common.get("packages_32bit", []) if multilib else [])
    sets = [list(dict.fromkeys(base))]
    for _sid, stack in sorted(drivers.get("stack", {}).items()):
        pk = list(stack.get("packages", [])) + (list(stack.get("packages_32bit", [])) if multilib else [])
        if not pk:
            continue
        sets.append(pk + (["linux-headers"] if stack.get("dkms") else []))
        for _kernel, prebuilt in sorted(stack.get("prebuilt", {}).items()):
            dkms = [p for p in stack.get("packages", []) if p.endswith("-dkms")]
            sets.append([prebuilt if p in dkms else p for p in pk])
    for hyb in drivers.get("hybrid", {}).values():
        if hyb.get("packages"):
            sets.append(list(hyb["packages"]))
    sets.append(["linux-lts", "linux-lts-headers", "linux-zen", "linux-zen-headers"])
    return sets


# ---------------------------------------------------------------------------
# Profile assembly
# ---------------------------------------------------------------------------


def mounts_under(path: Path, mountinfo: str | None = None) -> list[str]:
    """Mount points at or below ``path``, deepest first."""
    root = str(path.resolve())
    if mountinfo is None:
        mountinfo = Path("/proc/self/mountinfo").read_text()
    points = []
    for line in mountinfo.splitlines():
        fields = line.split()
        if len(fields) < 5:
            continue
        point = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), fields[4])
        if point == root or point.startswith(root + "/"):
            points.append(point)
    return sorted(points, key=lambda p: p.count("/"), reverse=True)


def release_mounts(path: Path, runner: util.Runner) -> None:
    """Unmount what an interrupted or failed earlier build left mounted under
    ``path`` (mkarchiso's /proc of the live system, for one)."""
    for point in mounts_under(path):
        print(f"    unmounting {point}, left over from an earlier build")
        runner.run(["umount", "--lazy", point])


def _remove(path: Path) -> None:
    if mounts_under(path):  # never delete through a mount into a live file system
        raise SystemExit(f"{path} has file systems mounted below it: {', '.join(mounts_under(path))}")
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _link(path: Path, target: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.exists():
        path.unlink()
    path.symlink_to(target)


def render_tree(src: Path, dest: Path, b: Branding, extra: dict[str, str]) -> list[Path]:
    """Copy src into dest, rendering *.in templates and @TOKENS@ in names."""
    out = []
    for f in sorted(src.rglob("*")):
        if f.is_dir():
            continue
        rel = Path(b.render(f.relative_to(src).as_posix(), extra))
        target = dest / (rel.with_suffix("") if rel.suffix == ".in" else rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.exists():
            target.unlink()
        if f.suffix == ".in":
            target.write_text(b.render(f.read_text(), extra))
        else:
            shutil.copyfile(f, target)
        out.append(target)
    return out


def build_info(b: Branding, opts: Options, epoch: int) -> dict:
    src = paths.DATA_ROOT
    return {
        "name": b.pretty_name,
        "id": b.id,
        "version": iso_version(b, epoch),
        "label": iso_label(b, epoch),
        "profile": opts.profile,
        "offline": opts.offline,
        "source_date_epoch": epoch,
        "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch)),
        "source_commit": git_commit(src),
        "desktop": stage.desktop_version(src),
        "distrokit": __version__,
        "archive_date": opts.archive_date,
        "debug": opts.debug,
    }


def assemble(opts: Options, b: Branding | None = None, epoch: int | None = None) -> Path:
    """Write the archiso profile to ``opts.profile_dir``."""
    b = b or load_branding()
    epoch = epoch if epoch is not None else source_epoch()
    src = paths.DATA_ROOT
    prof = opts.profile_dir
    if not (opts.releng / "profiledef.sh").is_file():
        raise SystemExit(f"archiso's releng profile was not found at {opts.releng} (install archiso)")
    _remove(prof)
    shutil.copytree(opts.releng, prof, symlinks=True)
    for rel in RELENG_REMOVE:
        _remove(prof / rel)

    from .branding import colour_tokens

    extra = colour_tokens(b) | {
        "ISO_LABEL": iso_label(b, epoch),
        "ISO_VERSION": iso_version(b, epoch),
        "SQUASHFS_OPTIONS": SQUASHFS["debug" if opts.debug else "release"],
    }
    render_tree(src / "iso", prof, b, extra)
    (prof / "sources.conf").unlink(missing_ok=True)

    splash = src / "branding" / "generated" / "syslinux" / "splash.png"
    if splash.is_file():
        shutil.copyfile(splash, prof / "syslinux" / "splash.png")

    (prof / "packages.x86_64").write_text(
        f"# {b.pretty_name} live system, generated from packages/lists/{{{','.join(LIVE_LISTS)}}}.list\n"
        + "\n".join(sorted(live_packages(b))) + "\n")

    # pacman.conf for mkarchiso: the freshly built distribution repository first.
    (prof / "pacman.conf").write_text(
        pkgbuild.build_pacman_conf(b, opts.repo, opts.archive_date, opts.multilib))

    air = prof / "airootfs"
    offline_dir = f"/var/cache/{b.id}/repo"
    live_conf = pacmanconf.render("live", b, offline_repo=offline_dir, multilib=opts.multilib)
    (air / "etc").mkdir(parents=True, exist_ok=True)
    (air / "etc" / "pacman.conf").write_text(live_conf)
    sysconf = air / "etc" / b.id
    sysconf.mkdir(parents=True, exist_ok=True)
    (sysconf / "pacman-live.conf").write_text(live_conf)
    (sysconf / "pacman-offline.conf").write_text(
        pacmanconf.render("offline", b, offline_repo=offline_dir, multilib=opts.multilib))
    (sysconf / "live").write_text("This is the live ISO.\n")
    (sysconf / "iso-build.json").write_text(json.dumps(build_info(b, opts, epoch), indent=2) + "\n")

    systemd = air / "etc" / "systemd" / "system"
    units = "/usr/lib/systemd/system"
    _link(systemd / "display-manager.service", f"{units}/greetd.service")
    ours = (f"{b.id}-live-setup.service", f"{b.id}-autoinstall.service")
    for unit in ("NetworkManager.service", "bluetooth.service", *ours):
        target = f"/etc/systemd/system/{unit}" if unit in ours else f"{units}/{unit}"
        _link(systemd / "multi-user.target.wants" / unit, target)
    _link(systemd / "network-online.target.wants" / "NetworkManager-wait-online.service",
          f"{units}/NetworkManager-wait-online.service")
    _link(systemd / "dbus-org.freedesktop.NetworkManager.service", f"{units}/NetworkManager.service")
    _link(systemd / "dbus-org.freedesktop.nm-dispatcher.service", f"{units}/NetworkManager-dispatcher.service")
    _link(systemd / "dbus-org.bluez.service", f"{units}/bluetooth.service")

    if opts.offline_repo.is_dir():
        dest = air / offline_dir.lstrip("/")
        dest.mkdir(parents=True, exist_ok=True)
        for f in sorted(opts.offline_repo.iterdir()):
            if f.is_file():
                try:
                    os.link(f, dest / f.name)
                except OSError:
                    shutil.copyfile(f, dest / f.name)
    return prof


# ---------------------------------------------------------------------------
# Offline repository
# ---------------------------------------------------------------------------


def offline_repository(opts: Options, b: Branding, runner: util.Runner, conf: Path) -> Path:
    """Fill ``opts.offline_repo`` and index it as ``<repo>-offline``."""
    out = opts.offline_repo
    _remove(out)
    out.mkdir(parents=True)
    for f in sorted(opts.repo.glob("*.pkg.tar.*")):
        shutil.copyfile(f, out / f.name)
    if opts.offline == "full":
        db = opts.build / "offline-db"
        _remove(db)
        db.mkdir(parents=True)
        runner.run(["pacman", "--config", str(conf), "--dbpath", str(db), "-Sy"])
        for pkset in offline_sets(b, opts.profile, opts.multilib):
            runner.run(["pacman", "--config", str(conf), "--dbpath", str(db), "--cachedir", str(out),
                        "--noconfirm", "-Sw", *pkset])
        _remove(db)
    pkgs = sorted(str(p) for p in out.glob("*.pkg.tar.*") if not p.name.endswith(".sig"))
    runner.run(["repo-add", "--new", str(out / f"{b.repo_name}-offline.db.tar.gz"), *pkgs])
    return out


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


def checksum_files(iso: Path, dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    sums = {"sha256": hashlib.sha256(), "b2": hashlib.blake2b()}
    with iso.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 2**20), b""):
            for h in sums.values():
                h.update(chunk)
    out = []
    for kind, h in sums.items():
        path = dest / f"{iso.name}.{kind}sum" if kind == "b2" else dest / f"{iso.name}.{kind}"
        path.write_text(f"{h.hexdigest()}  {iso.name}\n")
        out.append(path)
    return out


def finish(opts: Options, b: Branding, epoch: int, runner: util.Runner) -> dict:
    """Move the ISO to dist/ and write checksums and metadata."""
    version = iso_version(b, epoch)
    name = iso_filename(b, version)
    built = sorted(opts.out.glob("*.iso"))
    if not built:
        raise SystemExit(f"mkarchiso produced no ISO in {opts.out}")
    opts.dist.mkdir(parents=True, exist_ok=True)
    iso = opts.dist / name
    shutil.move(str(built[-1]), iso)
    root = opts.dist.parent
    sums = checksum_files(iso, root / "checksums")
    if opts.sign_key:
        for s in sums:
            runner.run(["gpg", "--batch", "--yes", "--local-user", opts.sign_key, "--detach-sign", str(s)])
    meta_dir = root / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)
    info = build_info(b, opts, epoch)
    info["iso"] = name
    info["size_bytes"] = iso.stat().st_size
    info["sha256"] = sums[0].read_text().split()[0]
    pkglist = next(opts.work.glob("iso/arch/pkglist.*.txt"), None) if opts.work.is_dir() else None
    if pkglist:
        shutil.copyfile(pkglist, meta_dir / f"{iso.stem}.packages.txt")
        info["live_packages"] = len(pkglist.read_text().splitlines())
    offline = sorted(p.name for p in opts.offline_repo.glob("*.pkg.tar.*") if not p.name.endswith(".sig"))
    (meta_dir / f"{iso.stem}.offline-repo.txt").write_text("\n".join(offline) + "\n")
    info["offline_packages"] = len(offline)
    lock = paths.DATA_ROOT / pkgbuild.LOCK_FILE
    if lock.is_file():
        shutil.copyfile(lock, meta_dir / f"{iso.stem}.aur.lock.json")
    (meta_dir / f"{iso.stem}.json").write_text(json.dumps(info, indent=2) + "\n")
    return info


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------


def preflight(opts: Options) -> list[str]:
    problems = []
    if os.geteuid() != 0:
        problems.append("mkarchiso needs root: run `sudo ./build.sh`, or `./build.sh --container`.")
    need = ["mkarchiso", "pacman", "repo-add", "unshare"]
    need += [] if opts.skip_packages else ["makepkg", "git", "pacstrap", "arch-chroot"]
    for exe in need:
        if not shutil.which(exe):
            problems.append(f"`{exe}` is missing: run scripts/bootstrap.sh on an Arch-based host, "
                            "or `./build.sh --container`.")
    if not (opts.releng / "profiledef.sh").is_file():
        problems.append(f"archiso's releng profile is missing ({opts.releng}).")
    if opts.profile not in load_profiles():
        problems.append(f"unknown profile {opts.profile!r}; choose from {', '.join(load_profiles())}.")
    free = shutil.disk_usage(opts.build if opts.build.exists() else Path.cwd()).free
    want = (60 if opts.offline == "full" else 30) * 2**30
    if free < want:
        problems.append(f"only {util.human_bytes(free)} free; the build needs about {util.human_bytes(want)}.")
    return problems


def build(opts: Options, runner: util.Runner | None = None) -> dict:
    b = load_branding()
    runner = runner or util.Runner(log=print)
    epoch = source_epoch()
    env = {"SOURCE_DATE_EPOCH": str(epoch)}
    if opts.archive_date:
        env["ARCHIVE_DATE"] = opts.archive_date
    runner.env.update(env)
    os.environ.update(env)

    if opts.build.exists() and not runner.dry_run:
        release_mounts(opts.build, runner)
    if opts.clean:
        for d in (opts.work, opts.out, opts.profile_dir, opts.offline_repo, opts.build / "packages"):
            _remove(d)
    opts.build.mkdir(parents=True, exist_ok=True)

    print(f"==> {b.pretty_name} {iso_version(b, epoch)}: profile {opts.profile}, offline repository {opts.offline}")
    print("==> Artwork")
    from . import branding as artwork

    artwork.generate(quick=runner.dry_run, log=lambda m: print("    " + m))

    print("==> Distribution repository")
    if not opts.skip_packages:
        args = ["build", "--out", str(opts.build / "pkgbuild"), "--work", str(opts.build / "packages"),
                "--repo", str(opts.repo)]
        if not opts.multilib:
            args.append("--no-multilib")
        if opts.sign_key:
            args += ["--sign", opts.sign_key]
        if runner.dry_run:
            runner.run([sys.executable, "-m", "distrokit.build.packages", *args])
        elif pkgbuild.main(args) != 0:
            raise SystemExit("building the distribution repository failed")
    elif not any(opts.repo.glob("*.pkg.tar.*")) and not runner.dry_run:
        raise SystemExit(f"--skip-packages: no packages in {opts.repo}")

    print("==> Offline repository")
    conf = pkgbuild.build_conf(b, opts.repo, opts.build / "packages", multilib=opts.multilib)
    offline_repository(opts, b, runner, conf)

    print("==> archiso profile")
    prof = assemble(opts, b, epoch)

    print("==> mkarchiso")
    _remove(opts.out)
    cmd = ["mkarchiso", "-v", "-w", str(opts.work), "-o", str(opts.out), str(prof)]
    if not opts.debug:
        cmd.insert(2, "-r")  # remove the work directory afterwards
    # In a mount namespace of its own: the live system's /proc, /sys and /dev
    # mounts are invisible to (and cannot be held busy by) anything else on
    # the host, such as file indexers, and vanish if mkarchiso is interrupted.
    runner.run(["unshare", "--mount", "--propagation", "private", "--", *cmd])
    if runner.dry_run:
        return {"dry_run": True, "commands": [" ".join(c) for c in runner.recorded]}
    info = finish(opts, b, epoch, runner)
    print(f"==> {opts.dist / info['iso']} ({util.human_bytes(info['size_bytes'])}), sha256 {info['sha256']}")
    return info


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="distrokit.build.iso", description=__doc__.splitlines()[0])
    p.add_argument("action", choices=["build", "profile", "info"], nargs="?", default="build")
    p.add_argument("--profile", default=os.environ.get("ISO_PROFILE", "standard"),
                   help="installation profile the ISO offers by default (and carries offline)")
    p.add_argument("--offline", choices=["minimal", "full"], default=os.environ.get("ISO_OFFLINE", "minimal"),
                   help="minimal: distribution packages only; full: everything for installs with no network")
    p.add_argument("--clean", action="store_true", help="start from a clean work directory")
    p.add_argument("--debug", action="store_true", help="fast compression, keep the work directory, verbose")
    p.add_argument("--skip-packages", action="store_true", help="reuse the packages already in build/repo")
    p.add_argument("--no-multilib", action="store_true")
    p.add_argument("--dist", default="dist")
    p.add_argument("--build-dir", default="build")
    p.add_argument("--releng", default=str(RELENG))
    p.add_argument("--archive-date", default=os.environ.get("ARCHIVE_DATE", ""),
                   help="YYYY/MM/DD: install Arch packages from that day's Arch Linux Archive snapshot")
    p.add_argument("--sign", default=os.environ.get("GPGKEY", ""), help="GPG key for packages and checksums")
    p.add_argument("--out", help="profile: where to write the archiso profile")
    p.add_argument("--dry-run", action="store_true", help="print the commands instead of running them")
    a = p.parse_args(argv)
    opts = Options(profile=a.profile, offline=a.offline, clean=a.clean, debug=a.debug,
                   skip_packages=a.skip_packages, dist=Path(a.dist), build=Path(a.build_dir),
                   releng=Path(a.releng), archive_date=a.archive_date, sign_key=a.sign, multilib=not a.no_multilib)
    b = load_branding()
    if a.action == "info":
        epoch = source_epoch()
        info = build_info(b, opts, epoch) | {"iso": iso_filename(b, iso_version(b, epoch)),
                                             "live_packages": len(live_packages(b))}
        print(json.dumps(info, indent=2))
        return 0
    if a.action == "profile":
        if a.out:
            opts.profile_out = Path(a.out)
        print(assemble(opts, b))
        return 0
    problems = [] if a.dry_run else preflight(opts)
    if problems:
        for problem in problems:
            print(util.style.fail(problem), file=sys.stderr)
        return 1
    try:
        build(opts, util.Runner(log=print, dry_run=a.dry_run))
    except (pkgbuild.FetchError, util.CommandError) as e:
        if opts.debug:
            raise
        print(util.style.fail(f"error: {e}"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
