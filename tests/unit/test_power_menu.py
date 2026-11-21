"""The power button opens a power menu in the extra desktops (desktop/profiles/power-button.sh, <id>-power-menu)."""

import os
import socket
import subprocess
from pathlib import Path

from distrokit import paths
from distrokit.system import power

HELPER = paths.data("desktop", "profiles", "power-button.sh")


def fake_session(tmp_path, binds="[]"):
    runtime = tmp_path / "run"
    inst = runtime / "hypr" / "sig1"
    inst.mkdir(parents=True)
    sock = socket.socket(socket.AF_UNIX)
    cwd = os.getcwd()
    os.chdir(inst)   # a relative name: unix socket paths are limited to 108 bytes
    try:
        sock.bind(".socket.sock")
    finally:
        os.chdir(cwd)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "log"
    (bin_ / "hyprctl").write_text(
        f"#!/bin/sh\necho \"hyprctl $HYPRLAND_INSTANCE_SIGNATURE $*\" >> {log}\n"
        f"[ \"$1\" = binds ] && echo '{binds}'\nexit 0\n")
    # systemd-inhibit: say how it was called, and do not wait for the session to end.
    (bin_ / "systemd-inhibit").write_text(f"#!/bin/sh\necho \"inhibit $*\" >> {log}\n")
    for f in bin_.iterdir():
        f.chmod(0o755)
    env = {"PATH": f"{bin_}:{os.environ['PATH']}", "XDG_RUNTIME_DIR": str(runtime), "HOME": str(tmp_path),
           "DISTRO_ID": "frontline", "POWER_MENU": "/usr/bin/frontline-power-menu", "POWER_BUTTON_WAIT": "3",
           "POWER_BUTTON_SETTLE": "0"}
    return env, log, sock


def run_helper(env, before=""):
    return subprocess.run(["bash", str(HELPER), before], env=env, capture_output=True, text=True, timeout=20)


def test_the_button_gets_the_menu_and_logind_lets_go_of_it(tmp_path):
    env, log, sock = fake_session(tmp_path)
    run_helper(env)
    text = log.read_text()
    assert 'hyprctl sig1 eval hl.bind("XF86PowerOff", hl.dsp.exec_cmd("/usr/bin/frontline-power-menu")' in text
    assert "inhibit --what=handle-power-key" in text and "--mode=block" in text
    sock.close()


def test_a_desktop_with_its_own_power_menu_keeps_it(tmp_path):
    env, log, sock = fake_session(tmp_path, binds='[{"key": "XF86PowerOff", "dispatcher": "exec"}]')
    run_helper(env)
    text = log.read_text()
    assert " eval " not in text            # its own binding stays
    assert "inhibit --what=handle-power-key" in text   # and the button reaches it
    sock.close()


def test_an_older_hyprland_instance_is_not_touched(tmp_path):
    env, log, sock = fake_session(tmp_path)
    run_helper(env, before="sig1")   # sig1 was there before this desktop started: never found
    assert not log.exists()
    sock.close()


def test_it_can_be_turned_off(tmp_path):
    env, log, sock = fake_session(tmp_path)
    (tmp_path / ".config/frontline").mkdir(parents=True)
    (tmp_path / ".config/frontline/power-button-off").touch()
    run_helper(env)
    assert not log.exists()
    sock.close()


def test_run_session_starts_it():
    text = paths.data("desktop", "profiles", "run-session.sh").read_text()
    start = text.index('"$SCRIPT_DIR/power-button.sh"')
    assert start < text.index('if [[ "$profile" == paperrice')   # every kind of session gets it


def test_the_actions():
    found = power.actions(can=lambda _m: False, env={"HYPRLAND_INSTANCE_SIGNATURE": "x", "XDG_SESSION_ID": "3"})
    ids = [a.id for a in found]
    assert ids == ["lock", "logout", "suspend", "reboot", "poweroff"]   # no hibernate/firmware where logind says no
    logout = next(a for a in found if a.id == "logout")
    assert logout.commands[0] == ["hyprctl", "dispatch", "hl.dsp.exit()"]
    assert logout.commands[-1] == ["loginctl", "terminate-session", "3"]
    every = [a.id for a in power.actions(can=lambda _m: True, env={})]
    assert "hibernate" in every and "firmware" in every


def test_perform_falls_back_to_the_next_command(tmp_path, monkeypatch):
    calls = []

    def run(cmd, **_kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if cmd[1] == "dispatch" else 0)

    monkeypatch.setattr(power.shutil, "which", lambda name: f"/usr/bin/{name}")
    action = power.Action("logout", "Log out", "arrow-right",
                          [["hyprctl", "dispatch", "hl.dsp.exit()"], ["loginctl", "terminate-session", "3"]])
    assert power.perform(action, run) is True
    assert calls[-1] == ["loginctl", "terminate-session", "3"]


def test_the_menu_window_loads():
    import pytest

    pytest.importorskip("PySide6.QtQuick", exc_type=ImportError)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from distrokit.gui import common, power_app

    app = common.make_app("power-menu", "Power")
    chosen = []
    backend = power_app.PowerBackend(power.actions(can=lambda _m: True, env={}),
                                     run=lambda cmd, **_k: chosen.append(cmd))
    engine, warnings = common.load_qml(app, paths.qml_dir() / "power" / "Main.qml",
                                       {"power": backend, "iconDir": str(common.icon_dir())})
    root = engine.rootObjects()[0]
    assert root.objectName() == "powerMenu" and not warnings.items
    ids = [a["id"] for a in backend.actions]
    assert ids[root.property("current")] == "poweroff"   # the power button then Enter: shut down
    root.close()
    assert Path(power_app.__file__).name == "power_app.py"
