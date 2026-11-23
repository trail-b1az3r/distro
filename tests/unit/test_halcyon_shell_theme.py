"""Halcyon shell-theme installer regression tests."""
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("shell", ["fish", "spire", "zsh"])
def test_theme_installer_is_idempotent_and_preserves_existing_prompt(tmp_path, shell):
    root = Path(__file__).resolve().parents[2]
    installer = root / "scripts/distro-install-w-halcyon_desktop_shell-theme"
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["ZDOTDIR"] = str(home)

    if shell in ("fish", "spire"):
        prompt = home / ".config/fish/functions/fish_prompt.fish"
        prompt.parent.mkdir(parents=True)
        prompt.write_text("# existing prompt\n")
        if shell == "spire":
            cfg = home / ".config/spire/spire.conf"
            cfg.parent.mkdir(parents=True)
            cfg.write_text("colorscheme = default\nfish_config = no\nprompt.use_fish_prompt = no\n")
    else:
        zshrc = home / ".zshrc"
        zshrc.write_text("# existing zshrc\n")
        theme = home / ".config/halcyon-shell/zsh-theme.zsh"
        theme.parent.mkdir(parents=True)
        theme.write_text("# existing theme\n")

    subprocess.run(["bash", str(installer), shell], env=env, check=True, capture_output=True, text=True)
    # The legacy misspelling remains a supported entry point.
    legacy = root / "scripts/distro-install-w-halcyon_dektop_shell-theme"
    subprocess.run(["bash", str(legacy), shell], env=env, check=True, capture_output=True, text=True)
    snapshot = {}
    if shell in ("fish", "spire"):
        snapshot[prompt] = prompt.read_text()
        if shell == "spire":
            cfg = home / ".config/spire/spire.conf"
            snapshot[cfg] = cfg.read_text()
    else:
        snapshot[zshrc] = zshrc.read_text()
        snapshot[theme] = theme.read_text()
    subprocess.run(["bash", str(installer), shell], env=env, check=True, capture_output=True, text=True)
    assert all(path.read_text() == contents for path, contents in snapshot.items())

    if shell in ("fish", "spire"):
        assert prompt.read_text().startswith("# Halcyon prompt")
        assert (prompt.with_name(prompt.name + ".bak")).read_text() == "# existing prompt\n"
        if shell == "spire":
            cfg = home / ".config/spire/spire.conf"
            assert "fish_config = yes" in cfg.read_text()
            assert "prompt.use_fish_prompt = yes" in cfg.read_text()
            assert "colorscheme = default" in cfg.read_text()
            assert (cfg.with_name(cfg.name + ".bak")).read_text() == "colorscheme = default\nfish_config = no\nprompt.use_fish_prompt = no\n"
    else:
        assert zshrc.read_text().count("halcyon-shell/zsh-theme.zsh") == 1
        assert zshrc.with_name(zshrc.name + ".bak").read_text() == "# existing zshrc\n"
        assert theme.read_text().startswith("# Halcyon Zsh prompt")
        assert theme.with_name(theme.name + ".bak").read_text() == "# existing theme\n"


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
