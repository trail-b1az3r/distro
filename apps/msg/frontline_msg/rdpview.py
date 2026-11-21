"""The remote desktop in the window: a QML item (RemoteView) that shows another computer's desktop and sends it
the mouse, the wheel and the keyboard."""

from __future__ import annotations

import threading

from PySide6.QtCore import Property, QPointF, QRectF, Qt, Signal, Slot
from PySide6.QtGui import QImage, QKeyEvent, QPainter
from PySide6.QtQuick import QQuickPaintedItem

from . import rdp

# Qt keys to Linux key codes, for when the platform gives no scan code (the X11 and Wayland platforms do: the xkb
# key code, which is the Linux one plus 8).
LETTERS = "qwertyuiop" + "asdfghjkl" + "zxcvbnm"
LETTER_CODES = list(range(16, 26)) + list(range(30, 39)) + list(range(44, 51))
FALLBACK = {getattr(Qt.Key, f"Key_{c.upper()}"): code for c, code in zip(LETTERS, LETTER_CODES)}
FALLBACK.update({getattr(Qt.Key, f"Key_{d}"): 2 + (d - 1) if d else 11 for d in range(10)})
FALLBACK.update({
    Qt.Key.Key_Return: 28, Qt.Key.Key_Enter: 96, Qt.Key.Key_Escape: 1, Qt.Key.Key_Backspace: 14, Qt.Key.Key_Tab: 15,
    Qt.Key.Key_Space: 57, Qt.Key.Key_Shift: 42, Qt.Key.Key_Control: 29, Qt.Key.Key_Alt: 56, Qt.Key.Key_Meta: 125,
    Qt.Key.Key_AltGr: 100, Qt.Key.Key_CapsLock: 58, Qt.Key.Key_Left: 105, Qt.Key.Key_Right: 106, Qt.Key.Key_Up: 103,
    Qt.Key.Key_Down: 108, Qt.Key.Key_Home: 102, Qt.Key.Key_End: 107, Qt.Key.Key_PageUp: 104, Qt.Key.Key_PageDown: 109,
    Qt.Key.Key_Delete: 111, Qt.Key.Key_Insert: 110, Qt.Key.Key_Minus: 12, Qt.Key.Key_Equal: 13,
    Qt.Key.Key_BracketLeft: 26, Qt.Key.Key_BracketRight: 27, Qt.Key.Key_Semicolon: 39, Qt.Key.Key_Apostrophe: 40,
    Qt.Key.Key_QuoteLeft: 41, Qt.Key.Key_Backslash: 43, Qt.Key.Key_Comma: 51, Qt.Key.Key_Period: 52,
    Qt.Key.Key_Slash: 53, Qt.Key.Key_Print: 99,
})
FALLBACK.update({getattr(Qt.Key, f"Key_F{n}"): 58 + n for n in range(1, 11)})
FALLBACK.update({Qt.Key.Key_F11: 87, Qt.Key.Key_F12: 88})
BUTTONS = {Qt.MouseButton.LeftButton: rdp.BTN_LEFT, Qt.MouseButton.RightButton: rdp.BTN_RIGHT,
           Qt.MouseButton.MiddleButton: rdp.BTN_MIDDLE}


def evdev_code(event: QKeyEvent) -> int:
    scan = event.nativeScanCode()
    if scan > 8:
        return scan - 8
    return FALLBACK.get(Qt.Key(event.key()), 0)


