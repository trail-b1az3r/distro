"""Build the distribution repository (and the ISO's offline repository).

    python3 -m distrokit.build.packages render  --out build/pkgbuild
    python3 -m distrokit.build.packages lock    [--out build/pkgbuild]
    python3 -m distrokit.build.packages plan    [--out build/pkgbuild]
    python3 -m distrokit.build.packages build   --repo build/repo [--only PKGBASE...] [--force]

``render`` writes the distribution's PKGBUILDs (from packages/pkgbuild/*.in)
next to a reproducible source tarball. ``lock`` resolves every AUR package the
distribution needs, with its AUR dependencies, and pins each to an AUR git
commit in packages/aur.lock.json. ``build`` builds everything in dependency
order from the pinned commits into a pacman repository.

Which packages: see packages/repo.toml. A dependency is taken from a local
PKGBUILD first, then from the Arch/EndeavourOS repositories, then from the
AUR. Everything except ``render`` needs an Arch-based host (pacman, makepkg,
repo-add); ``build`` runs makepkg as an unprivileged user (``--user``) and
installs build dependencies with pacman, so it belongs in a throwaway
container or a clean chroot (``build.sh --container`` does this).
"""

from __future__ import annotations

import argparse
import fnmatch
import gzip
import hashlib
import heapq
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .. import __version__, pacmanconf, paths, util
from ..branding import Branding, load as load_branding
from ..profiles import read_list
from . import stage

AUR = "https://aur.archlinux.org"
LOCK_FILE = "packages/aur.lock.json"


# ---------------------------------------------------------------------------
# Package metadata
# ---------------------------------------------------------------------------


def dep_name(dep: str) -> str:
    """'python>=3.11' -> 'python'; 'foo: description' (optdepends) -> 'foo'."""
    return re.split(r"[<>=:]", dep.strip(), maxsplit=1)[0].strip()


@dataclass
class SrcInfo:
    pkgbase: str
    pkgnames: list[str] = field(default_factory=list)
    pkgver: str = "0"
    pkgrel: str = "1"
    epoch: str = ""
    arch: list[str] = field(default_factory=list)
    depends: list[str] = field(default_factory=list)
    makedepends: list[str] = field(default_factory=list)
    checkdepends: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)

    @property
    def version(self) -> str:
        return (f"{self.epoch}:" if self.epoch else "") + f"{self.pkgver}-{self.pkgrel}"


def parse_srcinfo(text: str) -> SrcInfo:
    """Parse makepkg's .SRCINFO. Per-package and per-architecture (x86_64)
    dependencies are merged: the build needs all of them."""
    info: SrcInfo | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        if key == "pkgbase":
            info = SrcInfo(value)
            continue
        if info is None:
            raise ValueError(".SRCINFO does not start with pkgbase")
        base_key = key.removesuffix("_x86_64")
        if key == "pkgname":
            info.pkgnames.append(value)
        elif key in ("pkgver", "pkgrel", "epoch"):
            setattr(info, key, value)
        elif key == "arch":
            info.arch.append(value)
        elif base_key in ("depends", "makedepends", "checkdepends", "provides"):
            lst = getattr(info, base_key)
            if value not in lst:
                lst.append(value)
    if info is None:
        raise ValueError("empty .SRCINFO")
    if not info.pkgnames:
        info.pkgnames = [info.pkgbase]
    return info


@dataclass
class Node:
    pkgbase: str
    origin: str  # local | aur
    info: SrcInfo
    path: str = ""  # local: PKGBUILD directory
    commit: str = ""  # aur: git commit

    def names(self) -> set[str]:
        return set(self.info.pkgnames) | {dep_name(p) for p in self.info.provides}

    def needs(self, check: bool = False) -> list[str]:
        deps = self.info.depends + self.info.makedepends + (self.info.checkdepends if check else [])
        own = self.names()
        return [d for d in dict.fromkeys(deps) if dep_name(d) not in own]


