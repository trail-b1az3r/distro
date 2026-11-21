"""The login screen (SilentSDDM with the distribution's config, branding/sddm), loaded offscreen against stand-ins
for SDDM's greeter objects, as it is installed: branding/sddm with branding/generated/sddm on top.

``SDDM_SHOT=/path/prefix`` also saves screenshots of the lock and login screens."""

import configparser
import os
import shutil

import pytest

pytest.importorskip("PySide6.QtQuick", exc_type=ImportError)
# QtMultimedia (the theme's video backgrounds) also needs the system's PulseAudio library.
pytest.importorskip("PySide6.QtMultimedia", exc_type=ImportError)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Property, QByteArray, QEventLoop, QObject, Qt, QTimer, QUrl, Signal, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication, QStandardItem, QStandardItemModel  # noqa: E402
from PySide6.QtQml import QQmlPropertyMap  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402

from distrokit import paths  # noqa: E402
from distrokit.branding import load as load_branding  # noqa: E402

# SDDM's roles: UserModel (NameRole...), SessionModel (DirectoryRole...).
USER_NAME, USER_REAL, USER_HOME, USER_ICON, USER_NEEDS_PW = range(Qt.ItemDataRole.UserRole + 1, Qt.ItemDataRole.UserRole + 6)
SES_DIR, SES_FILE, SES_TYPE, SES_NAME, SES_EXEC, SES_COMMENT = range(Qt.ItemDataRole.UserRole + 1, Qt.ItemDataRole.UserRole + 7)


def spin(ms=300):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class Greeter(QObject):
    loginFailed = Signal()  # noqa: N815
    loginSucceeded = Signal()  # noqa: N815

    def __init__(self):
        super().__init__()
        self.attempts = []

    @Property(bool, constant=True)
    def canSuspend(self):  # noqa: N802
        return True

    @Property(bool, constant=True)
    def canReboot(self):  # noqa: N802
        return True

    @Property(bool, constant=True)
    def canPowerOff(self):  # noqa: N802
        return True

    @Property(str, constant=True)
    def hostName(self):  # noqa: N802
        return "frontline"

    currentUserChanged = Signal()  # noqa: N815

    def _get_user(self):
        return getattr(self, "_user", "alex")

    def _set_user(self, value):
        self._user = value
        self.currentUserChanged.emit()

    currentUser = Property(str, _get_user, _set_user, notify=currentUserChanged)  # noqa: N815

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

    @Property(bool, constant=True)
    def numLock(self):  # noqa: N802
        return True

    @Property("QVariantList", constant=True)
    def layouts(self):
        return []

    @Property(int, constant=True)
    def currentLayout(self):  # noqa: N802
        return -1


class Screens(QObject):
    """SDDM's screenModel: one 1600x900 screen."""

    @Property(int, constant=True)
    def primary(self):
        return 0

    @Slot(int, result="QRect")
    def geometry(self, _index):
        from PySide6.QtCore import QRect
        return QRect(0, 0, 1600, 900)


class Model(QStandardItemModel):
    def __init__(self, roles, rows):
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


class Config(QObject):
    """SDDM's theme config, as the theme uses it: ``config.stringValue("Section/key")`` and the other typed getters
    (keys of [General] have no section). The theme's two ``config["key"]`` reads only check for "false"."""

    def __init__(self, path):
        super().__init__()
        parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=None,
                                           comment_prefixes=(";", "#"), strict=False)
        parser.optionxform = str
        parser.read(path)
        self.values = {}
        for section in parser.sections():
            for key, value in parser.items(section):
                value = value.strip().strip('"')
                self.values[key if section == "General" else f"{section}/{key}"] = value

    @Slot(str, result=str)
    def stringValue(self, key):  # noqa: N802
        return self.values.get(key, "")

    @Slot(str, result=int)
    def intValue(self, key):  # noqa: N802
        try:
            return int(float(self.values.get(key, "0")))
        except ValueError:
            return 0

    @Slot(str, result=float)
    def realValue(self, key):  # noqa: N802
        try:
            return float(self.values.get(key, "0"))
        except ValueError:
            return 0.0

    @Slot(str, result=bool)
    def boolValue(self, key):  # noqa: N802
        return self.values.get(key, "").lower() == "true"


