"""Desktop profile selection and staged upstream setup smoke tests."""
from pathlib import Path
import subprocess

from distrokit.profiles import load_profiles, select_packages

def packages(overrides=None):
    return set(select_packages(load_profiles()["minimal"], overrides=overrides or {}).packages)

def test_halcyon_remains_the_default_desktop():
    selected = packages()
    assert "illogical-impulse-hyprland" in selected
    assert "illogical-impulse-quickshell-git" in selected
    assert "waybar" not in selected

def test_primary_desktop_can_be_selected_instead_of_halcyon():
    selected = packages({"desktop_environment": "ml4w"})
    assert "waybar" in selected
    assert "illogical-impulse-hyprland" not in selected

def test_additional_desktops_can_be_installed_together():
    selected = packages({"desktop_ml4w": True, "desktop_sekaipop": True, "desktop_hyde": True})
    assert "illogical-impulse-hyprland" in selected
    assert "waybar" in selected
    assert "qt6-shadertools" in selected

def test_networkmanager_assist_is_optional_and_does_not_replace_nmx():
    feature = __import__("distrokit.profiles", fromlist=["load_features"]).load_features()["networkmanager_assist"]
    assert feature.kind == "bool" and feature.default is False
    assert "nmx" in packages()

def test_external_desktop_setup_script_has_valid_shell_syntax():
    script = Path(__file__).resolve().parents[2] / "desktop" / "profiles" / "install-selected.sh"
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