@dataclass
class Plan:
    nodes: dict[str, Node]
    order: list[str]
    unresolved: dict[str, list[str]] = field(default_factory=dict)
    excluded: list[str] = field(default_factory=list)
    from_repos: int = 0

    def describe(self) -> str:
        rows = [f"{i + 1:3d}. {base:<42} {self.nodes[base].origin:<5} {self.nodes[base].info.version}"
                for i, base in enumerate(self.order)]
        out = [f"{len(self.order)} packages to build ({self.from_repos} dependencies come from the repositories):",
               *rows]
        if self.excluded:
            out.append("Not built (licence): " + ", ".join(self.excluded))
        if self.unresolved:
            out.append("Not found anywhere:")
            out += [f"  {name} (needed by {', '.join(sorted(set(by)))})" for name, by in sorted(self.unresolved.items())]
        return "\n".join(out)


class CycleError(RuntimeError):
    pass


def resolve(wanted: Iterable[str], local: list[Node], in_repos: Callable[[list[str]], set[str]],
            aur_lookup: Callable[[list[str]], dict[str, Node]], *, exclude: Iterable[str] = (),
            check: bool = False) -> Plan:
    """Work out what to build and in which order.

    ``in_repos(names)`` returns the names the binary repositories satisfy;
    ``aur_lookup(names)`` returns {name: Node} for names the AUR provides.
    All local nodes are built; AUR nodes only when something needs them.
    """
    exclude = set(exclude)
    nodes: dict[str, Node] = {}
    provider: dict[str, str] = {}
    requested_by: dict[str, list[str]] = defaultdict(list)
    pending: deque[tuple[str, str]] = deque()
    unresolved: dict[str, list[str]] = {}
    excluded: list[str] = []
    repo_names: set[str] = set()

    def add(node: Node) -> None:
        nodes[node.pkgbase] = node
        for name in sorted(node.names()):
            provider.setdefault(name, node.pkgbase)
        for dep in node.needs(check):
            pending.append((dep, node.pkgbase))

    for node in local:
        add(node)
    for w in wanted:
        pending.append((w, "(requested)"))

    seen: set[str] = set()
    while pending:
        batch: list[str] = []
        while pending:
            raw, who = pending.popleft()
            name = dep_name(raw)
            requested_by[name].append(who)
            if name in seen or name in provider:
                continue
            seen.add(name)
            if name in exclude:
                excluded.append(name)
                continue
            batch.append(name)
        if not batch:
            break
        ok = in_repos(batch)
        repo_names |= ok
        rest = [n for n in batch if n not in ok]
        found = aur_lookup(rest) if rest else {}
        for name in rest:
            node = found.get(name)
            if node is None:
                unresolved[name] = requested_by[name]
                continue
            if node.pkgbase not in nodes:
                add(node)
            provider.setdefault(name, node.pkgbase)
    for name in unresolved:
        unresolved[name] = requested_by[name]

    # Edges: provider -> dependant.
    edges: dict[str, set[str]] = {b: set() for b in nodes}
    indeg: dict[str, int] = {b: 0 for b in nodes}
    for base, node in nodes.items():
        for dep in node.needs(check):
            p = provider.get(dep_name(dep))
            if p and p != base and base not in edges[p]:
                edges[p].add(base)
                indeg[base] += 1
    heap = [b for b, d in indeg.items() if d == 0]
    heapq.heapify(heap)
    order: list[str] = []
    while heap:
        b = heapq.heappop(heap)
        order.append(b)
        for nxt in sorted(edges[b]):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                heapq.heappush(heap, nxt)
    if len(order) != len(nodes):
        stuck = sorted(b for b, d in indeg.items() if d > 0)
        raise CycleError("dependency cycle among: " + ", ".join(stuck))
    return Plan(nodes, order, unresolved, sorted(set(excluded)), len(repo_names))


# ---------------------------------------------------------------------------
# What the distribution needs
# ---------------------------------------------------------------------------


def load_manifest(root: Path | None = None) -> dict:
    with ((root or paths.DATA_ROOT) / "packages" / "repo.toml").open("rb") as fh:
        return tomllib.load(fh)


