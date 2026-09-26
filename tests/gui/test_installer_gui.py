"""The graphical installer, driven offscreen.

Loads the real QML with the real backend on a fixture machine, visits every
page (wide and narrow window, dark and light theme), runs a demo
installation through the real engine in dry-run mode, and fails on any QML
warning.
"""

import os

import pytest

pytest.importorskip("PySide6.QtQuick")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QMetaObject, QTimer  # noqa: E402

from distrokit import paths  # noqa: E402
from distrokit.gui import common  # noqa: E402
from distrokit.gui.installer_app import InstallerBackend  # noqa: E402


def spin(ms: int = 60) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_for(predicate, timeout_ms: int = 20000) -> bool:
    waited = 0
    while waited < timeout_ms:
        if predicate():
            return True
        spin(50)
        waited += 50
    return predicate()


@pytest.fixture(scope="module")
def app():
    from distrokit.build import branding

    branding.generate(quick=True, log=lambda _m: None)
    return common.make_app("installer", "Install")


@pytest.fixture
def ui(app, machine):
    root, _ = machine("hybrid_gtx1080_laptop")
    backend = InstallerBackend(demo=True, hardware_root=str(root))
    backend.demo_step_delay = 0.0
    engine, warnings = common.load_qml(app, paths.qml_dir() / "installer" / "Main.qml",
                                       {"installer": backend, "launcher": common.Launcher(),
                                        "iconDir": str(common.icon_dir())})
    assert engine.rootObjects(), "Main.qml failed to load"
    win = engine.rootObjects()[0]
    yield backend, win, warnings
    win.close()
    engine.deleteLater()
    spin(10)


def visit_all(backend, win) -> None:
    for i, pid in enumerate(backend.pages):
        if pid in ("install", "done"):
            continue
        if pid == "summary":
            backend.prepareSummary()
        win.setProperty("page", i)
        spin(40)


def test_every_page_loads_without_warnings(ui):
    backend, win, warnings = ui
    visit_all(backend, win)
    win.setProperty("width", 760)  # narrow: sidebar collapses to a progress header
    visit_all(backend, win)
    assert warnings.items == []


def test_validation_blocks_next_until_fields_are_valid(ui):
    backend, win, _ = ui
    user_page = backend.pages.index("user")
    win.setProperty("page", user_page)
    spin()
    QMetaObject.invokeMethod(win, "next")
    spin()
    assert win.property("page") == user_page  # missing username/password
    assert any("password" in i["field"] for i in win.property("issues"))
    backend.set("user.fullname", "Alex Doe")
    backend.set("user.password", "secret123")
    assert backend.config["user"]["username"] == "alex"  # suggested from the name
    QMetaObject.invokeMethod(win, "next")
    spin()
    assert win.property("page") == user_page + 1


def test_hardware_defaults_follow_detection(ui):
    backend, _win, _ = ui
    cards = backend.gpuCards
    assert {c["vendor"]: c["stack"] for c in cards} == {"intel": "intel", "nvidia": "nvidia-580xx"}
    backend.setGpuDriver(next(c["slot"] for c in cards if c["vendor"] == "nvidia"), "nouveau")
    assert next(c for c in backend.gpuCards if c["vendor"] == "nvidia")["stack"] == "nouveau"
    assert backend.surfaceInfo["detected"] is False and backend.config["surface_kernel"] is False
    ai = backend.ai
    assert ai["lines"] and any(c["suggested"] for c in ai["categories"])


def test_demo_installation_runs_to_the_end(ui):
    backend, win, warnings = ui
    backend.set("user.fullname", "Alex Doe")
    backend.set("user.password", "secret123")
    backend.set("hostname", "nexbox")
    backend.set("profile", "ai")
    backend.set("ai.model", "qwen3-8b")
    summary = backend.prepareSummary()
    assert summary["ok"], summary.get("error")
    assert summary["needsConfirm"] and summary["confirmToken"] == "/dev/nvme0n1"
    assert any(line.startswith("ERASE") for line in summary["destructive"])
    assert any("pacstrap" in c for c in backend.commands)
    assert not backend.install("/dev/wrong")  # confirmation must match
    win.setProperty("page", backend.pages.index("install"))
    assert backend.install("/dev/nvme0n1")
    assert wait_for(lambda: win.property("pageId") == "done", 30000), "installation did not finish"
    events = backend.history()
    assert [e for e in events if e["type"] == "done"]
    assert not [e for e in events if e["type"] == "error"]
    assert warnings.items == []


def test_light_theme_renders(ui):
    backend, win, warnings = ui
    win.setProperty("themeMode", "light")
    visit_all(backend, win)
    win.setProperty("themeMode", "dark")
    win.setProperty("page", backend.pages.index("disk"))
    spin()
    assert win.grabWindow().width() > 0
    assert warnings.items == []
