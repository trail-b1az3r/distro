"""Automatic updates: `<cli> auto-update`.

Three modes, in /etc/<id>/auto-update.conf (MODE=...):

  notify  (default)  once a day, check every update source and show a notification when something is waiting;
                     clicking it opens the updater. Nothing is installed without you.
  apply              once a day, also install updates from the repositories (Arch, EndeavourOS and the
                     distribution's own, which carries the desktop), unattended; then refresh each user's desktop
                     configuration. AUR packages, Flatpaks, GPU changes and the AI tools still wait for you.
  off                nothing runs.

Unattended installs hold back, and fall back to a notification, when:
  * the computer is on battery (an interrupted upgrade is the worst kind),
  * there is Arch Linux news since the last update (it often announces a manual step),
  * pacman's database is locked (another update is running).

Two timers do the work: <id>-auto-update.timer (system, root) installs packages in apply mode, and
<id>-update-notify.timer (user) checks and notifies, and refreshes the desktop configuration after an unattended
update. Both only act on the mode in the configuration file, so `auto-update mode ...` is all it takes.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .. import paths, util
from ..branding import Branding, load as load_branding

MODES = ("notify", "apply", "off")
DEFAULT_MODE = "notify"


def config_path(branding: Branding, root: Path | str = "/") -> Path:
    return paths.SystemPaths(branding.id, root).sysconf / "auto-update.conf"


def state_path(branding: Branding, root: Path | str = "/") -> Path:
    return paths.SystemPaths(branding.id, root).state / "auto-update.json"


def read_mode(branding: Branding, root: Path | str = "/") -> str:
    path = config_path(branding, root)
    if path.exists():
        for line in path.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "MODE" and value.strip().strip('"') in MODES:
                return value.strip().strip('"')
    return DEFAULT_MODE


def write_mode(mode: str, branding: Branding, root: Path | str = "/") -> Path:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    path = config_path(branding, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# {branding.pretty_name} automatic updates: notify, apply or off (`{branding.cli} auto-update mode ...`).\n"
        f"MODE={mode}\n")
    return path


def on_battery(sys_root: Path = Path("/sys/class/power_supply")) -> bool:
    """True when there is a battery and no mains power. Desktops (no battery) are never on battery."""
    if not sys_root.is_dir():
        return False
    batteries, mains_online = False, False
    for supply in sys_root.iterdir():
        kind = (supply / "type").read_text().strip() if (supply / "type").exists() else ""
        if kind == "Battery":
            batteries = True
        elif kind in ("Mains", "USB", "USB_C", "USB_PD") and (supply / "online").exists():
            mains_online = mains_online or (supply / "online").read_text().strip() == "1"
    return batteries and not mains_online


@dataclass
class Decision:
    install: bool
    reason: str


def decide(mode: str, waiting: int, battery: bool, news: int, locked: bool) -> Decision:
    """Whether the system timer installs now, and why (or why not), in words for the log and the notification."""
    if mode != "apply":
        return Decision(False, f"mode is {mode}")
    if waiting == 0:
        return Decision(False, "everything is up to date")
    if battery:
        return Decision(False, "on battery: waiting for mains power")
    if news:
        return Decision(False, f"{news} Arch Linux news post(s) since the last update: read them first")
    if locked:
        return Decision(False, "pacman is busy (its database is locked)")
    return Decision(True, f"{waiting} package update(s)")


def record(branding: Branding, **fields) -> None:
    path = state_path(branding)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"time": time.time(), **fields}
    path.write_text(json.dumps(data, indent=2) + "\n")


def read_record(branding: Branding, root: Path | str = "/") -> dict:
    path = state_path(branding, root)
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def run_system(branding: Branding | None = None, runner: util.Runner | None = None) -> int:
    """The system timer (root): in apply mode, install repository updates when it is safe to."""
    from . import update

    branding = branding or load_branding()
    runner = runner or util.Runner(log=print)
    mode = read_mode(branding)
    if mode != "apply":
        print(f"auto-update: mode is {mode}; nothing to install")
        return 0
    packages = update.check_packages()
    news = update.arch_news(update.last_update_time())
    choice = decide(mode, packages.count, on_battery(), len(news), Path("/var/lib/pacman/db.lck").exists())
    print(f"auto-update: {choice.reason}")
    if not choice.install:
        record(branding, installed=False, reason=choice.reason, waiting=packages.count)
        return 0
    rc = runner.run(["pacman", "-Syu", "--noconfirm"], check=False).returncode
    record(branding, installed=rc == 0, reason=choice.reason if rc == 0 else f"pacman failed ({rc})",
           waiting=0 if rc == 0 else packages.count)
    return rc


def run_user(branding: Branding | None = None, runner: util.Runner | None = None) -> int:
    """The user timer: refresh the desktop configuration after an unattended update, and notify about what waits."""
    from . import update

    branding = branding or load_branding()
    runner = runner or util.Runner()
    mode = read_mode(branding)
    if mode == "off":
        return 0
    last = read_record(branding)
    if last.get("installed"):
        for line in update.apply_desktop(branding, log=lambda m: None):
            print(line)
    sources = update.check_all(branding, ["packages", "aur", "flatpak", "desktop", "ai"])
    waiting = {s.label: s.count for s in sources if s.available and not s.error and s.count}
    if not waiting:
        return 0
    body = ", ".join(f"{label}: {count}" for label, count in waiting.items())
    if mode == "apply" and last.get("reason") and not last.get("installed"):
        body += f". Not installed automatically: {last['reason']}."
    if util.which("notify-send"):
        done = runner.run(["notify-send", "-a", branding.pretty_name, "-i", "system-software-update",
                           "-A", "open=Open the updater", "Updates are waiting", body], check=False, capture=True)
        if (done.stdout or "").strip() == "open":
            runner.run([f"{branding.id}-update"], check=False)
    else:
        print(f"Updates are waiting: {body}")
    return 0


def command_line(branding: Branding) -> str:
    """How the timers start this tool. Installed from the distribution's packages it is /usr/bin/<cli>; set up any other
    way (a source checkout, another install), it is this very Python running this copy of distrokit."""
    packaged = Path(f"/usr/bin/{branding.cli}")
    if packaged.exists():
        return str(packaged)
    which = util.which(branding.cli)
    if which:
        return which
    lib = Path(__file__).resolve().parents[2]  # .../lib, holding distrokit/
    return f"/usr/bin/env PYTHONPATH={lib} {sys.executable} -m distrokit"


def system_units(branding: Branding, command: str | None = None) -> dict[str, str]:
    """systemd units, by path under /usr/lib/systemd (or /etc/systemd): the system timer and the per-user one."""
    b = branding
    command = command or f"/usr/bin/{b.cli}"
    return {
        f"system/{b.id}-auto-update.service": (
            "[Unit]\n"
            f"Description={b.pretty_name} automatic updates (installs in apply mode; see {b.cli} auto-update)\n"
            "After=network-online.target\nWants=network-online.target\n"
            f"ConditionPathExists=!/etc/{b.id}/auto-update.disabled\n\n"
            "[Service]\nType=oneshot\n"
            f"ExecStart={command} auto-update run --system\n"
            "Nice=10\nIOSchedulingClass=idle\n"),
        f"system/{b.id}-auto-update.timer": (
            "[Unit]\n"
            f"Description=Daily {b.pretty_name} automatic updates\n\n"
            "[Timer]\nOnBootSec=15min\nOnUnitActiveSec=1d\nRandomizedDelaySec=1h\nPersistent=true\n\n"
            "[Install]\nWantedBy=timers.target\n"),
        f"user/{b.id}-update-notify.service": (
            "[Unit]\n"
            f"Description={b.pretty_name}: tell me when updates are waiting\n\n"
            "[Service]\nType=oneshot\n"
            f"ExecStart={command} auto-update run --user\n"),
        f"user/{b.id}-update-notify.timer": (
            "[Unit]\n"
            f"Description=Daily {b.pretty_name} update check\n\n"
            "[Timer]\nOnStartupSec=10min\nOnUnitActiveSec=1d\nRandomizedDelaySec=30min\nPersistent=true\n\n"
            "[Install]\nWantedBy=timers.target\n"),
    }


def timer_names(branding: Branding) -> tuple[str, str]:
    return f"{branding.id}-auto-update.timer", f"{branding.id}-update-notify.timer"


def install_units(branding: Branding, root: Path | str = "/", command: str | None = None) -> list[Path]:
    """Make the timers exist on this system, however it was installed. Units the distribution's packages ship in
    /usr/lib/systemd are left alone; any that are missing are written to /etc/systemd, pointing at this tool."""
    root = Path(root)
    written = []
    for unit, text in system_units(branding, command or command_line(branding)).items():
        if (root / "usr/lib/systemd" / unit).exists():
            continue
        path = root / "etc/systemd" / unit
        if path.exists() and path.read_text() == text:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        written.append(path)
    return written


def enable(branding: Branding | None = None, runner: util.Runner | None = None, root: Path | str = "/") -> list[str]:
    """Set up and start automatic updates (root): units where missing, the system timer on, the user timer on for
    every account."""
    branding = branding or load_branding()
    runner = runner or util.Runner()
    written = install_units(branding, root)
    system_timer, user_timer = timer_names(branding)
    runner.run(["systemctl", "daemon-reload"], check=False)
    runner.run(["systemctl", "enable", "--now", system_timer], check=False)
    runner.run(["systemctl", "--global", "enable", user_timer], check=False)
    lines = [f"wrote {p}" for p in written]
    lines.append(f"{system_timer} and {user_timer} are on (mode {read_mode(branding, root)})")
    return lines


def disable(branding: Branding | None = None, runner: util.Runner | None = None) -> list[str]:
    branding = branding or load_branding()
    runner = runner or util.Runner()
    system_timer, user_timer = timer_names(branding)
    runner.run(["systemctl", "disable", "--now", system_timer], check=False)
    runner.run(["systemctl", "--global", "disable", user_timer], check=False)
    return [f"{system_timer} and {user_timer} are off"]


def timers_enabled(branding: Branding, runner: util.Runner | None = None) -> bool:
    runner = runner or util.Runner()
    system_timer, _ = timer_names(branding)
    return runner.run(["systemctl", "is-enabled", "--quiet", system_timer], check=False, capture=True).returncode == 0


def status(branding: Branding | None = None) -> list[str]:
    branding = branding or load_branding()
    mode = read_mode(branding)
    last = read_record(branding)
    lines = [f"mode         {mode}  ({config_path(branding)})",
             f"timers       {'on' if timers_enabled(branding) else 'off: sudo ' + branding.cli + ' auto-update enable'}"]
    if last:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(last.get("time", 0)))
        lines.append(f"last run     {when}: {'installed' if last.get('installed') else 'nothing installed'}"
                     f" ({last.get('reason', '')})")
    else:
        lines.append("last run     never")
    return lines