class RemoteView(QQuickPaintedItem):
    statusChanged = Signal()
    _frame = Signal()
    _state = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._status = ""
        self._title = ""
        self._image: QImage | None = None
        self._lock = threading.Lock()
        self._remote: rdp.Remote | None = None
        self._target = QRectF()
        self._held: set[int] = set()
        self.setAcceptedMouseButtons(Qt.MouseButton.AllButtons)
        self.setAcceptHoverEvents(True)
        self.setFlag(QQuickPaintedItem.Flag.ItemIsFocusScope, True)
        self.setActiveFocusOnTab(True)
        self.setFillColor(Qt.GlobalColor.black)
        self._frame.connect(self.update)
        self._state.connect(self._set_state)

    status = Property(str, lambda self: self._status, notify=statusChanged)
    title = Property(str, lambda self: self._title, notify=statusChanged)

    def _set_state(self, status: str, title: str) -> None:
        self._status = status
        if title:
            self._title = title
        self.statusChanged.emit()

    # ── connecting ──
    @Slot(str, str)
    def open(self, host: str, code: str) -> None:
        self.close()
        host, _, port = host.strip().rpartition(":") if host.count(":") == 1 else (host.strip(), "", "")
        host = host or "127.0.0.1"
        self._set_state("connecting", host)

        def run():
            remote = rdp.Remote(on_hello=self._on_hello, on_frame=self._on_frame,
                                on_close=lambda why: self._state.emit(f"closed: {why}", ""))
            try:
                remote.connect(host, int(port) if port.isdigit() else rdp.PORT, code)
            except (rdp.RemoteError, OSError) as error:
                self._state.emit(f"error: {error}", "")
                return
            self._remote = remote
        threading.Thread(target=run, daemon=True, name="remote-connect").start()

    @Slot()
    def close(self) -> None:
        remote, self._remote = self._remote, None
        if remote is not None:
            for code in list(self._held):
                remote.key(code, False)
            self._held.clear()
            remote.close()

    @Slot(int)
    def setQuality(self, quality: int) -> None:
        if self._remote:
            self._remote.settings(quality=quality)

    def _on_hello(self, info: dict) -> None:
        with self._lock:
            self._image = QImage(int(info["width"]) or 1, int(info["height"]) or 1, QImage.Format.Format_RGB32)
            self._image.fill(Qt.GlobalColor.black)
        control = "" if info.get("pointer") and info.get("keyboard") else " (view only: the desktop allows no input)"
        self._state.emit("connected" + control, f"{info.get('name', '')} — {info.get('output', '')}")

    def _on_frame(self, number: int, width: int, height: int, rects: list) -> None:
        with self._lock:
            if self._image is None or (self._image.width(), self._image.height()) != (width, height):
                self._image = QImage(width, height, QImage.Format.Format_RGB32)
            p = QPainter(self._image)
            for x, y, _w, _h, jpeg in rects:
                p.drawImage(x, y, QImage.fromData(jpeg, "JPG"))
            p.end()
        self._frame.emit()

    # ── drawing ──
    def paint(self, painter: QPainter) -> None:
        with self._lock:
            img = self._image
            if img is None:
                return
            scale = min(self.width() / img.width(), self.height() / img.height())
            w, h = img.width() * scale, img.height() * scale
            self._target = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, scale < 1)
            painter.drawImage(self._target, img)

    def _remote_point(self, pos: QPointF) -> tuple[int, int] | None:
        img, t = self._image, self._target
        if img is None or t.width() <= 0:
            return None
        x = (pos.x() - t.x()) * img.width() / t.width()
        y = (pos.y() - t.y()) * img.height() / t.height()
        return int(min(max(x, 0), img.width() - 1)), int(min(max(y, 0), img.height() - 1))

    # ── input ──
    def _move(self, pos: QPointF) -> None:
        point = self._remote_point(pos)
        if self._remote and point:
            self._remote.pointer(*point)

    def hoverMoveEvent(self, event) -> None:
        self._move(event.position())

    def mouseMoveEvent(self, event) -> None:
        self._move(event.position())

    def mousePressEvent(self, event) -> None:
        self.forceActiveFocus()
        self._move(event.position())
        if self._remote and event.button() in BUTTONS:
            self._remote.button(BUTTONS[event.button()], True)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._remote and event.button() in BUTTONS:
            self._remote.button(BUTTONS[event.button()], False)

    def wheelEvent(self, event) -> None:
        steps_v = -round(event.angleDelta().y() / 120)
        steps_h = round(event.angleDelta().x() / 120)
        if self._remote and (steps_v or steps_h):
            self._remote.scroll(steps_v, steps_h)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        code = evdev_code(event)
        if self._remote and code:
            self._held.add(code)
            self._remote.key(code, True)
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            return
        code = evdev_code(event)
        if self._remote and code:
            self._held.discard(code)
            self._remote.key(code, False)
        event.accept()

    def focusOutEvent(self, event) -> None:
        # Nothing stays held down on the other computer when this window loses the keyboard.
        if self._remote:
            for code in list(self._held):
                self._remote.key(code, False)
        self._held.clear()
