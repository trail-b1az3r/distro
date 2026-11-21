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
    assert "oynix-bin" not in packages()
    assert "oynix-bin" in packages({"networkmanager_assist": True})


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
    """sudo, pacman, chsh, getent, git and dbus-run-session stand-ins, and an upstream installer that writes all over
    HOME, into the real home by its full path, into the login entries, and asks pacman for the stock hyprland."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    def tool(name, body):
        (bin_dir / name).write_text("#!/bin/bash\n" + body)
        (bin_dir / name).chmod(0o755)
    # sudo runs what it is given (the system paths are under DISTRO_SYSROOT, in tmp_path), except chsh.
    tool("sudo", f'echo "sudo $*" >> {calls}\nif [[ "$1" == chsh ]]; then exit 0; fi\nexec "$@"\n')
    tool("pacman", f'echo "pacman $*" >> {calls}\nexit 0\n')
    tool("getent", 'echo "me:x:1000:1000::/home/me:/usr/bin/fish"\n')
    tool("dbus-run-session", f'echo "dbus-run-session" >> {calls}\nshift\nexec "$@"\n')
    # The upstream repository: HyDE's Scripts/install.sh writes config, shell rc, themes and data under $HOME, and
    # misbehaves the ways real installers do.
    tool("git", r"""if [[ "$1" == clone ]]; then
  dir="${@: -1}"; mkdir -p "$dir/.git" "$dir/Scripts"
  cat > "$dir/Scripts/install.sh" <<'INSTALL'
#!/bin/bash
mkdir -p "$HOME/.config/hypr" "$HOME/.local/share/hyde" "$HOME/.themes/Hyde"
if [[ -n "${HYDE_CONF_ONLY:-}" ]]; then echo "hyde" > "$HOME/.config/hypr/hyprland.conf"; exit 0; fi
echo "hyde" > "$HOME/.config/hypr/hyprland.lua"
echo "hyde" > "$HOME/.zshrc"
echo "hyde" > "$HOME/.local/share/hyde/data"
echo "$XDG_CONFIG_HOME" > "$HOME/.xdg-seen"
echo "${HYPRLAND_INSTANCE_SIGNATURE:-none}" > "$HOME/.hypr-seen"
# Past HOME, into the real home by its full path.
real="$GUARD_TEST_REAL"
echo "hyde" > "$real/.config/hypr/hyprland.lua"
echo "hyde-extra" > "$real/.config/hypr/hyde.conf"
echo "hyde" > "$real/.zshrc"
mkdir -p "$real/.mydotfiles" && echo x > "$real/.mydotfiles/x"
rm -f "$real/.bashrc"
echo "browser" > "$real/.config/chromium/Local State"
# The system: the stock compositor, a login entry of its own, Halcyon's entry and the login screen changed.
sudo pacman -S --needed --noconfirm hyprland waybar
pacman -Qi hyprland > /dev/null
sessions="$DISTRO_SYSROOT/usr/share/wayland-sessions"
echo "[Desktop Entry]" | sudo tee "$sessions/hyde-hyprland.desktop" > /dev/null
echo "broken" | sudo tee "$sessions/hyprland.desktop" > /dev/null
echo "[Theme]" | sudo tee "$DISTRO_SYSROOT/etc/sddm.conf.d/hyde.conf" > /dev/null
INSTALL
  chmod +x "$dir/Scripts/install.sh"
