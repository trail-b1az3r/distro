"""The first-boot wizard and welcome app, exposed to QML as ``welcome``."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from .. import paths, pkg, util
from ..ai import launcher, tools
from ..branding import load as load_branding
from ..tasks import TaskQueue
from . import common

APPS = [
    # id, name, package(s), category, description
    ("steam", "Steam", ["steam"], "Games", "PC games; uses the 32-bit graphics libraries."),
    ("obs", "OBS Studio", ["obs-studio"], "Media", "Screen recording and live streaming."),
    ("gimp", "GIMP", ["gimp"], "Graphics", "Photo editing and image manipulation."),
    ("krita", "Krita", ["krita"], "Graphics", "Digital painting, with pen support."),
    ("inkscape", "Inkscape", ["inkscape"], "Graphics", "Vector graphics."),
    ("blender", "Blender", ["blender"], "Graphics", "3D modelling, animation and rendering."),
    ("kdenlive", "Kdenlive", ["kdenlive"], "Media", "Video editing."),
    ("audacity", "Audacity", ["audacity"], "Media", "Audio recording and editing."),
    ("thunderbird", "Thunderbird", ["thunderbird"], "Internet", "Email and calendar."),
    ("chromium", "Chromium", ["chromium"], "Internet", "A second browser."),
    ("libreoffice", "LibreOffice", ["libreoffice-fresh"], "Office", "Office suite with ODF as its native format."),
    ("keepassxc", "KeePassXC", ["keepassxc"], "Utilities", "Offline password manager."),
    ("syncthing", "Syncthing", ["syncthing"], "Utilities", "Sync folders between your devices, peer to peer."),
    ("virt-manager", "Virtual Machine Manager", ["virt-manager", "qemu-desktop", "libvirt", "dnsmasq"], "Development",
     "Run virtual machines with QEMU/KVM."),
    ("filelight", "Filelight", ["filelight"], "Utilities", "See what uses your disk space."),
    ("timeshift", "Timeshift", ["timeshift"], "Utilities", "System snapshots for ext4 installations (rsync)."),
]


class WelcomeBackend(QObject):
    changed = Signal()
    tasksChanged = Signal()
    log = Signal(str)
    busyChanged = Signal()

    def __init__(self, first_boot: bool = False, home: Path | None = None):
        super().__init__()
        self.b = load_branding()
        self.first_boot = first_boot
        self.home = home or Path.home()
        self.state_dir = paths.user_state_dir(self.b.id, self.home)
        self._busy = False
        self._record = util.read_json(self.b.system_paths().install_record, {}) or {}
        self._queue = TaskQueue(self.b, self.home)

    # -- properties -----------------------------------------------------------
    @Property(bool, constant=True)
    def firstBoot(self) -> bool:  # noqa: N802
        return self.first_boot

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property("QVariant", notify=changed)
    def checklist(self) -> list:
        sp = self.b.system_paths()
        gpu_state = util.read_json(sp.gpu_state, None)
        items = [
            {"id": "hardware", "label": "Hardware configured", "ok": sp.hardware_report.exists() or bool(self._record)},
            {"id": "gpu", "label": "GPU configured", "ok": gpu_state is not None},
            {"id": "network", "label": "Network configured", "ok": self._network_ok()},
            {"id": "desktop", "label": "Desktop configured",
             "ok": (self.home / ".config" / "hypr" / self.b.id / "init.lua").exists()},
        ]
        pending = [t for t in self._queue.load() if t.status in ("pending", "failed", "running")]
        if pending:
            items.append({"id": "tasks", "label": f"{len(pending)} setup task(s) waiting", "ok": False})
        return items

    def _network_ok(self) -> bool:
        rc, out = util.run_quiet(["nmcli", "-t", "-f", "STATE", "general"], timeout=5)
        return rc == 0 and out.strip().startswith("connected")

    @Property("QVariant", notify=tasksChanged)
    def tasks(self) -> list:
        return [t.to_dict() | {"size": util.human_bytes(t.size_bytes) if t.size_bytes else ""} for t in self._queue.load()]

    @Property("QVariant", notify=changed)
    def gpu(self) -> list:
        from ..gpu import status as gpu_status
        from ..hardware import detect

        try:
            return [s.to_dict() for s in gpu_status.gather(detect(), branding=self.b)]
        except Exception as exc:  # noqa: BLE001
            return [{"vendor": "", "model": f"Could not read GPU status: {exc}", "status": "", "problems": []}]

    @Property("QVariant", notify=changed)
    def ai(self) -> list:
        return [e.to_dict() for e in launcher.entries(self.home, self.b)]

    @Property("QVariant", constant=True)
    def themes(self) -> list:
        base = self.home / ".config" / "hypr" / "hyprland" / "halcyon" / "themes"
        out = [{"id": "off", "name": "Wallpaper colours", "description": "Material You colours from your wallpaper (default)."}]
        for f in sorted(base.glob("*.json")) if base.is_dir() else []:
            try:
                data = json.loads(f.read_text())
            except ValueError:
                continue
            out.append({"id": f.stem, "name": data.get("name", f.stem),
                        "description": data.get("description", "")})
        return out

    @Property("QVariant", notify=changed)
    def apps(self) -> list:
        installed = pkg.installed_provides()
        return [{"id": a, "name": n, "packages": p, "category": c, "description": d,
                 "installed": all(x in installed for x in p)} for a, n, p, c, d in APPS]

    @Property("QVariant", notify=changed)
    def privacy(self) -> dict:
        rc, _ = util.run_quiet(["systemctl", "is-enabled", "--quiet", "nftables.service"])
        geo_rc, geo = util.run_quiet(["systemctl", "is-enabled", "geoclue.service"])
        return {
            "firewall": rc == 0,
            "macRandomization": Path(f"/etc/NetworkManager/conf.d/90-{self.b.id}-mac.conf").exists(),
            "location": geo.strip() != "masked",
            "coredumps": not Path(f"/etc/systemd/coredump.conf.d/90-{self.b.id}.conf").exists(),
        }

    @Property("QVariant", notify=changed)
    def backup(self) -> dict:
        fs = ""
        rc, out = util.run_quiet(["findmnt", "-n", "-o", "FSTYPE", "/"])
        if rc == 0:
            fs = out.strip()
        snapper = Path("/etc/snapper/configs/root").exists()
        count = 0
        if snapper and util.which("snapper"):
            rc, out = util.run_quiet(["snapper", "--no-dbus", "-c", "root", "list", "--columns", "number"], timeout=10)
            count = max(0, len([ln for ln in out.splitlines() if ln.strip().isdigit()]) - 0)
        rc, _ = util.run_quiet(["systemctl", "is-enabled", "--quiet", "snapper-timeline.timer"])
        return {"filesystem": fs, "snapper": snapper, "snapshots": count, "timeline": rc == 0,
                "timeshift": shutil.which("timeshift") is not None}

    # -- actions --------------------------------------------------------------
    def _set_busy(self, value: bool) -> None:
        self._busy = value
        self.busyChanged.emit()

    @Slot()
    def refresh(self) -> None:
        self.changed.emit()
        self.tasksChanged.emit()

    @Slot()
    def runTasks(self) -> None:  # noqa: N802
        if self._busy:
            return
        self._set_busy(True)

        def work():
            ctx = tools.UserContext.current(util.Runner(log=self.log.emit))
            return self._queue.run(ctx, log=self.log.emit,
                                   progress=lambda tid, d, t: self.log.emit(f"{tid}: {util.human_bytes(d)} / {util.human_bytes(t)}"))

        def done(failed):
            self._set_busy(False)
            self.log.emit("Setup tasks finished." if not failed else f"{len(failed)} task(s) failed; see above.")
            self.tasksChanged.emit()
            self.changed.emit()

        common.run_async(work, done, lambda e: (self._set_busy(False), self.log.emit(f"Error: {e}")))

    @Slot(str)
    def skipTask(self, task_id: str) -> None:  # noqa: N802
        self._queue.skip(task_id)
        self.tasksChanged.emit()

    def _privileged(self, *args: str) -> None:
        cmd = ["pkexec", f"/usr/lib/{self.b.id}/bin/{self.b.id}-privileged", *args]
        self._set_busy(True)

        def work():
            res = subprocess.run(cmd, capture_output=True, text=True)
            return res.returncode, res.stdout + res.stderr

        def done(result):
            rc, out = result
            for line in out.splitlines():
                self.log.emit(line)
            if rc != 0:
                self.log.emit(f"Failed (exit {rc}).")
            self._set_busy(False)
            self.changed.emit()

        common.run_async(work, done, lambda e: (self._set_busy(False), self.log.emit(f"Error: {e}")))

    @Slot(str, bool)
    def setPrivacy(self, key: str, value: bool) -> None:  # noqa: N802
        action = {"firewall": "firewall", "macRandomization": "mac-randomization", "location": "location",
                  "coredumps": "coredumps"}[key]
        self._privileged(action, "on" if value else "off")

    @Slot()
    def snapshotNow(self) -> None:  # noqa: N802
        self._privileged("snapshot", "Manual snapshot from Welcome")

    @Slot(bool)
    def setTimeline(self, value: bool) -> None:  # noqa: N802
        self._privileged("snapshot-timeline", "on" if value else "off")

    @Slot(str)
    def installApp(self, app_id: str) -> None:  # noqa: N802
        app = next(a for a in APPS if a[0] == app_id)
        self._privileged("install", *app[2])

    @Slot(str)
    def applyTheme(self, theme_id: str) -> None:  # noqa: N802
        tool = self.home / ".config" / "hypr" / "hyprland" / "halcyon" / "halcyon-theme"
        if tool.exists():
            args = ["off"] if theme_id == "off" else ["apply", theme_id]
            subprocess.Popen([str(tool), *args], start_new_session=True)
            self.log.emit(f"Theme: {theme_id}")

    @Slot(str, str)
    def launchAi(self, entry_id: str, action: str) -> None:  # noqa: N802
        try:
            launcher.launch(entry_id, action or "run")
        except Exception as exc:  # noqa: BLE001
            self.log.emit(f"Could not start {entry_id}: {exc}")

    @Slot()
    def finish(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "firstboot-done").touch()


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--first-boot", action="store_true")
    a = p.parse_args(argv)
    b = load_branding()
    app = common.make_app("welcome", f"Welcome to {b.name}")
    backend = WelcomeBackend(first_boot=a.first_boot)
    engine, _w = common.load_qml(app, paths.qml_dir() / "welcome" / "Main.qml",
                                 {"welcome": backend, "launcher": common.Launcher(), "iconDir": str(common.icon_dir())})
    if not engine.rootObjects():
        return 1
    os.environ.setdefault("PATH", "")
    return app.exec()
