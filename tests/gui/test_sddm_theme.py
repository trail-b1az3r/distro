"""The SDDM login theme, loaded offscreen against stand-ins for SDDM's greeter
objects (``sddm``, ``userModel``, ``sessionModel``, ``keyboard``, ``config``)."""

import os

import pytest

pytest.importorskip("PySide6.QtQuick")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Property, QByteArray, QEventLoop, QObject, Qt, QTimer, QUrl, Signal, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication, QStandardItem, QStandardItemModel  # noqa: E402
from PySide6.QtQml import QQmlPropertyMap  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402

from distrokit import paths  # noqa: E402
from distrokit.branding import load as load_branding  # noqa: E402

NAME, REAL_NAME = Qt.ItemDataRole.UserRole + 1, Qt.ItemDataRole.UserRole + 2
SESSION_NAME = Qt.ItemDataRole.UserRole + 3


class Greeter(QObject):
    loginFailed = Signal()  # noqa: N815
    loginSucceeded = Signal()  # noqa: N815

    def __init__(self):
        super().__init__()
        self.attempts: list[tuple[str, str, int]] = []

    @Property(bool, constant=True)
    def canSuspend(self):  # noqa: N802
        return True

    @Property(bool, constant=True)
    def canReboot(self):  # noqa: N802
        return True

    @Property(bool, constant=True)
    def canPowerOff(self):  # noqa: N802
        return True

    @Slot(str, str, int)
    def login(self, user, password, session):
        self.attempts.append((user, password, session))
        self.loginFailed.emit()

    @Slot()
    def suspend(self):
        pass

    @Slot()
    def reboot(self):
        pass

    @Slot()
    def powerOff(self):  # noqa: N802
        pass


class Keyboard(QObject):
    @Property(bool, constant=True)
    def capsLock(self):  # noqa: N802
        return False


class Model(QStandardItemModel):
    def __init__(self, roles: dict[int, bytes], rows: list[dict[int, str]]):
        super().__init__()
        self._roles = roles
        for row in rows:
            item = QStandardItem()
            for role, value in row.items():
                item.setData(value, role)
            self.appendRow(item)

    def roleNames(self):
        return {k: QByteArray(v) for k, v in self._roles.items()}

    @Property(int, constant=True)
    def lastIndex(self):  # noqa: N802
        return 0

    @Property(int, constant=True)
    def count(self):
        return self.rowCount()


def spin(ms: int = 100) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_sddm_theme_loads_and_logs_in(tmp_path):
    from distrokit.build import branding

    b = load_branding()
    branding.generate(quick=True, log=lambda _m: None)
    theme = paths.data("branding") / "generated" / "sddm"
    app = QGuiApplication.instance() or QGuiApplication([])
    assert app

    greeter = Greeter()
    users = Model({NAME: b"name", REAL_NAME: b"realName"}, [{NAME: "alex", REAL_NAME: "Alex Doe"}])
    sessions = Model({SESSION_NAME: b"name"}, [{SESSION_NAME: "Hyprland"}, {SESSION_NAME: "Plasma (Wayland)"}])
    config = QQmlPropertyMap(None)
    conf = (paths.data("branding") / "generated" / "sddm" / "theme.conf").read_text()
    for line in conf.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            config.insert(k, v)
    keyboard = Keyboard()

    view = QQuickView()
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    warnings = []
    view.engine().warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
    ctx = view.rootContext()
    for name, obj in {"sddm": greeter, "userModel": users, "sessionModel": sessions, "config": config,
                      "keyboard": keyboard}.items():
        ctx.setContextProperty(name, obj)
    view.setSource(QUrl.fromLocalFile(str(theme / "Main.qml")))
    assert view.status() == QQuickView.Status.Ready, [e.toString() for e in view.errors()]
    view.resize(1280, 800)
    view.show()
    spin()

    root = view.rootObject()
    assert config.value("distroName") == b.pretty_name
    root.setProperty("sessionIndex", 1)
    password = root.findChild(QObject, "password")
    password.setProperty("text", "hunter2")
    root.metaObject().invokeMethod(root, "doLogin")
    spin()
    assert greeter.attempts == [("alex", "hunter2", 1)]
    assert root.property("errorText")
    assert password.property("text") == ""
    # Raster artwork is not generated in quick mode.
    assert [w for w in warnings if ".png" not in w] == []
    view.grabWindow().save(str(tmp_path / "sddm.png"))
