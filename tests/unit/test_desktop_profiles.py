"""Desktop profile selection and staged upstream setup smoke tests."""
import os
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
    # Each desktop runs in a home of its own; nothing swaps ~/.config in and out any more.
    assert ". \"$SCRIPT_DIR/profile-home.sh\"" in wrapper_text and 'profile_env "$profile"' in wrapper_text
    assert "rm -rf" not in wrapper_text and "rm -rf" not in script.read_text()

def test_profile_sessions_can_start_from_sddm(tmp_path):
    # The login entries run distro-desktop-session, so the scripts must be executable in the package (git keeps the
    # mode), both commands are in /usr/bin, and the entries say Hyprland, which the portals are configured for.
    root = Path(__file__).resolve().parents[2]
    # On the files themselves: the packages' check() runs these tests from the source tarball, with no git.
    for name in ("install-selected.sh", "run-session.sh"):
        assert os.access(root / "desktop/profiles" / name, os.X_OK), name
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



def _fake_tools(tmp_path):
    """sudo, pacman, chsh, getent and git stand-ins, and an upstream installer that writes all over HOME."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    def tool(name, body):
        (bin_dir / name).write_text("#!/bin/bash\n" + body)
        (bin_dir / name).chmod(0o755)
    tool("sudo", f'echo "sudo $*" >> {calls}\nif [[ "$1" == install ]]; then exit 0; fi\nif [[ "$1" == tee ]]; then cat >/dev/null; exit 0; fi\nexit 0\n')
    tool("pacman", "exit 0\n")
    tool("getent", 'echo "me:x:1000:1000::/home/me:/usr/bin/fish"\n')
    # The upstream repository: HyDE's Scripts/install.sh writes config, shell rc, themes and data under $HOME.
    tool("git", r"""if [[ "$1" == clone ]]; then
  dir="${@: -1}"; mkdir -p "$dir/.git" "$dir/Scripts"
  cat > "$dir/Scripts/install.sh" <<'INSTALL'
#!/bin/bash
mkdir -p "$HOME/.config/hypr" "$HOME/.local/share/hyde" "$HOME/.themes/Hyde"
echo "hyde" > "$HOME/.config/hypr/hyprland.conf"
echo "hyde" > "$HOME/.zshrc"
echo "hyde" > "$HOME/.local/share/hyde/data"
echo "$XDG_CONFIG_HOME" > "$HOME/.xdg-seen"
INSTALL
  chmod +x "$dir/Scripts/install.sh"
fi
exit 0
""")
    return bin_dir, calls


def test_extra_desktops_install_in_their_own_home(tmp_path):
    # The real installer, with stand-ins for the system tools: HyDE's installer writes all over HOME, and none of it
    # may land in Halcyon's home.
    root = Path(__file__).resolve().parents[2]
    bin_dir, calls = _fake_tools(tmp_path)
    home = tmp_path / "home"
    (home / ".config/hypr").mkdir(parents=True)
    (home / ".config/hypr/hyprland.conf").write_text("halcyon")
    (home / ".zshrc").write_text("halcyon")
    (home / ".ssh").mkdir()
    data = tmp_path / "share/nexora"
    (data / "packages/lists").mkdir(parents=True)
    for p in ("ml4w", "hyde", "sekaipop"):
        (data / f"packages/lists/desktop-{p}.list").write_text("kitty\n")
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "DISTRO_DATA_ROOT": str(data),
           "XDG_CONFIG_HOME": str(home / ".config"), "XDG_STATE_HOME": str(home / ".local/state")}
    res = subprocess.run(["bash", str(root / "desktop/profiles/install-selected.sh"), "hyde"], input="y\n",
                         capture_output=True, text=True, env=env, timeout=60)
    assert res.returncode == 0, res.stdout + res.stderr

    # Halcyon's files are as they were; nothing new in its config or data.
    assert (home / ".config/hypr/hyprland.conf").read_text() == "halcyon"
    assert (home / ".zshrc").read_text() == "halcyon"
    assert not (home / ".local/share/hyde").exists() and not (home / ".themes").exists()

    # HyDE has its own home with all of it, and shares the user's files and keys.
    hyde = home / ".local/share/distro-desktop-profiles/homes/hyde"
    assert (hyde / ".config/hypr/hyprland.conf").read_text().strip() == "hyde"
    assert (hyde / ".zshrc").exists() and (hyde / ".local/share/hyde/data").exists() and (hyde / ".themes/Hyde").is_dir()
    assert (hyde / ".xdg-seen").read_text().strip() == str(hyde / ".config")
    assert (hyde / "Documents").resolve() == (home / "Documents").resolve() and (hyde / ".ssh").is_symlink()
    assert (home / ".local/state/distro-desktop-profiles/hyde.done").exists() and (hyde / ".installed-here").exists()

    # Run again: installed in its own home, so only its login entry is checked.
    calls.write_text("")
    res = subprocess.run(["bash", str(root / "desktop/profiles/install-selected.sh"), "hyde"], input="y\n",
                         capture_output=True, text=True, env=env, timeout=60)
    assert res.returncode == 0 and "already installed" in res.stdout and "pacman" not in calls.read_text()
    log = calls.read_text()
    assert "sudo install -D -m 0644" in log and "/usr/share/wayland-sessions/nexora-hyde.desktop" in log
    assert "chsh" not in log  # the shell did not change (the login theme is only re-set where it is installed)


def test_extra_desktop_session_runs_in_its_home(tmp_path):
    root = Path(__file__).resolve().parents[2]
    home = tmp_path / "home"
    hyde = home / ".local/share/distro-desktop-profiles/homes/hyde"
    hyde.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    seen = tmp_path / "seen"
    (bin_dir / "start-hyprland").write_text(f'#!/bin/bash\necho "$HOME|$XDG_CONFIG_HOME|$PWD|$PATH" > {seen}\n')
    (bin_dir / "start-hyprland").chmod(0o755)
    (bin_dir / "systemctl").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "systemctl").chmod(0o755)
    env = {"HOME": str(home), "PATH": f"{bin_dir}:{home}/.local/bin:/usr/bin:/bin"}
    res = subprocess.run(["bash", str(root / "desktop/profiles/run-session.sh"), "hyde"], capture_output=True,
                         text=True, env=env, timeout=30)
    assert res.returncode == 0, res.stderr
    h, xdg, pwd, path = seen.read_text().strip().split("|")
    assert h == str(hyde) and xdg == str(hyde / ".config") and pwd == str(hyde)
    assert path.split(":")[0] == str(hyde / ".local/bin") and f"{home}/.local/bin" not in path.split(":")
    # A desktop that was never installed does not start.
    res = subprocess.run(["bash", str(root / "desktop/profiles/run-session.sh"), "ml4w"], capture_output=True,
                         text=True, env=env, timeout=30)
    assert res.returncode == 1 and "not installed" in res.stderr
