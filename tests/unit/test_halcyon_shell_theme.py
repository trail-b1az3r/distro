"""Halcyon shell-theme installer regression tests."""
import os
import subprocess
from pathlib import Path

import pytest


def _fake_halcyon(home: Path) -> Path:
    """A stand-in halcyon-theme that records how it was called."""
    tool = home / ".config/hypr/hyprland/halcyon/halcyon-theme"
    tool.parent.mkdir(parents=True)
    tool.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$HOME/called"\n')
    tool.chmod(0o755)
    return home / "called"


@pytest.mark.parametrize("shell", ["halcyon", "glass", "summit", "macshell", "noctalia", "auto"])
def test_it_picks_the_hyprland_shell_halcyon_runs(tmp_path, shell):
    root = Path(__file__).resolve().parents[2]
    home = tmp_path / "home"
    called = _fake_halcyon(home)
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), DISTRO_ALLOW_ROOT="1")
    for command in ("distro-install-w-halcyon_desktop_shell-theme", "distro-install-w-halcyon_dektop_shell-theme"):
        subprocess.run(["bash", str(root / "scripts" / command), shell, "--no-install"], env=env, check=True,
                       capture_output=True, text=True)
        assert called.read_text().split() == ["shell", shell]


def test_login_shells_are_not_its_business(tmp_path):
    root = Path(__file__).resolve().parents[2]
    home = tmp_path / "home"
    _fake_halcyon(home)
    env = dict(os.environ, HOME=str(home), DISTRO_ALLOW_ROOT="1")
    for login_shell in ("fish", "zsh", "spire"):
        result = subprocess.run(["bash", str(root / "scripts/distro-install-w-halcyon_desktop_shell-theme"), login_shell],
                                env=env, capture_output=True, text=True, check=False)
        assert result.returncode == 2
    assert not (home / ".config/fish").exists() and not (home / ".zshrc").exists()


def test_it_needs_halcyon(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, HOME=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path / ".config"), DISTRO_ALLOW_ROOT="1")
    result = subprocess.run(["bash", str(root / "scripts/distro-install-w-halcyon_desktop_shell-theme"), "glass",
                             "--no-install"], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 1 and "Halcyon is not set up" in result.stderr


def test_theme_installer_stages_correct_command_and_legacy_alias(tmp_path):
    from distrokit.branding import load as load_branding
    from distrokit.build import stage

    b = load_branding()
    stage.Stage(tmp_path, b).run("desktop")
    canonical = tmp_path / "usr/bin/distro-install-w-halcyon_desktop_shell-theme"
    legacy = tmp_path / "usr/bin/distro-install-w-halcyon_dektop_shell-theme"
    assert canonical.is_file() and canonical.stat().st_mode & 0o111
    assert legacy.is_symlink()
    assert legacy.resolve() == canonical.resolve()


def test_theme_installer_reports_correct_command_name(tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    result = subprocess.run(["bash", str(root / "scripts/distro-install-w-halcyon_desktop_shell-theme"), "invalid"],
                           env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "distro-install-w-halcyon_desktop_shell-theme" in result.stderr