def sddm_components(tmp_path):
    """SDDM's own QML module, as far as the theme uses it (TextConstants)."""
    mod = tmp_path / "imports" / "SddmComponents"
    mod.mkdir(parents=True)
    (mod / "qmldir").write_text("module SddmComponents\nTextConstants 2.0 TextConstants.qml\n")
    props = {"login": "Login", "capslockWarning": "Caps Lock is on", "userName": "User name", "password": "Password",
             "suspend": "Suspend", "shutdown": "Shut down", "reboot": "Reboot", "promptUser": "Enter your user",
             "loginFailed": "Login failed", "loginSucceeded": "Login succeeded", "session": "Session",
             "layout": "Layout", "welcomeText": "Welcome"}
    (mod / "TextConstants.qml").write_text("import QtQuick\nQtObject {\n" + "".join(
        f'    readonly property string {k}: "{v}"\n' for k, v in props.items()) + "}\n")
    return tmp_path / "imports"


def installed_theme(tmp_path):
    from distrokit.build import branding

    branding.generate(quick=True, log=lambda _m: None)
    gen = paths.data("branding") / "generated" / "sddm"
    if not (gen / "backgrounds" / "default.jpg").is_file():
        pytest.skip("the login background is made by the full branding build (python3 -m distrokit.build.branding)")
    theme = tmp_path / "theme"
    shutil.copytree(paths.data("branding") / "sddm", theme, ignore=shutil.ignore_patterns("*.in", "UPSTREAM"))
    shutil.copytree(gen, theme, dirs_exist_ok=True)
    return theme


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_login_screen_loads_with_the_distributions_look(tmp_path):
    b = load_branding()
    theme = installed_theme(tmp_path)
    meta = (theme / "metadata.desktop").read_text()
    assert f"Theme-Id={b.id}\n" in meta and "ConfigFile=configs/theme.conf" in meta
    conf_text = (theme / "configs" / "theme.conf").read_text()
    assert "@" not in conf_text.replace("@possible", "")   # every token rendered
    assert b["BRAND_ACCENT"] in conf_text and b["BRAND_FG"] in conf_text

    app = QGuiApplication.instance() or QGuiApplication([])
    assert app
    greeter = Greeter()
    users = Model({USER_NAME: b"name", USER_REAL: b"realName", USER_HOME: b"homeDir", USER_ICON: b"icon",
                   USER_NEEDS_PW: b"needsPassword"},
                  [{USER_NAME: "alex", USER_REAL: "Alex Doe", USER_HOME: "/home/alex", USER_ICON: "",
                    USER_NEEDS_PW: True}])
    sessions = Model({SES_DIR: b"directory", SES_FILE: b"file", SES_TYPE: b"type", SES_NAME: b"name",
                      SES_EXEC: b"exec", SES_COMMENT: b"comment"},
                     [{SES_NAME: "Hyprland", SES_FILE: "hyprland.desktop", SES_COMMENT: "Halcyon"},
                      {SES_NAME: "ML4W", SES_FILE: f"{b.id}-ml4w.desktop", SES_COMMENT: "ML4W desktop profile"}])
    text = QQmlPropertyMap(None)
    for key, value in {"login": "Login", "capslockWarning": "Caps Lock is on", "userName": "User name",
                       "password": "Password", "suspend": "Suspend", "shutdown": "Shut down", "reboot": "Reboot",
                       "promptUser": "Enter your user", "loginFailed": "Login failed"}.items():
        text.insert(key, value)

    view = QQuickView()
    view.engine().addImportPath(str(sddm_components(tmp_path)))
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    warnings = []
    view.engine().warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
    ctx = view.rootContext()
    keyboard, config = Keyboard(), Config(theme / "configs" / "theme.conf")   # kept: QML holds no reference
    screens = Screens()
    for name, obj in {"sddm": greeter, "userModel": users, "sessionModel": sessions, "keyboard": keyboard,
                      "config": config, "textConstants": text, "screenModel": screens}.items():
        ctx.setContextProperty(name, obj)
    view.resize(1600, 900)
    view.setSource(QUrl.fromLocalFile(str(theme / "Main.qml")))
    assert view.status() == QQuickView.Status.Ready, [e.toString() for e in view.errors()]
    view.show()
    spin(800)
    shot = os.environ.get("SDDM_SHOT")
    if shot:
        view.grabWindow().save(f"{shot}-lock.png")
    # Any key leaves the lock screen for the login screen; Enter there logs in with the password typed.
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent

    def key(k, txt=""):
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QGuiApplication.sendEvent(view, QKeyEvent(kind, k, Qt.KeyboardModifier.NoModifier, txt))
        spin(120)
    key(Qt.Key.Key_Space, " ")
    spin(900)
    for ch in "hunter2":
        key(Qt.Key(ord(ch.upper())), ch)
    if shot:
        view.grabWindow().save(f"{shot}-login.png")
    key(Qt.Key.Key_Return, "\r")
    spin(600)
    assert greeter.attempts and greeter.attempts[0][0] == "alex"
    errors = [w for w in warnings if "Error" in w or "is not defined" in w or "Cannot" in w]
    assert not errors, errors