fi
exit 0
""")
    return bin_dir, calls


def test_extra_desktops_install_in_their_own_home(tmp_path):
    # The real installer, with stand-ins for the system tools: HyDE's installer writes all over HOME, past it into the
    # real home, and into the system; none of it may change Halcyon.
    root = Path(__file__).resolve().parents[2]
    bin_dir, calls = _fake_tools(tmp_path)
    home = tmp_path / "home"
    (home / ".config/hypr").mkdir(parents=True)
    (home / ".config/hypr/hyprland.lua").write_text("halcyon")
    (home / ".config/chromium").mkdir()
    (home / ".zshrc").write_text("halcyon")
    (home / ".bashrc").write_text("halcyon")
    (home / ".ssh").mkdir()
    sysroot = tmp_path / "sys"
    (sysroot / "usr/share/wayland-sessions").mkdir(parents=True)
    (sysroot / "usr/share/wayland-sessions/hyprland.desktop").write_text("[Desktop Entry]\nName=Halcyon\n")
    (sysroot / "etc/sddm.conf.d").mkdir(parents=True)
    data = tmp_path / "share/nexora"
    (data / "packages/lists").mkdir(parents=True)
    for p in ("ml4w", "hyde", "sekaipop"):
        (data / f"packages/lists/desktop-{p}.list").write_text("kitty\n")
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "DISTRO_DATA_ROOT": str(data),
           "XDG_CONFIG_HOME": str(home / ".config"), "XDG_STATE_HOME": str(home / ".local/state"),
           "DISTRO_SYSROOT": str(sysroot), "GUARD_TEST_REAL": str(home), "HYPRLAND_INSTANCE_SIGNATURE": "halcyon"}
    res = subprocess.run(["bash", str(root / "desktop/profiles/install-selected.sh"), "hyde"], input="y\n",
                         capture_output=True, text=True, env=env, timeout=60)
    assert res.returncode == 0, res.stdout + res.stderr

    # Halcyon's files are as they were; nothing new in its config or data, even what was written by full path.
    assert (home / ".config/hypr/hyprland.lua").read_text() == "halcyon"
    assert (home / ".zshrc").read_text() == "halcyon" and (home / ".bashrc").read_text() == "halcyon"
    assert not (home / ".config/hypr/hyde.conf").exists() and not (home / ".mydotfiles").exists()
    assert not (home / ".local/share/hyde").exists() and not (home / ".themes").exists()
    # A running program's files (a browser's) are left alone.
    assert (home / ".config/chromium/Local State").read_text().strip() == "browser"

    # HyDE has its own home with all of it, and shares the user's files and keys.
    hyde = home / ".local/share/distro-desktop-profiles/homes/hyde"
    assert (hyde / ".config/hypr/hyprland.lua").read_text().strip() == "hyde"
    assert (hyde / ".config/hypr/hyde.conf").read_text().strip() == "hyde-extra"
    assert (hyde / ".mydotfiles/x").exists()
    assert (hyde / ".zshrc").exists() and (hyde / ".local/share/hyde/data").exists() and (hyde / ".themes/Hyde").is_dir()
    assert (hyde / ".xdg-seen").read_text().strip() == str(hyde / ".config")
    # Not the running Halcyon session's address, and its own D-Bus session.
    assert (hyde / ".hypr-seen").read_text().strip() == "none"
    assert (hyde / "Documents").resolve() == (home / "Documents").resolve() and (hyde / ".ssh").is_symlink()
    assert (home / ".local/state/distro-desktop-profiles/hyde.done").exists() and (hyde / ".installed-here").exists()
    assert not list((home / ".local/state/distro-desktop-profiles").glob("guard-*"))
    log = calls.read_text()
    assert "dbus-run-session" in log

    # hyprland-plus stays: the stock hyprland was left out of the install and the query answered for hyprland-plus.
    installs = [line for line in log.splitlines() if line.startswith("pacman -S")]
    assert "pacman -S --needed --noconfirm waybar" in installs and not any("hyprland" in line for line in installs)
    assert "pacman -Qi hyprland-plus" in log

    # The system: the installer's login entry and SDDM file set aside, Halcyon's entry put back, ours registered.
    sessions = sysroot / "usr/share/wayland-sessions"
    assert (sessions / "hyprland.desktop").read_text() == "[Desktop Entry]\nName=Halcyon\n"
    assert not (sessions / "hyde-hyprland.desktop").exists() and not (sysroot / "etc/sddm.conf.d/hyde.conf").exists()
    assert (sysroot / "var/lib/nexora/set-aside/hyde-hyprland.desktop").exists()
    assert "/usr/bin/distro-desktop-session hyde" in (sessions / "nexora-hyde.desktop").read_text() or \
        "run-session.sh hyde" in (sessions / "nexora-hyde.desktop").read_text()

    # Run again: installed in its own home, so only its login entry is checked.
    calls.write_text("")
    res = subprocess.run(["bash", str(root / "desktop/profiles/install-selected.sh"), "hyde"], input="y\n",
                         capture_output=True, text=True, env=env, timeout=60)
    assert res.returncode == 0 and "already installed" in res.stdout and "pacman" not in calls.read_text()
    log = calls.read_text()
    assert "sudo install -D -m 0644" in log and "/usr/share/wayland-sessions/nexora-hyde.desktop" in log
    assert "chsh" not in log  # the shell did not change (the login theme is only re-set where it is installed)


def _install_env(tmp_path, bin_dir):
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True, exist_ok=True)
    data = tmp_path / "share/nexora"
    (data / "packages/lists").mkdir(parents=True, exist_ok=True)
    for p in ("ml4w", "hyde", "sekaipop"):
        (data / f"packages/lists/desktop-{p}.list").write_text("kitty\n")
    sysroot = tmp_path / "sys"
    (sysroot / "usr/share/wayland-sessions").mkdir(parents=True, exist_ok=True)
    (sysroot / "etc/sddm.conf.d").mkdir(parents=True, exist_ok=True)
    return home, {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "DISTRO_DATA_ROOT": str(data),
                  "XDG_CONFIG_HOME": str(home / ".config"), "XDG_STATE_HOME": str(home / ".local/state"),
                  "DISTRO_SYSROOT": str(sysroot), "GUARD_TEST_REAL": str(home)}


def test_a_desktop_without_its_own_lua_config_is_not_registered(tmp_path):
    # Hyprland 0.57 reads only hyprland.lua: dotfiles that leave only hyprland.conf would open as plain Hyprland.
    root = Path(__file__).resolve().parents[2]
    bin_dir, calls = _fake_tools(tmp_path)
    home, env = _install_env(tmp_path, bin_dir)
    res = subprocess.run(["bash", str(root / "desktop/profiles/install-selected.sh"), "hyde"], input="y\n",
                         capture_output=True, text=True, env={**env, "HYDE_CONF_ONLY": "1"}, timeout=60)
    assert res.returncode == 1 and "only hyprland.conf" in res.stdout and "not registered" in res.stdout
    assert not (tmp_path / "sys/usr/share/wayland-sessions/nexora-hyde.desktop").exists()
    assert not (home / ".local/state/distro-desktop-profiles/hyde.done").exists()


def test_a_desktop_with_hyprlands_generated_example_is_installed_again(tmp_path):
    # Marked installed, but its session already ran into Hyprland's generated example: the next run installs it again.
    root = Path(__file__).resolve().parents[2]
    bin_dir, calls = _fake_tools(tmp_path)
    home, env = _install_env(tmp_path, bin_dir)
    hyde = home / ".local/share/distro-desktop-profiles/homes/hyde"
    (hyde / ".config/hypr").mkdir(parents=True)
    (hyde / ".config/hypr/hyprland.lua").write_text("hl.config({ autogenerated = true })\n")
    (hyde / ".installed-here").write_text("")
    state = home / ".local/state/distro-desktop-profiles"
    state.mkdir(parents=True)
    (state / "hyde.done").write_text("")
    res = subprocess.run(["bash", str(root / "desktop/profiles/install-selected.sh"), "hyde"], input="y\n",
                         capture_output=True, text=True, env=env, timeout=60)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "generated example" in res.stdout and "installing it again" in res.stdout
    assert (hyde / ".config/hypr/hyprland.lua").read_text().strip() == "hyde"
    assert list((hyde / ".config/hypr").glob("hyprland.lua.not-installed-*"))


def test_a_session_without_its_config_opens_the_repair_session(tmp_path):
    root = Path(__file__).resolve().parents[2]
    home = tmp_path / "home"
    ml4w = home / ".local/share/distro-desktop-profiles/homes/ml4w"
    (ml4w / ".config/hypr").mkdir(parents=True)
    (ml4w / ".config/hypr/hyprland.lua").write_text("hl.config({ autogenerated = true })\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    seen = tmp_path / "seen"
    (bin_dir / "start-hyprland").write_text(f'#!/bin/bash\necho "$HOME|$*" > {seen}\n')
    (bin_dir / "start-hyprland").chmod(0o755)
    (bin_dir / "alacritty").write_text("#!/bin/sh\n")
    (bin_dir / "alacritty").chmod(0o755)
    runtime = tmp_path / "run"
    runtime.mkdir()
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "XDG_RUNTIME_DIR": str(runtime)}
    res = subprocess.run(["bash", str(root / "desktop/profiles/run-session.sh"), "ml4w"], capture_output=True,
                         text=True, env=env, timeout=30)
    assert res.returncode == 0, res.stderr
    h, args = seen.read_text().strip().split("|")
    # Not the desktop's home: the repair session, with the real home, reinstalls it.
    assert h == str(home) and args == f"-- --config {runtime}/distro-desktop-repair-ml4w/hyprland.lua"
    lua = (runtime / "distro-desktop-repair-ml4w/hyprland.lua").read_text()
    assert "alacritty -e" in lua and "autogenerated = false" in lua
    assert "distro-install-desktop-profiles ml4w" in (runtime / "distro-desktop-repair-ml4w/repair.sh").read_text()


def test_the_pacman_guard_keeps_hyprland_plus(tmp_path):
    root = Path(__file__).resolve().parents[2]
    guard = root / "desktop/profiles/guard-bin"
    real = tmp_path / "bin"
    real.mkdir()
    log = tmp_path / "log"
    installed = tmp_path / "plus-installed"
    (real / "pacman").write_text(f'#!/bin/bash\nif [[ "$*" == "-Q hyprland-plus" ]]; then [[ -e {installed} ]]; exit; fi\n'
                                 f'echo "$*" >> {log}\n')
    (real / "pacman").chmod(0o755)
    (real / "sudo").write_text(f'#!/bin/bash\nwhile [[ "$1" == -* ]]; do shift; done\necho "sudo $1" >> {log}\nexec "$@"\n')
    (real / "sudo").chmod(0o755)
    env = {"PATH": f"{guard}:{real}:/usr/bin:/bin"}
    def run(*args):
        log.write_text("")
        r = subprocess.run(list(args), capture_output=True, text=True, env=env, timeout=30)
        return r.returncode, log.read_text().strip()

    installed.touch()
    assert run("pacman", "-S", "--needed", "--noconfirm", "hyprland", "waybar") == (0, "-S --needed --noconfirm waybar")
    assert run("pacman", "-S", "--noconfirm", "hyprland") == (0, "")
    assert run("pacman", "-Rns", "--noconfirm", "hyprland") == (0, "")
    assert run("pacman", "-Qi", "hyprland") == (0, "-Qi hyprland-plus")
    assert run("pacman", "-Ss", "hyprland") == (0, "-Ss hyprland")
    assert run("pacman", "-S", "--ignore", "hyprland", "kitty") == (0, "-S --ignore hyprland kitty")
    # Through sudo, as installers call it.
    code, out = run("sudo", "pacman", "-S", "hyprland", "kitty")
    assert code == 0 and out.endswith("-S kitty") and str(guard / "pacman") in out
    # The upgrade asked for alongside it still runs.
    code, out = run("sudo", "-E", "pacman", "-Syu", "--noconfirm", "hyprland")
    assert code == 0 and out.endswith("-Syu --noconfirm")
    # Without hyprland-plus, the stock package goes through.
    installed.unlink()
    assert run("pacman", "-S", "hyprland") == (0, "-S hyprland")


def test_extra_desktop_session_runs_in_its_home(tmp_path):
    root = Path(__file__).resolve().parents[2]
    home = tmp_path / "home"
    hyde = home / ".local/share/distro-desktop-profiles/homes/hyde"
    (hyde / ".config/hypr").mkdir(parents=True)
    (hyde / ".config/hypr/hyprland.lua").write_text("-- HyDE\n")
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


def _carry(tmp_path, *names):
    """Runs profile_home_setup for one desktop with REAL_HOME in tmp_path, and returns (real home, desktop home)."""
    real = tmp_path / "real"
    real.mkdir(exist_ok=True)
    script = Path(__file__).resolve().parents[2] / "desktop/profiles/profile-home.sh"
    subprocess.run(["bash", "-c", f'REAL_HOME="{real}"; . "{script}"; profile_home_setup hyde'],
                   check=True, capture_output=True, text=True)
    return real, real / ".local/share/distro-desktop-profiles/homes/hyde"


def test_firefox_carries_over_from_halcyon_in_both_places_it_keeps_profiles(tmp_path):
    real = tmp_path / "real"
    (real / ".config/mozilla/firefox").mkdir(parents=True)  # Firefox 147+: profiles under ~/.config/mozilla
    (real / ".config/mozilla/firefox/profiles.ini").write_text("[Profile0]\n")
    (real / ".mozilla/firefox").mkdir(parents=True)          # older Firefox: ~/.mozilla
    (real / ".cache/mozilla").mkdir(parents=True)
    _, desk = _carry(tmp_path)
    for name in (".config/mozilla", ".mozilla", ".cache/mozilla"):
        assert (desk / name).is_symlink() and (desk / name).resolve() == (real / name).resolve(), name
    assert (desk / ".config/mozilla/firefox/profiles.ini").read_text() == "[Profile0]\n"


def test_a_browser_first_used_in_the_other_desktop_moves_to_the_real_home(tmp_path):
    desk = tmp_path / "real/.local/share/distro-desktop-profiles/homes/hyde"
    (desk / ".config/google-chrome/Default").mkdir(parents=True)
    (desk / ".config/google-chrome/Default/Login Data").write_text("signed in\n")
    real, desk = _carry(tmp_path)
    assert (real / ".config/google-chrome/Default/Login Data").read_text() == "signed in\n"
    assert (desk / ".config/google-chrome").is_symlink()


def test_the_desktops_own_copy_is_kept_aside_and_halcyons_is_used(tmp_path):
    real = tmp_path / "real"
    (real / ".mozilla/firefox").mkdir(parents=True)
    (real / ".mozilla/firefox/halcyon").write_text("halcyon\n")
    desk = real / ".local/share/distro-desktop-profiles/homes/hyde"
    (desk / ".mozilla/firefox").mkdir(parents=True)
    (desk / ".mozilla/firefox/own").write_text("own\n")
    _, desk = _carry(tmp_path)
    assert (desk / ".mozilla").is_symlink() and (desk / ".mozilla/firefox/halcyon").is_file()
    kept = list((desk / ".local/state/distro-desktop-profiles/own").glob(".mozilla.*"))
    assert len(kept) == 1 and (kept[0] / "firefox/own").read_text() == "own\n"
    # The next login changes nothing.
    _carry(tmp_path)
    assert len(list((desk / ".local/state/distro-desktop-profiles/own").glob(".mozilla.*"))) == 1


def test_the_installer_guard_leaves_shared_browsers_alone():
    text = (Path(__file__).resolve().parents[2] / "desktop/profiles/install-selected.sh").read_text()
    assert "${PROFILE_SHARED_APPS[*]}" in text


def test_hyde_is_installed_from_a_fresh_start_after_a_failed_try():
    text = (Path(__file__).resolve().parents[2] / "desktop/profiles/install-selected.sh").read_text()
    # A half-made Python environment ("deez-dots not found") is set aside, and so is a checkout that cannot update.
    assert '.local/state/hyde/python_env' in text and 'mv -- "$pyenv" "$pyenv.old-' in text
    assert 'mv -- "$dir" "$dir.old-' in text
    hyde = (Path(__file__).resolve().parents[2] / "packages/lists/desktop-hyde.list").read_text().split()
    assert "uv" in hyde and "python" in hyde
