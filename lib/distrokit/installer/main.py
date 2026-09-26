"""``<id>-installer``: the graphical installer, unattended installs, and the
privileged engine the graphical installer drives.

    <id>-installer                         graphical installer
    <id>-installer --config install.json   unattended installation
    <id>-installer --config f --dry-run    print every command, change nothing
    <id>-installer --engine                (internal) read a config on stdin,
                                           install, report JSON lines on stdout

The graphical front end runs as the live user and starts ``--engine``
through sudo, so the UI itself never runs as root.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .. import hardware, util
from ..branding import load as load_branding
from ..profiles import load_features, load_profiles
from . import config as cfgmod
from .engine import Engine, human, json_lines
from .steps import Installation, dry_run_commands, is_online, summary


def _hardware(root: str = "/"):
    b = load_branding()
    return hardware.detect(root, live_label_prefix=b["ISO_LABEL_PREFIX"])


def prepare(cfg: cfgmod.InstallConfig, report, runner: util.Runner, online: bool | None = None) -> tuple[Installation, list]:
    issues = cfgmod.validate(
        cfg,
        uefi=report.firmware.uefi,
        profiles=set(load_profiles()),
        features=load_features(),
        disks={d.path: d.size_bytes for d in report.installable_disks},
    )
    if cfgmod.errors(issues):
        return None, issues  # type: ignore[return-value]
    inst = Installation(cfg, report, runner=runner, online=online)
    return inst, issues


def run_unattended(args) -> int:
    b = load_branding()
    style = util.style
    cfg = cfgmod.InstallConfig.load(Path(args.config))
    # Secrets can come from the environment instead of the file.
    cfg.user.password = os.environ.get("INSTALL_USER_PASSWORD", cfg.user.password)
    cfg.user.root_password = os.environ.get("INSTALL_ROOT_PASSWORD", cfg.user.root_password)
    cfg.disk.passphrase = os.environ.get("INSTALL_DISK_PASSPHRASE", cfg.disk.passphrase)
    report = _hardware(args.hardware_root)
    runner = util.Runner(dry_run=args.dry_run)
    online = False if cfg.offline else (True if args.dry_run else is_online())
    inst, issues = prepare(cfg, report, runner, online)
    for i in issues:
        print((style.fail if i.severity == "error" else style.warn)(str(i)), file=sys.stderr)
    if inst is None:
        return 2
    s = summary(inst)
    print(style.header(f"{b.pretty_name} — installation plan"))
    print(util.table([("Profile", s["profile"]), ("Boot", f"{s['bootloader']} ({s['firmware']})"),
                      ("User", s["user"]), ("Hostname", s["hostname"]), ("Packages", str(s["packages"])),
                      ("AI backend", s["ai"]["backend"]), ("Network", "online" if s["online"] else "offline")]))
    for line in s["gpu"]:
        print(style.info(line))
    print(style.header("Disk changes"))
    for line in s["destructive"]:
        print(style.warn(line) if line.startswith(("ERASE", "FORMAT")) else "  " + line)
    for w in s["warnings"]:
        print(style.warn(w))
    if args.dry_run:
        print(style.header("Commands (dry run)"))
        for c in dry_run_commands(inst):
            print("  " + c)
        return 0
    if inst.disk_plan.destructive and not args.yes_i_understand:
        if not sys.stdin.isatty():
            print(style.fail("Refusing to modify disks without --yes-i-understand in a non-interactive run."), file=sys.stderr)
            return 3
        answer = input(f"Type the disk path ({inst.disk_plan.disk or 'manual'}) to confirm: ").strip()
        if answer != (inst.disk_plan.disk or "manual"):
            print("Cancelled; nothing was changed.")
            return 1
    log_file = Path(f"/var/log/{b.id}/installer.log")
    emit = json_lines() if args.json_progress else human(verbose=args.verbose)
    ok = Engine(inst, emit, log_file).run()
    return 0 if ok else 1


def run_engine(args) -> int:
    """Privileged engine for the GUI: config JSON on stdin, events on stdout."""
    b = load_branding()
    if os.geteuid() != 0 and not args.dry_run:
        json_lines()({"type": "error", "step": "preflight", "label": "Permissions", "message": "the engine must run as root"})
        return 1
    data = json.loads(sys.stdin.read())
    cfg = cfgmod.InstallConfig.from_dict(data["config"])
    report = _hardware(args.hardware_root)
    emit = json_lines()
    runner = util.Runner(dry_run=args.dry_run)
    online = data.get("online")
    inst, issues = prepare(cfg, report, runner, online if online is not None else (not cfg.offline and is_online()))
    if inst is None:
        emit({"type": "error", "step": "validate", "label": "Configuration",
              "message": "; ".join(str(i) for i in cfgmod.errors(issues))})
        return 2
    # The disk the user confirmed must still be the disk we are about to write.
    expected = data.get("confirm_disk")
    if inst.disk_plan.destructive and expected != (inst.disk_plan.disk or "manual"):
        emit({"type": "error", "step": "validate", "label": "Confirmation",
              "message": "the disk confirmation does not match the plan; nothing was changed"})
        return 3
    log_file = None if args.dry_run else Path(f"/var/log/{b.id}/installer.log")
    ok = Engine(inst, emit, log_file).run()
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog=f"{load_branding().id}-installer")
    p.add_argument("--config", help="unattended installation from a JSON configuration")
    p.add_argument("--dry-run", action="store_true", help="show the plan and commands without changing anything")
    p.add_argument("--yes-i-understand", action="store_true", help="do not ask before erasing/formatting (unattended)")
    p.add_argument("--json-progress", action="store_true", help="report progress as JSON lines")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--engine", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--hardware-root", default="/", help=argparse.SUPPRESS)
    p.add_argument("--demo", action="store_true", help="GUI: use a simulated machine and never touch disks")
    args = p.parse_args(argv)
    if args.engine:
        return run_engine(args)
    if args.config:
        return run_unattended(args)
    from ..gui import installer_app

    return installer_app.main(demo=args.demo or args.dry_run, hardware_root=args.hardware_root)


if __name__ == "__main__":
    sys.exit(main())
