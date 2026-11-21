"""The power menu's actions (``<id>-power-menu``, opened by the power button in the extra desktops).

Each action is a command line; the ones that need logind's support (hibernation, restarting into the firmware's
setup) are offered only where logind says they are possible. Logging out ends the compositor the way it ends itself
(Hyprland's exit), and falls back to ending the login session.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    icon: str            # a name from branding/icons/ui
    commands: list[list[str]] = field(default_factory=list)   # tried in order until one succeeds
    danger: bool = False


def logind_can(method: str, run=subprocess.run) -> bool:
    """logind's own answer to Can<method> (CanHibernate, CanRebootToFirmwareSetup...): "yes" or "challenge"."""
    if not shutil.which("busctl"):
        return False
    try:
        out = run(["busctl", "call", "--system", "org.freedesktop.login1", "/org/freedesktop/login1",
                   "org.freedesktop.login1.Manager", method], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0 and any(word in out.stdout for word in ('"yes"', '"challenge"'))


def lock_commands() -> list[list[str]]:
    # A running idle daemon locks with the desktop's own locker when logind asks; otherwise hyprlock directly.
    commands = []
    if shutil.which("pidof") and subprocess.run(["pidof", "hypridle"], capture_output=True).returncode == 0:
        commands.append(["loginctl", "lock-session"])
    if shutil.which("hyprlock"):
        commands.append(["hyprlock"])
    commands.append(["loginctl", "lock-session"])
    return commands


def logout_commands(env: dict[str, str] | None = None) -> list[list[str]]:
    env = os.environ if env is None else env
    commands = []
    if env.get("HYPRLAND_INSTANCE_SIGNATURE"):
        commands += [["hyprctl", "dispatch", "hl.dsp.exit()"], ["hyprctl", "dispatch", "exit"]]
    if env.get("XDG_SESSION_ID"):
        commands.append(["loginctl", "terminate-session", env["XDG_SESSION_ID"]])
    else:
        commands.append(["loginctl", "terminate-user", env.get("USER", "")])
    return commands


def actions(can=logind_can, env: dict[str, str] | None = None) -> list[Action]:
    found = [
        Action("lock", "Lock", "lock", lock_commands()),
        Action("logout", "Log out", "arrow-right", logout_commands(env)),
        Action("suspend", "Sleep", "moon", [["systemctl", "suspend"]]),
    ]
    if can("CanHibernate"):
        found.append(Action("hibernate", "Hibernate", "storage", [["systemctl", "hibernate"]]))
    found += [
        Action("reboot", "Restart", "refresh", [["systemctl", "reboot"]], danger=True),
        Action("poweroff", "Shut down", "power", [["systemctl", "poweroff"]], danger=True),
    ]
    if can("CanRebootToFirmwareSetup"):
        found.append(Action("firmware", "Firmware setup", "settings",
                            [["systemctl", "reboot", "--firmware-setup"]], danger=True))
    return found


def perform(action: Action, run=subprocess.run) -> bool:
    """Run the action's first command that works. The lock screen is started and left running."""
    for cmd in action.commands:
        if not cmd or not shutil.which(cmd[0]):
            continue
        try:
            if action.id == "lock" and cmd[0] == "hyprlock":
                subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            if run(cmd, capture_output=True, timeout=30).returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False
