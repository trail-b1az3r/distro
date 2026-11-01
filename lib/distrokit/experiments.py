"""Opt-in installation of packages from the latest successful Nexora CI run.

CI artifacts are experimental snapshots, not the signed rolling repository. They
are installed explicitly with pacman -U and never change pacman.conf.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from . import util
from .branding import Branding, load as load_branding

API = "https://api.github.com"
COMPONENTS = ("core", "branding", "desktop", "welcome", "installer", "ai")
DEPENDENCIES = {
    "core": ("core",),
    "branding": ("branding",),
    "desktop": ("core", "branding", "desktop"),
    "welcome": ("core", "welcome"),
    "installer": ("core", "installer"),
    "ai": ("core", "ai"),
}
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024 * 1024


class ExperimentError(RuntimeError):
    pass


def config_path(branding: Branding | None = None) -> Path:
    b = branding or load_branding()
    return Path("/etc") / b.id / "experiments.json"


def read_enabled(branding: Branding | None = None) -> list[str]:
    path = config_path(branding)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise ExperimentError(f"cannot read {path}: {exc}") from exc
    enabled = data.get("components", []) if isinstance(data, dict) else []
    if not isinstance(enabled, list) or any(x not in COMPONENTS for x in enabled):
        raise ExperimentError(f"{path} contains an invalid component list")
    return list(dict.fromkeys(enabled))


def set_enabled(action: str, requested: str, branding: Branding | None = None) -> list[str]:
    b = branding or load_branding()
    if os.geteuid() != 0:
        raise ExperimentError(f"changing experimental sources needs root: sudo {b.cli} experiments {action} {requested}")
    if requested == "all":
        selected = list(COMPONENTS)
    elif requested in COMPONENTS:
        selected = [requested]
    else:
        raise ExperimentError(f"unknown component {requested!r}; choose all or: {', '.join(COMPONENTS)}")
    enabled = set(read_enabled(b))
    if action == "enable":
        enabled.update(selected)
    elif action == "disable":
        enabled.difference_update(selected)
    else:
        raise ExperimentError(f"unknown action {action!r}")
    result = [c for c in COMPONENTS if c in enabled]
    path = config_path(b)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"components": result}, indent=2) + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    return result


def _repo(branding: Branding) -> tuple[str, str]:
    url = branding.get("DISTRO_HOME_URL", "")
    parsed = urllib.parse.urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if parsed.netloc.lower() not in ("github.com", "www.github.com") or len(parts) < 2:
        raise ExperimentError("DISTRO_HOME_URL must point to the Nexora GitHub repository")
    return parts[0], parts[1].removesuffix(".git")


def _headers(accept: str = "application/vnd.github+json") -> dict[str, str]:
    headers = {
        "Accept": accept,
        "User-Agent": "Nexora-Experiments",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read(4 * 1024 * 1024 + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise ExperimentError(f"GitHub request failed: {exc}") from exc


def _download(url: str, destination: Path) -> None:
    req = urllib.request.Request(url, headers=_headers("application/octet-stream"))
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=180) as response, destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_ARTIFACT_BYTES:
                    raise ExperimentError("CI package artifact exceeds the 8 GiB safety limit")
                output.write(chunk)
    except (OSError, urllib.error.URLError) as exc:
        destination.unlink(missing_ok=True)
        raise ExperimentError(f"CI artifact download failed: {exc}") from exc


def latest_packages_artifact(branding: Branding | None = None) -> tuple[int, int, str]:
    """Return (workflow run id, artifact id, run head SHA) for latest successful CI."""
    b = branding or load_branding()
    owner, repo = _repo(b)
    base = f"{API}/repos/{owner}/{repo}"
    query = urllib.parse.urlencode({"branch": "main", "status": "success", "per_page": 20})
    runs = json.loads(_request(f"{base}/actions/workflows/ci.yml/runs?{query}"))
    for run in runs.get("workflow_runs", []):
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            continue
        run_id = int(run["id"])
        artifacts = json.loads(_request(f"{base}/actions/runs/{run_id}/artifacts?per_page=100"))
        for artifact in artifacts.get("artifacts", []):
            if artifact.get("name") == "packages" and not artifact.get("expired"):
                return run_id, int(artifact["id"]), str(run.get("head_sha", ""))
    raise ExperimentError("no unexpired 'packages' artifact was found in the latest 20 successful main-branch CI runs")


def _safe_extract_packages(archive: Path, destination: Path, selected: set[str], branding: Branding) -> list[Path]:
    prefix = f"{branding.id}-"
    wanted = {f"{branding.id}-{name}" for name in selected}
    found: dict[str, Path] = {}
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = Path(info.filename).name
            if not name.startswith(prefix) or not name.endswith(".pkg.tar.zst"):
                continue
            package = next((p for p in wanted if name.startswith(p + "-")), None)
            if not package:
                continue
            if info.file_size > 1024 * 1024 * 1024:
                raise ExperimentError(f"package {name} exceeds the 1 GiB safety limit")
            target = destination / name
            with zf.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            found[package] = target
    missing = sorted(wanted - set(found))
    if missing:
        raise ExperimentError("CI artifact is missing selected packages: " + ", ".join(missing))
    return [found[p] for p in sorted(wanted)]


def fetch_packages(selected: list[str], branding: Branding | None = None) -> tuple[list[Path], int, str]:
    b = branding or load_branding()
    run_id, artifact_id, sha = latest_packages_artifact(b)
    owner, repo = _repo(b)
    url = f"{API}/repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip"
    cache = Path.home() / ".cache" / b.id / "experiments" / str(run_id)
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / "packages.zip"
    if not archive.exists() or not zipfile.is_zipfile(archive):
        archive.unlink(missing_ok=True)
        tmp = archive.with_suffix(".zip.tmp")
        _download(url, tmp)
        if not zipfile.is_zipfile(tmp):
            tmp.unlink(missing_ok=True)
            raise ExperimentError("GitHub returned an invalid CI artifact ZIP")
        os.replace(tmp, archive)
    expanded = {dep for component in selected for dep in DEPENDENCIES[component]}
    packages = _safe_extract_packages(archive, cache / "pkg", expanded, b)
    return packages, run_id, sha


def _packages_newer_than_installed(packages: list[Path]) -> list[Path]:
    """Never replace a stable installed package with an older CI snapshot."""
    pending = []
    for package in packages:
        query = subprocess.run(["pacman", "-Qp", str(package)], capture_output=True, text=True, check=False)
        if query.returncode:
            raise ExperimentError(f"cannot read package metadata from {package.name}: {query.stderr.strip()}")
        fields = query.stdout.split()
        if len(fields) != 2:
            raise ExperimentError(f"unexpected pacman package metadata for {package.name}")
        name, candidate = fields
        installed = subprocess.run(["pacman", "-Q", name], capture_output=True, text=True, check=False)
        if installed.returncode:
            pending.append(package)
            continue
        current_fields = installed.stdout.split()
        if len(current_fields) != 2:
            pending.append(package)
            continue
        comparison = subprocess.run(["vercmp", current_fields[1], candidate], capture_output=True, text=True, check=False)
        if comparison.returncode:
            raise ExperimentError("vercmp is required to compare experimental package versions")
        if comparison.stdout.strip() == "-1":
            pending.append(package)
    return pending


def apply(runner: util.Runner, branding: Branding | None = None, *, interactive: bool = True) -> list[str]:
    b = branding or load_branding()
    enabled = read_enabled(b)
    if not enabled:
        return []
    components = [c for c in COMPONENTS if c in enabled]
    try:
        packages, run_id, sha = fetch_packages(components, b)
    except (ExperimentError, OSError, zipfile.BadZipFile) as exc:
        raise ExperimentError(str(exc)) from exc
    if not packages:
        return []
    packages = _packages_newer_than_installed(packages)
    if not packages:
        return []
    print(f"Experimental Nexora packages: successful CI run #{run_id} ({sha[:12] or 'unknown commit'})")
    cmd = ["pacman", "-U", "--needed", *map(str, packages)]
    if not interactive:
        cmd.append("--noconfirm")
    if os.geteuid() != 0:
        cmd.insert(0, "sudo")
    result = runner.run(cmd, terminal=interactive)
    if result.returncode:
        raise ExperimentError(f"pacman could not install experimental packages (exit {result.returncode})")
    return [p.name for p in packages]


def check(branding: Branding | None = None) -> list[str]:
    b = branding or load_branding()
    enabled = read_enabled(b)
    if not enabled:
        return []
    components = [c for c in COMPONENTS if c in enabled]
    packages, _, _ = fetch_packages(components, b)
    return [p.name for p in _packages_newer_than_installed(packages)]


def status(branding: Branding | None = None) -> list[str]:
    enabled = read_enabled(branding)
    return enabled