def wanted_packages(b: Branding, root: Path | None = None) -> list[str]:
    """Every package name the repository must be able to provide."""
    root = root or paths.DATA_ROOT
    m = load_manifest(root)
    names: list[str] = []
    lists = sorted(p.stem for p in (root / "packages" / "lists").glob("*.list"))
    for pattern in m["aur"].get("lists", ["*"]):
        for lst in lists:
            if fnmatch.fnmatch(lst, pattern):
                names += read_list(lst, b)
    if m["aur"].get("gpu_stacks", True):
        with (root / "hardware" / "gpu" / "drivers.toml").open("rb") as fh:
            drivers = tomllib.load(fh)
        for stack in drivers.get("stack", {}).values():
            if stack.get("source") == "aur":
                names += stack.get("packages", []) + stack.get("packages_32bit", [])
    with (root / "ai" / "runtime" / "llama-server.toml").open("rb") as fh:
        llama = tomllib.load(fh)["packages"]
    names += [llama[k] for k in m["aur"].get("llama_backends", []) if k in llama]
    names += m["aur"].get("extra", [])
    return list(dict.fromkeys(names))


# ---------------------------------------------------------------------------
# Sources: local PKGBUILDs, the lock file, the AUR
# ---------------------------------------------------------------------------


def git_output(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def source_version(src: Path) -> tuple[str, int]:
    """(pkgver, SOURCE_DATE_EPOCH) of this checkout: <version>.r<commits>.g<hash>."""
    try:
        count = git_output(["rev-list", "--count", "HEAD"], src)
        short = git_output(["rev-parse", "--short=7", "HEAD"], src)
        epoch = int(git_output(["log", "-1", "--format=%ct"], src))
        return f"{__version__}.r{count}.g{short}", epoch
    except (OSError, subprocess.CalledProcessError, ValueError):
        return __version__, int(os.environ.get("SOURCE_DATE_EPOCH", "0"))


def tracked_files(src: Path) -> list[str]:
    try:
        out = git_output(["ls-files", "-z", "--recurse-submodules"], src)
        return sorted(f for f in out.split("\0") if f and (src / f).is_file())
    except (OSError, subprocess.CalledProcessError):
        skip = {".git", "build", "dist", "out", "work", "__pycache__", "checksums", "metadata"}
        return sorted(p.relative_to(src).as_posix() for p in src.rglob("*")
                      if p.is_file() and not skip & set(p.relative_to(src).parts))


def source_tarball(src: Path, dest: Path, prefix: str, epoch: int) -> Path:
    """A byte-for-byte reproducible .tar.gz of the tracked files (dots
    included) plus desktop/VERSION."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        def add_bytes(name: str, data: bytes, mode: int) -> None:
            ti = tarfile.TarInfo(f"{prefix}/{name}")
            ti.size, ti.mtime, ti.mode = len(data), epoch, mode
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            tar.addfile(ti, io.BytesIO(data))

        files = tracked_files(src)
        for rel in files:
            path = src / rel
            if path.is_symlink():
                ti = tarfile.TarInfo(f"{prefix}/{rel}")
                ti.type, ti.linkname, ti.mtime, ti.mode = tarfile.SYMTYPE, os.readlink(path), epoch, 0o777
                ti.uid = ti.gid = 0
                ti.uname = ti.gname = ""
                tar.addfile(ti)
                continue
            add_bytes(rel, path.read_bytes(), 0o755 if os.access(path, os.X_OK) else 0o644)
        if "desktop/VERSION" not in files:
            add_bytes("desktop/VERSION", (stage.desktop_version(src) + "\n").encode(), 0o644)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as gz:
        gz.write(buf.getvalue())
    return dest


def render(out: Path, b: Branding | None = None, src: Path | None = None) -> list[Path]:
    """Render the distribution's PKGBUILD templates into ``out/<dir>/``."""
    b = b or load_branding()
    src = src or paths.DATA_ROOT
    pkgver, epoch = source_version(src)
    rendered = []
    for tdir in load_manifest(src)["local"].get("templates", []):
        tsrc = src / "packages" / "pkgbuild" / tdir
        target = out / tdir
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        extra = {"PKGVER": pkgver, "SOURCE_DATE_EPOCH": str(epoch)}
        if tdir == "distro":
            tarball = source_tarball(src, target / f"{b.id}-{pkgver}.tar.gz", f"{b.id}-{pkgver}", epoch)
            extra["SOURCE_SHA256"] = hashlib.sha256(tarball.read_bytes()).hexdigest()
        for f in sorted(tsrc.iterdir()):
            name = b.render(f.name.removesuffix(".in"))
            if f.suffix == ".in":
                (target / name).write_text(b.render(f.read_text(), extra))
            else:
                shutil.copyfile(f, target / name)
        rendered.append(target)
    return rendered


def printsrcinfo(pkgdir: Path, user: str = "") -> SrcInfo:
    cached = pkgdir / ".SRCINFO"
    if cached.is_file() and cached.stat().st_mtime >= (pkgdir / "PKGBUILD").stat().st_mtime:
        return parse_srcinfo(cached.read_text())
    cmd = ["makepkg", "--printsrcinfo"]
    if user and os.geteuid() == 0:
        cmd = ["runuser", "-u", user, "--", *cmd]
    text = subprocess.run(cmd, cwd=pkgdir, capture_output=True, text=True, check=True).stdout
    return parse_srcinfo(text)


def local_nodes(out: Path, src: Path | None = None, user: str = "") -> list[Node]:
    src = src or paths.DATA_ROOT
    m = load_manifest(src)
    dirs = [out / t for t in m["local"].get("templates", [])]
    for pattern in m["local"].get("dirs", []):
        dirs += sorted(p for p in src.glob(pattern) if (p / "PKGBUILD").is_file())
    nodes = []
    for d in dirs:
        info = printsrcinfo(d, user)
        nodes.append(Node(info.pkgbase, "local", info, path=str(d)))
    return nodes


def _rpc(path: str, params: list[tuple[str, str]] | None = None) -> dict:
    url = f"{AUR}/rpc/v5/{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 - fixed https host
        data = json.load(resp)
    if data.get("type") == "error":
        raise RuntimeError(f"AUR: {data.get('error')}")
    return data


def _node_from_rpc(r: dict) -> Node:
    info = SrcInfo(r["PackageBase"], [r["Name"]], *r["Version"].rsplit("-", 1))
    if ":" in info.pkgver:
        info.epoch, info.pkgver = info.pkgver.split(":", 1)
    info.depends = r.get("Depends", [])
    info.makedepends = r.get("MakeDepends", [])
    info.checkdepends = r.get("CheckDepends", [])
    info.provides = r.get("Provides", [])
    return Node(info.pkgbase, "aur", info)


def aur_rpc_lookup(names: list[str]) -> dict[str, Node]:
    """Look names up on the AUR, by package name and then by provides."""
    found: dict[str, Node] = {}
    for i in range(0, len(names), 100):
        chunk = names[i:i + 100]
        for r in _rpc("info", [("arg[]", n) for n in chunk])["results"]:
            found[r["Name"]] = _node_from_rpc(r)
    for name in [n for n in names if n not in found]:
        hits = [r for r in _rpc(f"search/{urllib.parse.quote(name)}", [("by", "provides")])["results"]
                if r.get("Name") != name]
        if not hits:
            continue
        # The most used provider, deterministic on ties.
        best = sorted(hits, key=lambda r: (-r.get("NumVotes", 0), r["Name"]))[0]
        info = _rpc("info", [("arg[]", best["Name"])])["results"]
        if info:
            found[name] = _node_from_rpc(info[0])
    return found


def aur_head(pkgbase: str) -> str:
    out = subprocess.run(["git", "ls-remote", f"{AUR}/{pkgbase}.git", "HEAD"], capture_output=True, text=True,
                         check=True).stdout.split()
    if not out:
        raise RuntimeError(f"AUR git repository for {pkgbase} is empty")
    return out[0]


def clone_aur(pkgbase: str, commit: str, workdir: Path) -> Path:
    dest = workdir / "aur" / pkgbase
    if not (dest / ".git").is_dir():
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", f"{AUR}/{pkgbase}.git", str(dest)], check=True)
    else:
        subprocess.run(["git", "-C", str(dest), "fetch", "--quiet", "origin"], check=True)
    subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", "--force", commit], check=True)
    subprocess.run(["git", "-C", str(dest), "clean", "-qfdx"], check=True)
    return dest


def locked_lookup(lock: dict, workdir: Path) -> Callable[[list[str]], dict[str, Node]]:
    """AUR lookups answered from the pinned commits (reproducible builds)."""
    by_name: dict[str, Node] = {}
    for base, entry in sorted(lock.get("packages", {}).items()):
        d = clone_aur(base, entry["commit"], workdir)
        info = parse_srcinfo((d / ".SRCINFO").read_text())
        node = Node(base, "aur", info, path=str(d), commit=entry["commit"])
        for name in sorted(node.names()):
            by_name.setdefault(name, node)
        for name in entry.get("for", []):
            by_name.setdefault(name, node)

    def lookup(names: list[str]) -> dict[str, Node]:
        return {n: by_name[n] for n in names if n in by_name}

    return lookup


def pacman_lookup(conf: Path) -> Callable[[list[str]], set[str]]:
    """Which names the binary repositories satisfy (by name or provides)."""

    def check(names: list[str]) -> set[str]:
        res = subprocess.run(["pacman", "--config", str(conf), "-Spdd", "--noconfirm", "--print-format", "%n", *names],
                             capture_output=True, text=True)
        missing = set(re.findall(r"target not found: (\S+)", res.stderr + res.stdout))
        return {n for n in names if n not in missing}

    return check


def build_conf(b: Branding, repo: Path, workdir: Path, multilib: bool = True) -> Path:
    """pacman.conf of the build host: the repository being built first."""
    conf = workdir / "pacman-build.conf"
    text = pacmanconf.render("build", b, archive_date=os.environ.get("ARCHIVE_DATE", ""), multilib=multilib)
    local = f"[{b.repo_name}-build]\nSigLevel = Optional TrustAll\nServer = file://{repo.resolve()}\n\n"
    text = text.replace("[endeavouros]", local + "[endeavouros]", 1)
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(text)
    return conf


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


class Builder:
    def __init__(self, b: Branding, repo: Path, workdir: Path, conf: Path, user: str, runner: util.Runner,
                 sign_key: str = ""):
        self.b = b
        self.repo = repo.resolve()
        self.workdir = workdir.resolve()
        self.conf = conf
        self.user = user
        self.runner = runner
        self.sign_key = sign_key
        self.db = self.repo / f"{b.repo_name}.db.tar.gz"
        self.pacman_wrapper = self.workdir / "pacman-build"

    def prepare(self) -> None:
        self.repo.mkdir(parents=True, exist_ok=True)
        if not self.db.exists():
            self.runner.run(["repo-add", str(self.db)])
        # makepkg runs pacman through $PACMAN; this one knows about the new repository.
        self.pacman_wrapper.write_text(f'#!/bin/sh\nexec pacman --config "{self.conf}" "$@"\n')
        self.pacman_wrapper.chmod(0o755)
        self.runner.run(["pacman", "--config", str(self.conf), "-Sy"])

    def built(self, node: Node) -> list[Path]:
        return sorted(p for name in node.info.pkgnames
                      for p in self.repo.glob(f"{name}-{node.info.version}-*.pkg.tar.*") if not p.name.endswith(".sig"))

    def build(self, node: Node, force: bool = False) -> list[Path]:
        if self.built(node) and not force:
            return []
        src = Path(node.path)
        work = self.workdir / "src" / node.pkgbase
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(src, work, ignore=shutil.ignore_patterns(".git", "src", "pkg"))
        out = self.workdir / "out" / node.pkgbase
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        if self.user and os.geteuid() == 0:
            self.runner.run(["chown", "-R", f"{self.user}:{self.user}", str(work), str(out)])
        env = ["env", f"PACMAN={self.pacman_wrapper}", f"PKGDEST={out}", f"SRCDEST={self.workdir / 'sources'}",
               f"BUILDDIR={self.workdir / 'makepkg'}"]
        if "SOURCE_DATE_EPOCH" in os.environ:
            env.append(f"SOURCE_DATE_EPOCH={os.environ['SOURCE_DATE_EPOCH']}")
        cmd = [*env, "makepkg", "--syncdeps", "--noconfirm", "--cleanbuild", "--clean", "--force", "--noprogressbar"]
        if node.origin == "aur":
            cmd.append("--nocheck")  # upstream test suites are not the distribution's to run
        if self.sign_key:
            cmd += ["--sign", "--key", self.sign_key]
        if self.user and os.geteuid() == 0:
            cmd = ["runuser", "-u", self.user, "--", *cmd]
        for d in ("sources", "makepkg"):
            (self.workdir / d).mkdir(parents=True, exist_ok=True)
            if self.user and os.geteuid() == 0:
                self.runner.run(["chown", f"{self.user}:{self.user}", str(self.workdir / d)])
        self.runner.run(cmd, cwd=str(work))
        pkgs = sorted(p for p in out.glob("*.pkg.tar.*") if not p.name.endswith(".sig"))
        if not pkgs and not self.runner.dry_run:
            raise util.CommandError(cmd, 0, f"{node.pkgbase}: makepkg produced no packages")
        for p in out.iterdir():
            shutil.copyfile(p, self.repo / p.name)
        add = ["repo-add", "--new", "--remove", "--prevent-downgrade"]
        if self.sign_key:
            add += ["--sign", "--key", self.sign_key]
        self.runner.run([*add, str(self.db), *[str(self.repo / p.name) for p in pkgs]])
        self.runner.run(["pacman", "--config", str(self.conf), "-Sy"])
        return [self.repo / p.name for p in pkgs]


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _load_lock(src: Path) -> dict:
    path = src / LOCK_FILE
    return json.loads(path.read_text()) if path.is_file() else {"packages": {}}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="distrokit.build.packages", description=__doc__.splitlines()[0])
    p.add_argument("action", choices=["render", "lock", "plan", "build"])
    p.add_argument("--out", default="build/pkgbuild", help="where PKGBUILDs are rendered")
    p.add_argument("--work", default="build/packages", help="scratch directory")
    p.add_argument("--repo", default="build/repo", help="pacman repository to build into")
    p.add_argument("--user", default=os.environ.get("BUILD_USER", "builder"), help="unprivileged build user")
    p.add_argument("--only", nargs="*", default=[], help="build only these package bases")
    p.add_argument("--force", action="store_true", help="rebuild packages already in the repository")
    p.add_argument("--no-multilib", action="store_true")
    p.add_argument("--sign", default=os.environ.get("GPGKEY", ""), help="GPG key to sign packages and the database")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    b = load_branding()
    src = paths.DATA_ROOT
    out, work, repo = Path(a.out), Path(a.work), Path(a.repo)

    rendered = render(out, b, src)
    if a.action == "render":
        for r in rendered:
            print(r)
        return 0

    conf = build_conf(b, repo, work, multilib=not a.no_multilib)
    runner = util.Runner(log=print, dry_run=a.dry_run)
    exclude = load_manifest(src)["aur"].get("exclude", [])
    local = local_nodes(out, src, a.user)
    in_repos = pacman_lookup(conf)
    if not repo.joinpath(f"{b.repo_name}.db.tar.gz").exists():
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["repo-add", str(repo / f"{b.repo_name}.db.tar.gz")], check=True)
    subprocess.run(["pacman", "--config", str(conf), "-Sy"], check=False)

    if a.action == "lock":
        plan = resolve(wanted_packages(b, src), local, in_repos, aur_rpc_lookup, exclude=exclude)
        print(plan.describe())
        lock = {"generated_by": f"distrokit {__version__}", "packages": {}}
        for base in plan.order:
            node = plan.nodes[base]
            if node.origin != "aur":
                continue
            wanted_for = sorted(n for n in node.names() if n not in node.info.pkgnames)
            lock["packages"][base] = {"version": node.info.version, "commit": aur_head(base),
                                      **({"for": wanted_for} if wanted_for else {})}
        (src / LOCK_FILE).write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
        print(f"wrote {LOCK_FILE} ({len(lock['packages'])} AUR packages)")
        return 1 if plan.unresolved else 0

    lookup = locked_lookup(_load_lock(src), work)
    plan = resolve(wanted_packages(b, src), local, in_repos, lookup, exclude=exclude)
    print(plan.describe())
    if plan.unresolved:
        print(f"\nSome packages are neither in the repositories nor in {LOCK_FILE}. "
              "Run `scripts/build-packages.sh --update-lock` (or remove them from the package lists).")
        return 1
    if a.action == "plan":
        return 0

    builder = Builder(b, repo, work, conf, a.user, runner, a.sign)
    builder.prepare()
    for base in plan.order:
        if a.only and base not in a.only:
            continue
        node = plan.nodes[base]
        made = builder.build(node, force=a.force)
        print(f"{base}: " + (", ".join(p.name for p in made) if made else "already built"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
