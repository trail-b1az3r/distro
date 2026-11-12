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
    assert 'active="$root/.active-profile"' in wrapper_text
    assert 'previous_snapshot="$root/configs/$previous"' in wrapper_text
    assert 'rm -f "$active"' in wrapper_text
