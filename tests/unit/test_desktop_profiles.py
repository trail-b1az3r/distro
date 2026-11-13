"""Desktop profile selection and staged upstream setup smoke tests."""
import subprocess
from pathlib import Path

from distrokit.profiles import load_profiles, select_packages


def packages(overrides=None):
    return set(select_packages(load_profiles()["minimal"], overrides=overrides or {}).packages)


def test_welcome_backend_exposes_multi_profile_selection():
    source = (Path(__file__).resolve().parents[2] / "lib" / "distrokit" / "gui" / "welcome_app.py").read_text()
    assert 'def desktopProfiles(self)' in source
    assert 'def saveDesktopProfiles(self, profile_ids: list)' in source
    assert 'allowed = {"ml4w", "hyde", "sekaipop"}' in source


def test_profile_installer_prefers_user_selection_and_falls_back_to_system_config():
    script = (Path(__file__).resolve().parents[2] / "desktop" / "profiles" / "install-selected.sh").read_text()
    assert 'XDG_CONFIG_HOME:-$HOME/.config' in script
    assert 'CONFIG=/etc/distro-desktop-profiles.conf' in script

def test_halcyon_remains_the_default_desktop():
    selected = packages()
    assert "illogical-impulse-hyprland" in selected
    assert "illogical-impulse-quickshell-git" in selected
    assert "waybar" not in selected


def test_primary_external_desktop_is_selected_with_halcyon_fallback():
    selected = packages({"desktop_environment": "ml4w"})
    assert "waybar" in selected
    assert "illogical-impulse-hyprland" in selected


def test_additional_desktops_can_be_installed_together():
    selected = packages({"desktop_ml4w": True, "desktop_sekaipop": True, "desktop_hyde": True})
    assert "illogical-impulse-hyprland" in selected
    assert "waybar" in selected
    assert "qt6-shadertools" in selected


def test_networkmanager_assist_is_optional_and_does_not_replace_nmx():
    feature = __import__("distrokit.profiles", fromlist=["load_features"]).load_features()["networkmanager_assist"]
    assert feature.kind == "bool" and feature.default is False
    assert "nmx" in packages()
    assert "firefox" not in packages()
    assert "firefox" in packages({"networkmanager_assist": True})


def test_external_desktop_setup_script_has_valid_shell_syntax():
    script = Path(__file__).resolve().parents[2] / "desktop" / "profiles" / "install-selected.sh"
    wrapper = script.with_name("run-session.sh")
    for path in (script, wrapper):
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
    wrapper_text = wrapper.read_text()
    # Which profile is running lives in the state directory, with a lock against two switches at once; the
    # previous profile's config goes back to its own snapshot, and both are cleared when the session ends.
    assert 'state="$HOME/.local/state/distro-desktop-profiles"' in wrapper_text
    assert 'active="$state/active-profile"' in wrapper_text
    assert 'lock="$state/session.lock"' in wrapper_text
    assert 'mv "$staging" "$configs/$previous"' in wrapper_text
    assert 'rm -f "$active" "$lock"' in wrapper_text


def test_profile_sessions_can_start_from_sddm(tmp_path):
    # The login entries run distro-desktop-session, so the scripts must be executable in the package (git keeps the
    # mode), both commands are in /usr/bin, and the entries say Hyprland, which the portals are configured for.
    root = Path(__file__).resolve().parents[2]
    modes = subprocess.run(["git", "ls-files", "-s", "desktop/profiles"], cwd=root, capture_output=True, text=True).stdout
    for name in ("install-selected.sh", "run-session.sh"):
        assert any(line.startswith("100755") and line.endswith(name) for line in modes.splitlines()), modes
    from distrokit.branding import load as load_branding
    from distrokit.build import stage
    b = load_branding()
    stage.Stage(tmp_path, b).run("desktop")
    for command, script in (("distro-desktop-session", "run-session.sh"),
                            ("distro-install-desktop-profiles", "install-selected.sh")):
        link = tmp_path / "usr/bin" / command
        assert link.is_symlink() and link.resolve() == (tmp_path / f"usr/share/{b.id}/desktop/profiles/{script}").resolve()
        assert link.resolve().stat().st_mode & 0o111
    assert "1777" in (tmp_path / f"usr/lib/tmpfiles.d/{b.id}-session-previews.conf").read_text()
    installer = (root / "desktop/profiles/install-selected.sh").read_text()
    assert "DesktopNames=Hyprland" in installer and "/usr/bin/distro-desktop-session" in installer
    session = (root / "desktop/profiles/run-session.sh").read_text()
    assert "start-hyprland -- \"$@\"" in session and "session-previews" in session
    steps = (root / "lib/distrokit/installer/steps.py").read_text()
    assert "/usr/local/bin/distro" not in steps
