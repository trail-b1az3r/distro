"""`logout`: end graphical sessions now, at a time, or cancel that, like `shutdown`.

    logout                 log out in 1 minute (a warning goes to the session first)
    logout now             log out now
    logout +N | HH:MM      log out in N minutes, or at that time
    logout stop            cancel a pending logout
    logout status          what is pending

Only graphical sessions (Wayland or X11) end: SSH and text logins stay. With sudo it is the user who ran sudo, and
`--all` is every user's; without, your own. A pending logout is a systemd timer (a system one as root, a user one
otherwise), so it survives the terminal it was typed in.
"""

from __future__ import annotations

import json
import os
import pwd
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta

UNIT = "nexora-logout"
GRAPHICAL = {"wayland", "x11", "mir"}


class LogoutError(RuntimeError):
    pass


@dataclass(frozen=True)
class Session:
    id: str
    user: str
    uid: int
    type: str


def when(spec: str, now: datetime | None = None) -> int:
    """Seconds from now for "now", "+N" (minutes) or "HH:MM" (today, or tomorrow when that has passed)."""
    now = now or datetime.now()
    if spec == "now":
        return 0
    m = re.fullmatch(r"\+?(\d{1,4})", spec)
    if m:
        return int(m.group(1)) * 60
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", spec)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        at = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if at <= now:
            at += timedelta(days=1)
        return int((at - now).total_seconds())
    raise LogoutError(f"not a time: {spec!r} (use now, +MINUTES or HH:MM)")


def target_users(all_users: bool) -> set[str] | None:
    """Whose sessions end: None for everyone's (--all, root only), else the user who ran sudo, or this user."""
    if all_users:
        if os.geteuid() != 0:
            raise LogoutError("logging out every user needs root: sudo logout --all")
        return None
    sudo_user = os.environ.get("SUDO_USER")
    if os.geteuid() == 0 and sudo_user and sudo_user != "root":
        return {sudo_user}
    return {pwd.getpwuid(os.geteuid()).pw_name}


def sessions(users: set[str] | None, run=subprocess.run) -> list[Session]:
    """The graphical sessions of these users (None: everyone's)."""
    out = run(["loginctl", "list-sessions", "--json=short"], capture_output=True, text=True, check=False)
    try:
        listed = json.loads(out.stdout or "[]")
    except ValueError:
        listed = []
    found = []
    for item in listed:
        sid, user = str(item.get("session", "")), str(item.get("user", ""))
        if not sid or (users is not None and user not in users):
            continue
        kind = run(["loginctl", "show-session", sid, "-p", "Type", "--value"], capture_output=True, text=True,
                   check=False).stdout.strip()
        if kind in GRAPHICAL:
            found.append(Session(sid, user, int(item.get("uid", -1)), kind))
    return found


def warn(targets: list[Session], message: str, run=subprocess.run) -> None:
    """A desktop notification in each session, and a line in each terminal (wall, as root)."""
    for s in targets:
        bus = f"unix:path=/run/user/{s.uid}/bus"
        cmd = ["notify-send", "-u", "critical", "-a", "Logout", "Logging out", message]
        if os.geteuid() == 0 and shutil.which("runuser"):
            cmd = ["runuser", "-u", s.user, "--", "env", f"DBUS_SESSION_BUS_ADDRESS={bus}", *cmd]
        if shutil.which("notify-send"):
            run(cmd, capture_output=True, check=False, timeout=10)
    if os.geteuid() == 0 and shutil.which("wall"):
        run(["wall", message], capture_output=True, check=False, timeout=10)


def end(targets: list[Session], run=subprocess.run) -> list[str]:
    """End these sessions; returns the ones that could not be ended."""
    failed = []
    for s in targets:
        done = run(["loginctl", "terminate-session", s.id], capture_output=True, text=True, check=False)
        if done.returncode != 0:
            failed.append(f"{s.id} ({s.user}): {(done.stderr or done.stdout).strip()}")
    return failed


def _systemctl() -> list[str]:
    return ["systemctl"] if os.geteuid() == 0 else ["systemctl", "--user"]


def pending(run=subprocess.run) -> str:
    """When the pending logout fires, or "" for none."""
    out = run([*_systemctl(), "show", f"{UNIT}.timer", "-p", "ActiveState", "-p", "NextElapseUSecRealtime"],
              capture_output=True, text=True, check=False).stdout
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if props.get("ActiveState") != "active":
        return ""
    return props.get("NextElapseUSecRealtime", "") or "pending"


def schedule(seconds: int, cli: str, all_users: bool, users: set[str] | None, run=subprocess.run) -> None:
    """A systemd timer that runs `<cli> logout now` then (replacing one already pending)."""
    cancel(run)
    cmd = [shutil.which(cli) or f"/usr/bin/{cli}", "logout", "now", "--quiet"]
    if all_users:
        cmd.append("--all")
    env = []
    if os.geteuid() == 0 and users:
        env = [f"--setenv=SUDO_USER={next(iter(users))}"]
    sd = ["systemd-run"] if os.geteuid() == 0 else ["systemd-run", "--user"]
    done = run([*sd, f"--unit={UNIT}", f"--on-active={seconds}", "--timer-property=AccuracySec=1s", *env, *cmd],
               capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise LogoutError("could not schedule the logout: " + (done.stderr or done.stdout).strip())


def cancel(run=subprocess.run) -> bool:
    """Cancel a pending logout; whether there was one."""
    was = bool(pending(run))
    run([*_systemctl(), "stop", f"{UNIT}.timer", f"{UNIT}.service"], capture_output=True, check=False)
    return was


def describe(seconds: int) -> str:
    if seconds < 90:
        return "in 1 minute" if seconds >= 30 else "now"
    minutes = round(seconds / 60)
    if minutes < 120:
        return f"in {minutes} minutes"
    return "at " + (datetime.now() + timedelta(seconds=seconds)).strftime("%H:%M")
