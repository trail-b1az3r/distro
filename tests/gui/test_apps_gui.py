"""Welcome, updater and AI launcher windows, driven offscreen."""

import os

import pytest

pytest.importorskip("PySide6.QtQuick")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

from distrokit import hardware, paths  # noqa: E402
from distrokit.gui import common  # noqa: E402


def spin(ms: int = 60) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.fixture(scope="module")
def app():
    from distrokit.build import branding

    branding.generate(quick=True, log=lambda _m: None)
    return common.make_app("test", "Test")


def load(app, qml: str, context: dict):
    ctx = {"launcher": common.Launcher(), "iconDir": str(common.icon_dir()), **context}
    engine, warnings = common.load_qml(app, paths.qml_dir() / qml, ctx)
    assert engine.rootObjects(), f"{qml} failed to load"
    return engine, engine.rootObjects()[0], warnings


def test_welcome_sections(app, tmp_path, monkeypatch):
    from distrokit.gui.welcome_app import WelcomeBackend
    from distrokit.tasks import Task, TaskQueue

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    backend = WelcomeBackend(first_boot=True, home=tmp_path)
    TaskQueue(backend.b, tmp_path).add(Task("model:qwen3-8b", "model", "Model: Qwen3 8B", {"model": "qwen3-8b"}, size_bytes=5 * 10**9))
    engine, win, warnings = load(app, "welcome/Main.qml", {"welcome": backend})
    for section in ("home", "updates", "ai", "appearance", "apps", "privacy", "backup", "help"):
        win.setProperty("section", section)
        spin()
    win.setProperty("width", 700)
    spin()
    assert [t["id"] for t in backend.tasks] == ["model:qwen3-8b"]
    assert any(i["id"] == "tasks" for i in backend.checklist)
    backend.finish()
    assert (tmp_path / "state" / "nexora" / "firstboot-done").exists() or (backend.state_dir / "firstboot-done").exists()
    assert warnings.items == []
    engine.deleteLater()


def test_updater_window(app):
    from distrokit.gui.updater_app import UpdaterBackend

    backend = UpdaterBackend()
    backend._sources = [
        {"id": "packages", "label": "System packages (pacman)", "count": 2, "available": True, "error": "",
         "needs_root": True, "command": ["pacman", "-Syu"],
         "items": [{"name": "linux", "current": "6.16.1", "new": "6.16.2"}, {"name": "mesa", "current": "25.2.0", "new": "25.2.1"}]},
        {"id": "aur", "label": "AUR packages (yay)", "count": 0, "available": True, "error": "", "needs_root": False,
         "command": ["yay", "-Sua"], "items": []},
    ]
    backend._news = [{"title": "Manual intervention required", "link": "https://archlinux.org/news/", "published": 0, "date": "2026-09-20"}]
    backend._checked = True
    engine, win, warnings = load(app, "updater/Main.qml", {"updater": backend})
    backend.changed.emit()
    spin(100)
    assert backend.total == 2
    assert warnings.items == []
    engine.deleteLater()


def test_ai_window(app, machine, tmp_path):
    from distrokit.ai import models
    from distrokit.gui.ai_app import AiBackend

    root, report = machine("rtx4080_desktop")
    backend = AiBackend("launcher", home=tmp_path, report=report)
    reg = models.Registry(backend.b.id, tmp_path)
    reg.add("qwen3-8b", {"name": "Qwen3 8B", "path": str(tmp_path / "m.gguf"), "context": 8192})
    engine, win, warnings = load(app, "ai/Main.qml", {"ai": backend})
    spin()
    win.setProperty("tab", "models")
    spin(100)
    assert backend.recommendation["lines"][0] == "7B–14B quantized"
    assert "qwen3-8b" in backend.installed["models"]
    backend.setDefault("qwen3-8b")
    ids = [e["id"] for e in backend.entries]
    assert ids == ["hypernix", "hermis", "openclaw", "claude-code", "local-model"]
    assert warnings.items == []
    engine.deleteLater()
