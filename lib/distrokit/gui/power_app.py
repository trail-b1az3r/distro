"""The power menu (``<id>-power-menu``): lock, log out, sleep, hibernate, restart, shut down, restart to firmware.

The extra desktops' power button opens it (desktop/profiles/power-button.sh). It covers the screen, dimmed, so it
needs no window rules in any compositor; Escape, a click outside or the power button again closes it. Opening it
while it is open closes it (one per user, through a local socket).
"""

from __future__ import annotations

import os

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .. import paths
from ..branding import load as load_branding
from ..system import power
from . import common


class PowerBackend(QObject):
    closeRequested = Signal()  # noqa: N815

    def __init__(self, actions: list[power.Action] | None = None, run=None):
        super().__init__()
        self._actions = actions if actions is not None else power.actions()
        self._run = run

    @Property("QVariant", constant=True)
    def actions(self) -> list:
        return [{"id": a.id, "label": a.label, "icon": a.icon, "danger": a.danger} for a in self._actions]

    @Property(str, constant=True)
    def userName(self) -> str:  # noqa: N802
        return os.environ.get("USER", "")

    @Slot(str, result=bool)
    def perform(self, action_id: str) -> bool:
        for a in self._actions:
            if a.id == action_id:
                ok = power.perform(a, self._run) if self._run else power.perform(a)
                self.closeRequested.emit()
                return ok
        return False


def server_name() -> str:
    return f"{load_branding().id}-power-menu-{os.getuid()}"


def already_open() -> bool:
    """When a menu is open: ask it to close, and say so (the power button toggles the menu)."""
    sock = QLocalSocket()
    sock.connectToServer(server_name())
    if not sock.waitForConnected(300):
        return False
    sock.write(b"close\n")
    sock.flush()
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


def main(argv: list[str] | None = None) -> int:
    app = common.make_app("power-menu", "Power")
    if already_open():
        return 0
    backend = PowerBackend()
    QLocalServer.removeServer(server_name())
    server = QLocalServer()
    server.listen(server_name())
    server.newConnection.connect(lambda: (server.nextPendingConnection(), app.quit()))
    backend.closeRequested.connect(app.quit)
    engine, _w = common.load_qml(app, paths.qml_dir() / "power" / "Main.qml",
                                 {"power": backend, "iconDir": str(common.icon_dir())})
    if not engine.rootObjects():
        return 1
    return app.exec()
