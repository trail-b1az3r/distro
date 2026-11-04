"""The CI package sources: nexora-experiments (main) and nexora-experiments-extra (beta), their pacman.conf blocks,
the per-component update plan and the published packages.json."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from distrokit import experiments, pacmanconf
from distrokit.branding import Branding

ROOT = Path(__file__).resolve().parents[2]
B = Branding({"DISTRO_ID": "nexora", "DISTRO_CLI": "nexora", "DISTRO_REPO_NAME": "nexora",
              "DISTRO_HOME_URL": "https://github.com/trail-b1az3r/distro"})
CONF = "[options]\nArchitecture = auto\n\n[nexora]\nServer = https://example/nexora\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n"


def test_components_and_their_packages():
    assert experiments.COMPONENTS[:6] == ("core", "branding", "desktop", "welcome", "installer", "ai")
    assert experiments.packages("core", B) == ("nexora-core",)
    assert experiments.packages("nmx", B) == ("nmx",)
    assert experiments.packages("touchd", B) == ("touchd-dkms",)
    assert experiments.packages("fonts", B) == ("nexora-fonts-google-sans-flex",)


def test_sources_go_after_every_repository():
    text = pacmanconf.set_experiments_repo(CONF, True, B, experiments.MAIN)
    text = pacmanconf.set_experiments_repo(text, True, B, experiments.EXTRA)
    heads = [line for line in text.splitlines() if line.startswith("[")]
    assert heads == ["[options]", "[nexora]", "[core]", "[nexora-experiments]", "[nexora-experiments-extra]"]
    assert "Server = https://github.com/trail-b1az3r/distro/releases/download/nexora-experiments-extra" in text
    assert pacmanconf.set_experiments_repo(text, True, B, experiments.EXTRA) == text, "idempotent"
    off = pacmanconf.set_experiments_repo(text, False, B, experiments.EXTRA)
    assert "[nexora-experiments-extra]" not in off and "[nexora-experiments]" in off
    assert pacmanconf.set_experiments_repo(off, False, B, experiments.MAIN).strip() == CONF.strip()


def test_old_placement_before_the_stable_repository_moves_to_the_end():
    old = CONF.replace("[nexora]\n", "[nexora-experiments]\nSigLevel = Optional TrustAll\nServer = x\n\n[nexora]\n")
    heads = [line for line in pacmanconf.set_experiments_repo(old, True, B).splitlines() if line.startswith("[")]
    assert heads == ["[options]", "[nexora]", "[core]", "[nexora-experiments]"]


@pytest.fixture
def system(tmp_path, monkeypatch):
    conf = tmp_path / "pacman.conf"
    conf.write_text(CONF)
    monkeypatch.setattr(experiments, "config_path", lambda branding=None: tmp_path / "experiments.json")
    monkeypatch.setattr(experiments.os, "geteuid", lambda: 0)
    return conf


def test_enable_from_main_or_beta(system):
    enable = lambda *a, **k: experiments.set_enabled(*a, branding=B, pacman_conf=system, **k)  # noqa: E731
    assert enable("enable", "nmx") == ["nmx"]
    assert enable("enable", "hyprland-plus", extra=True) == ["nmx", "hyprland-plus"]
    assert experiments.read_config(B) == {"components": ["nmx"], "extra": ["hyprland-plus"]}
    assert "[nexora-experiments]" in system.read_text() and "[nexora-experiments-extra]" in system.read_text()
    enable("enable", "nmx", extra=True)                          # one source per component: moves to beta
    assert experiments.read_config(B) == {"components": [], "extra": ["nmx", "hyprland-plus"]}
    assert "[nexora-experiments]\n" not in system.read_text()
    enable("disable", "nmx", extra=True)
    assert experiments.read_config(B)["extra"] == ["hyprland-plus"]
    enable("disable", "all")
    assert experiments.read_enabled(B) == [] and "experiments" not in system.read_text()


def test_needs_root(system, monkeypatch):
    monkeypatch.setattr(experiments.os, "geteuid", lambda: 1000)
    with pytest.raises(experiments.ExperimentError, match="sudo nexora experiments enable nmx --extra"):
        experiments.set_enabled("enable", "nmx", B, extra=True, pacman_conf=system)


def test_plan_takes_only_enabled_installed_packages(system, monkeypatch):
    (system.parent / "experiments.json").write_text(json.dumps({"components": ["nmx", "core"], "extra": ["mdxl"]}))
    outputs = {
        ("pacman", "-Q"): "nmx 0.1.0-1\nnexora-core 26.11.0.1.4-1\nmdxl 1.0-1\nhyprland-plus 0.57.0.p3-1\n",
        ("pacman", "-Sl", "nexora-experiments"): "nexora-experiments nmx 0.2.0-1\n"
                                                 "nexora-experiments nexora-core 26.11.0.1.4-1 [installed]\n"
                                                 "nexora-experiments hyprland-plus 0.57.1.p1-1\n",
        ("pacman", "-Sl", "nexora-experiments-extra"): "nexora-experiments-extra mdxl 1.1-1\n"
                                                       "nexora-experiments-extra nmx 9.9-1\n",
    }
    monkeypatch.setattr(experiments, "_run", lambda command, timeout: outputs[tuple(command)])
    monkeypatch.setattr(experiments, "newer", lambda a, b: a != b)
    assert experiments.plan(B) == [("nexora-experiments-extra", "mdxl", "1.0-1", "1.1-1"),
                                   ("nexora-experiments", "nmx", "0.1.0-1", "0.2.0-1")]
    assert experiments.check(B) == ["mdxl 1.0-1 -> 1.1-1 (nexora-experiments-extra)",
                                    "nmx 0.1.0-1 -> 0.2.0-1 (nexora-experiments)"]

    class Runner:
        def run(self, command, terminal, check):
            self.command = command
            return subprocess.CompletedProcess(command, 0)

    runner = Runner()
    assert experiments.apply(runner, B, interactive=False) == ["mdxl 1.1-1", "nmx 0.2.0-1"]
    assert runner.command[-2:] == ["nexora-experiments-extra/mdxl", "nexora-experiments/nmx"], "by name, per source"
    assert "-Syu" not in runner.command


# ── packages.json ────────────────────────────────────────────────────────────────────────────────────────────────

def fake_package(directory: Path, name: str, version: str, arch: str) -> Path:
    info = f"# Generated by makepkg\npkgname = {name}\npkgbase = {name}\npkgver = {version}\narch = {arch}\n" \
           f"builddate = 1788000000\ndepend = glibc\n".encode()
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        member = tarfile.TarInfo(".PKGINFO")
        member.size = len(info)
        tar.addfile(member, io.BytesIO(info))
    path = directory / f"{name}-{version}-{arch}.pkg.tar.zst"
    path.write_bytes(subprocess.run(["zstd", "-q", "-c"], input=raw.getvalue(), capture_output=True, check=True).stdout)
    return path


@pytest.mark.skipif(not shutil.which("zstd"), reason="zstd is not installed")
def test_manifest(tmp_path):
    pkgs = tmp_path / "pkgs"
    pkgs.mkdir()
    fake_package(pkgs, "nexora-fonts-google-sans-flex", "r1.251aa5a-1", "any")
    fake_package(pkgs, "nmx", "0.2.0-1", "any")
    fake_package(pkgs, "aquamarine", "0.16.0-1", "x86_64")
    out = tmp_path / "packages.json"
    subprocess.run([sys.executable, str(ROOT / "scripts/experiments-manifest.py"), str(pkgs), str(out),
                    "--repo", "nexora-experiments-extra", "--branch", "beta", "--commit", "abc123"], check=True)
    data = json.loads(out.read_text())
    assert data["repository"] == "nexora-experiments-extra" and data["beta"] and data["branch"] == "beta"
    assert data["components"] == ["fonts", "nmx"]
    assert [(p["name"], p["version"], p["arch"], p["component"]) for p in data["packages"]] == [
        ("aquamarine", "0.16.0-1", "x86_64", ""),
        ("nexora-fonts-google-sans-flex", "r1.251aa5a-1", "any", "fonts"),
        ("nmx", "0.2.0-1", "any", "nmx"),
    ]


def test_manifest_refuses_a_non_package(tmp_path):
    (tmp_path / "broken-1-1-any.pkg.tar.gz").write_bytes(b"")
    run = subprocess.run([sys.executable, str(ROOT / "scripts/experiments-manifest.py"), str(tmp_path),
                          str(tmp_path / "out.json")], capture_output=True, text=True)
    assert run.returncode != 0


def test_ci_publishes_both_sources():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "--print-format" not in ci, "pacman -Qp takes no --print-format"
    assert "scripts/experiments-manifest.py" in ci
    assert "'nexora-experiments-extra'" in ci and 'gh release upload "$REPO"' in ci
