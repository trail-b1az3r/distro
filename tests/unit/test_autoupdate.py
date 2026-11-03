"""Automatic updates (system/autoupdate.py): the mode file, when an unattended install holds back, the units, and
the CLI."""

from pathlib import Path

import pytest

from distrokit.branding import load as load_branding
from distrokit.system import autoupdate

B = load_branding()


def test_mode_defaults_to_notify_and_round_trips(tmp_path):
    assert autoupdate.read_mode(B, tmp_path) == "notify"
    path = autoupdate.write_mode("apply", B, tmp_path)
    assert path == tmp_path / f"etc/{B.id}/auto-update.conf"
    assert autoupdate.read_mode(B, tmp_path) == "apply"
    with pytest.raises(ValueError):
        autoupdate.write_mode("always", B, tmp_path)


@pytest.mark.parametrize("mode,waiting,battery,news,locked,install,why", [
    ("notify", 5, False, 0, False, False, "mode is notify"),
    ("apply", 0, False, 0, False, False, "up to date"),
    ("apply", 5, True, 0, False, False, "battery"),
    ("apply", 5, False, 2, False, False, "news"),
    ("apply", 5, False, 0, True, False, "locked"),
    ("apply", 5, False, 0, False, True, "5 package update"),
])
def test_unattended_install_holds_back_when_unsafe(mode, waiting, battery, news, locked, install, why):
    choice = autoupdate.decide(mode, waiting, battery, news, locked)
    assert choice.install is install
    assert why in choice.reason


def _supply(root: Path, name: str, kind: str, online: str | None = None) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "type").write_text(kind + "\n")
    if online is not None:
        (d / "online").write_text(online + "\n")


def test_on_battery(tmp_path):
    assert autoupdate.on_battery(tmp_path / "none") is False          # no power_supply: a desktop
    _supply(tmp_path, "BAT0", "Battery")
    _supply(tmp_path, "AC", "Mains", "0")
    assert autoupdate.on_battery(tmp_path) is True
    (tmp_path / "AC/online").write_text("1\n")
    assert autoupdate.on_battery(tmp_path) is False


def test_units():
    units = autoupdate.system_units(B)
    service = units[f"system/{B.id}-auto-update.service"]
    assert f"ExecStart=/usr/bin/{B.cli} auto-update run --system" in service
    assert "WantedBy=timers.target" in units[f"system/{B.id}-auto-update.timer"]
    assert "auto-update run --user" in units[f"user/{B.id}-update-notify.service"]


def test_cli_parses():
    from distrokit.cli import build_parser

    a = build_parser().parse_args(["auto-update", "mode", "apply"])
    assert (a.action, a.value) == ("mode", "apply")
    a = build_parser().parse_args(["auto-update", "run", "--user"])
    assert a.user and not a.system


def test_units_follow_the_tool_wherever_it_lives(monkeypatch):
    monkeypatch.setattr(autoupdate.util, "which", lambda name: None)
    monkeypatch.setattr(autoupdate.Path, "exists", lambda self: False if str(self) == f"/usr/bin/{B.cli}" else Path.exists(self))
    line = autoupdate.command_line(B)
    assert "-m distrokit" in line and "PYTHONPATH=" in line
    units = autoupdate.system_units(B, line)
    assert f"ExecStart={line} auto-update run --system" in units[f"system/{B.id}-auto-update.service"]


def test_install_units_fills_in_only_what_the_packages_did_not(tmp_path):
    packaged = tmp_path / f"usr/lib/systemd/system/{B.id}-auto-update.timer"
    packaged.parent.mkdir(parents=True)
    packaged.write_text("from the package\n")
    written = autoupdate.install_units(B, tmp_path, command="/opt/nexora/bin/nexora")
    names = sorted(p.relative_to(tmp_path).as_posix() for p in written)
    assert names == [f"etc/systemd/system/{B.id}-auto-update.service",
                     f"etc/systemd/user/{B.id}-update-notify.service",
                     f"etc/systemd/user/{B.id}-update-notify.timer"]
    service = (tmp_path / f"etc/systemd/system/{B.id}-auto-update.service").read_text()
    assert "ExecStart=/opt/nexora/bin/nexora auto-update run --system" in service
    # Run again: nothing to write.
    assert autoupdate.install_units(B, tmp_path, command="/opt/nexora/bin/nexora") == []


def test_enable_turns_both_timers_on(tmp_path):
    from distrokit import util

    runner = util.Runner(dry_run=True)
    lines = autoupdate.enable(B, runner, tmp_path)
    cmds = [" ".join(c) for c in runner.recorded]
    assert f"systemctl enable --now {B.id}-auto-update.timer" in cmds
    assert f"systemctl --global enable {B.id}-update-notify.timer" in cmds
    assert any("are on" in line for line in lines)


def test_cli_has_enable_and_disable():
    from distrokit.cli import build_parser

    assert build_parser().parse_args(["auto-update", "enable"]).action == "enable"
    assert build_parser().parse_args(["auto-update", "disable"]).action == "disable"
