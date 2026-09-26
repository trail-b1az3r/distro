"""Qt/QML plumbing shared by the graphical applications."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QIcon, QImage, QPainter
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer

from .. import paths
from ..branding import Branding, load as load_branding


def icon_dir() -> Path:
    return paths.data("branding", "icons", "ui")


class IconProvider(QQuickImageProvider):
    """``image://icon/<name>/<rrggbb>``: an SVG icon stroked in a colour."""

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._cache: dict[str, str] = {}

    def requestImage(self, id_: str, size: QSize, requested: QSize) -> QImage:  # noqa: N802 (Qt API)
        name, _, color = id_.partition("/")
        if len(color) == 8:  # aarrggbb
            color = color[2:]
        svg = self._cache.get(name)
        if svg is None:
            path = icon_dir() / f"{Path(name).name}.svg"
            svg = path.read_text() if path.exists() else ""
            self._cache[name] = svg
        w = requested.width() if requested.width() > 0 else 48
        h = requested.height() if requested.height() > 0 else 48
        image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        if svg:
            renderer = QSvgRenderer(svg.replace("currentColor", f"#{color or 'ffffff'}").encode())
            painter = QPainter(image)
            renderer.render(painter)
            painter.end()
        if size is not None:
            size.setWidth(w)
            size.setHeight(h)
        return image


def brand_info(b: Branding) -> dict[str, str]:
    return {
        "name": b.name,
        "prettyName": b.pretty_name,
        "id": b.id,
        "cli": b.cli,
        "tagline": b.get("DISTRO_TAGLINE"),
        "homeUrl": b.get("DISTRO_HOME_URL"),
        "docUrl": b.get("DISTRO_DOC_URL"),
        "supportUrl": b.get("DISTRO_SUPPORT_URL"),
        "bg": b.get("BRAND_BG"),
        "surface": b.get("BRAND_SURFACE"),
        "fg": b.get("BRAND_FG"),
        "muted": b.get("BRAND_MUTED"),
        "accent": b.get("BRAND_ACCENT"),
        "accent2": b.get("BRAND_ACCENT_2"),
        "warning": b.get("BRAND_WARNING"),
        "danger": b.get("BRAND_DANGER"),
        "logo": QUrl.fromLocalFile(str(paths.data("branding", "generated", "logo", "logo-mark.svg"))).toString(),
    }


def make_app(app_id: str, title: str) -> QGuiApplication:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    b = load_branding()
    app.setApplicationName(title)
    app.setApplicationDisplayName(title)
    app.setOrganizationName(b.name)
    app.setDesktopFileName(f"{b.id}-{app_id}")
    logo = paths.data("branding", "generated", "logo", "logo-mark.svg")
    if logo.exists():
        app.setWindowIcon(QIcon(str(logo)))
    return app


class QmlWarnings:
    """Collects QML warnings; tests fail on any."""

    def __init__(self):
        self.items: list[str] = []

    def __call__(self, warnings) -> None:
        for w in warnings:
            text = w.toString()
            self.items.append(text)
            print(f"QML: {text}", file=sys.stderr)


def load_qml(app: QGuiApplication, qml_file: Path, context: dict[str, Any]) -> tuple[QQmlApplicationEngine, QmlWarnings]:
    b = load_branding()
    engine = QQmlApplicationEngine()
    warnings = QmlWarnings()
    engine.warnings.connect(warnings)
    engine.addImportPath(str(paths.qml_dir()))
    engine.addImageProvider("icon", IconProvider())
    ctx = engine.rootContext()
    ctx.setContextProperty("brandInfo", brand_info(b))
    for name, obj in context.items():
        ctx.setContextProperty(name, obj)
    engine.load(QUrl.fromLocalFile(str(qml_file)))
    return engine, warnings


# ---------------------------------------------------------------------------
# Background work
# ---------------------------------------------------------------------------


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Job(QRunnable):
    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.signals.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.signals.done.emit(result)


_KEEP: set[_Job] = set()


def run_async(fn: Callable[[], Any], on_done: Callable[[Any], None], on_error: Callable[[str], None] | None = None) -> None:
    """Run ``fn`` on the thread pool; callbacks run on the GUI thread."""
    job = _Job(fn)
    _KEEP.add(job)
    job.signals.done.connect(lambda r: (_KEEP.discard(job), on_done(r)))
    job.signals.failed.connect(lambda e: (_KEEP.discard(job), (on_error or (lambda _e: None))(e)))
    job.setAutoDelete(False)
    QThreadPool.globalInstance().start(job)


class Launcher(QObject):
    """Small helpers every app exposes to QML."""

    @Slot(str)
    def openUrl(self, url: str) -> None:  # noqa: N802
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(url))

    @Slot(str, result=bool)
    def run(self, command: str) -> bool:  # noqa: N802
        import shlex
        import subprocess

        try:
            subprocess.Popen(shlex.split(command), start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            return False

    @Slot(str, result=bool)
    def runInTerminal(self, command: str) -> bool:  # noqa: N802
        import shlex

        from ..ai.launcher import terminal_command

        try:
            cmd = terminal_command(shlex.split(command), hold=True)
        except RuntimeError:
            return False
        return self.run(shlex.join(cmd))
