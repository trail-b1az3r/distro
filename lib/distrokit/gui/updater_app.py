"""The graphical updater, exposed to QML as ``updater``.

It shows what each source would update and then runs the same commands as
``<cli> update``, streaming their output. System packages are updated by
pacman (through the polkit-guarded helper), AUR packages by yay (which asks
for the password through pkexec), everything else as the user.
"""

from __future__ import annotations

import subprocess
import time

from PySide6.QtCore import Property, QObject, Signal, Slot

from .. import paths, util
from ..branding import load as load_branding
from ..system import update
from . import common


class UpdaterBackend(QObject):
    changed = Signal()
    busyChanged = Signal()
    log = Signal(str)
    finished = Signal(bool)

    def __init__(self):
        super().__init__()
        self.b = load_branding()
        self._sources: list[dict] = []
        self._news: list[dict] = []
        self._busy = False
        self._checked = False

    @Property("QVariant", notify=changed)
    def sources(self) -> list:
        return self._sources

    @Property("QVariant", notify=changed)
    def news(self) -> list:
        return self._news

    @Property(bool, notify=changed)
    def checked(self) -> bool:
        return self._checked

    @Property(int, notify=changed)
    def total(self) -> int:
        return sum(s["count"] for s in self._sources if s["available"] and not s["error"])

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    def _set_busy(self, v: bool) -> None:
        self._busy = v
        self.busyChanged.emit()

    @Slot()
    def check(self) -> None:
        if self._busy:
            return
        self._set_busy(True)

        def work():
            news = [n.__dict__ for n in update.arch_news(update.last_update_time())]
            return [s.to_dict() for s in update.check_all(self.b)], news

        def done(result):
            self._sources, self._news = result
            for n in self._news:
                n["date"] = time.strftime("%Y-%m-%d", time.localtime(n["published"]))
            self._checked = True
            self._set_busy(False)
            self.changed.emit()

        common.run_async(work, done, lambda e: (self._set_busy(False), self.log.emit(f"Check failed: {e}")))

    def _stream(self, cmd: list[str]) -> int:
        self.log.emit("$ " + " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert proc.stdout
        for line in proc.stdout:
            self.log.emit(line.rstrip("\n"))
        return proc.wait()

    @Slot("QVariant")
    def apply(self, ids) -> None:
        if hasattr(ids, "toVariant"):
            ids = ids.toVariant()
        wanted = [s for s in self._sources if s["id"] in ids and s["count"] and s["available"]]
        if self._busy or not wanted:
            return
        self._set_busy(True)
        helper = f"/usr/lib/{self.b.id}/bin/{self.b.id}-privileged"

        def work():
            ok = True
            for s in wanted:
                self.log.emit(f"== {s['label']} ==")
                if s["id"] == "packages":
                    ok &= self._stream(["pkexec", helper, "update-system"]) == 0
                elif s["id"] == "aur":
                    ok &= self._stream(["yay", "-Sua", "--noconfirm", "--sudo", "pkexec", "--answerdiff", "None",
                                        "--answerclean", "None"]) == 0
                elif s["id"] == "flatpak":
                    ok &= self._stream(["flatpak", "update", "-y", "--noninteractive"]) == 0
                elif s["id"] == "desktop":
                    for line in update.apply_desktop(self.b, log=self.log.emit):
                        self.log.emit(line)
                elif s["id"] == "ai":
                    done = update.apply_ai(util.Runner(log=self.log.emit), self.b)
                    self.log.emit("Updated: " + ", ".join(done))
                elif s["id"] == "gpu":
                    ok &= self._stream(["pkexec", helper, "gpu-configure"]) == 0
            return ok

        def done(ok):
            self._set_busy(False)
            self.log.emit("Update complete." if ok else "Some updates failed; see the log above. "
                          f"You can also run `{self.b.cli} update` in a terminal.")
            self.finished.emit(bool(ok))
            self.check()

        common.run_async(work, done, lambda e: (self._set_busy(False), self.log.emit(f"Error: {e}")))

    @Slot()
    def openTerminal(self) -> None:  # noqa: N802
        common.Launcher().runInTerminal(f"{self.b.cli} update")


def main(argv: list[str] | None = None) -> int:
    app = common.make_app("update", "System Update")
    backend = UpdaterBackend()
    engine, _w = common.load_qml(app, paths.qml_dir() / "updater" / "Main.qml",
                                 {"updater": backend, "launcher": common.Launcher(), "iconDir": str(common.icon_dir())})
    if not engine.rootObjects():
        return 1
    backend.check()
    return app.exec()

