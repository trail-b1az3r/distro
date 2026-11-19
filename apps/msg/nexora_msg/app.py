"""The window: PySide6 and QML (Qt 6). The Bridge is what QML sees as `msg`."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtQuickControls2 import QQuickStyle

from . import APP_ID, __version__
from .service import Service

QML = Path(__file__).resolve().parent / "qml"


def halcyon_colors() -> dict:
    """The desktop's colours (Halcyon's theme or wallpaper), when there are some."""
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    try:
        roles = json.loads((state / "quickshell/user/generated/colors.json").read_text())
    except (OSError, ValueError):
        return {}
    keys = ("primary", "on_primary", "primary_container", "on_primary_container", "surface", "on_surface",
            "surface_container", "surface_container_high", "on_surface_variant", "outline_variant", "error")
    return {k: roles[k] for k in keys if isinstance(roles.get(k), str)}


class Bridge(QObject):
    changed = Signal()
    chatsChanged = Signal()
    messagesChanged = Signal()
    searchChanged = Signal()
    contactsChanged = Signal()
    devicesChanged = Signal()
    remotesChanged = Signal()
    toast = Signal(str)
    # From the service's threads to the UI's.
    _event = Signal(str, "QVariant")

    def __init__(self, service: Service):
        super().__init__()
        self.svc = service
        self._chats: list = []
        self._messages: list = []
        self._results: dict = {"messages": [], "contacts": [], "chats": []}
        self._contacts: list = []
        self._devices: list = []
        self._remotes: list = []
        self._finding = False
        self._chat = 0
        self._chat_info: dict = {}
        self._busy: dict[str, bool] = {}
        self._progress = -1
        self._status = ""
        self._bt = ""
        self._companion = ""
        self._code = ""
        self._event.connect(self._on_event)
        service.listen(lambda kind, data: self._event.emit(kind, data))
        self.refresh()

    # ── properties ──
    chats = Property("QVariantList", lambda self: self._chats, notify=chatsChanged)
    messages = Property("QVariantList", lambda self: self._messages, notify=messagesChanged)
    results = Property("QVariantMap", lambda self: self._results, notify=searchChanged)
    contacts = Property("QVariantList", lambda self: self._contacts, notify=contactsChanged)
    devices = Property("QVariantList", lambda self: self._devices, notify=devicesChanged)
    remotes = Property("QVariantList", lambda self: self._remotes, notify=remotesChanged)
    findingRemotes = Property(bool, lambda self: self._finding, notify=remotesChanged)
    currentChat = Property(int, lambda self: self._chat, notify=messagesChanged)
    chatInfo = Property("QVariantMap", lambda self: self._chat_info, notify=messagesChanged)
    busy = Property(bool, lambda self: any(self._busy.values()), notify=changed)
    progress = Property(int, lambda self: self._progress, notify=changed)
    status = Property(str, lambda self: self._status, notify=changed)
    bluetoothState = Property(str, lambda self: self._bt, notify=changed)
    companionState = Property(str, lambda self: self._companion, notify=changed)
    pairingCode = Property(str, lambda self: self._code, notify=changed)
    version = Property(str, lambda self: __version__, constant=True)
    colors = Property("QVariantMap", lambda self: halcyon_colors(), constant=True)

    def _set_status(self, text: str) -> None:
        self._status = text
        self.changed.emit()

    # ── service events ──
    def _on_event(self, kind: str, data: dict) -> None:
        if kind == "busy":
            self._busy[data["what"]] = data["busy"]
            if not data["busy"]:
                self._progress = -1
            self.changed.emit()
        elif kind == "progress":
            self._progress = data.get("percent", -1)
            self._set_status(data.get("text", ""))
        elif kind == "error":
            self._set_status(data["message"])
            self.toast.emit(data["message"])
        elif kind == "synced":
            added = data.get("added", 0)
            extra = f", {data['contacts']} contacts" if data.get("contacts") else ""
            self._set_status(f"Synced over {data['source']}: {added} new messages{extra}")
            self.refresh()
        elif kind in ("message", "sent"):
            self.refresh()
            if kind == "sent" and data.get("status") == "cancelled":
                self.toast.emit("Not sent: it was cancelled on the iPhone")
        elif kind == "contacts":
            self._set_status(f"{data['count']} contacts synced")
            self.refresh()
        elif kind == "bluetooth":
            parts = []
            if data.get("messages"):
                parts.append("messages")
            if data.get("contacts"):
                parts.append("contacts")
            self._bt = "Connected: " + " and ".join(parts) if parts else "Not connected"
            for key in ("messages_error", "contacts_error"):
                if data.get(key):
                    self.toast.emit(data[key])
            self.changed.emit()
        elif kind == "devices":
            self._devices = data["list"]
            self.devicesChanged.emit()
            if not self._devices:
                self.toast.emit("No paired iPhone: pair it in Bluetooth settings first")
        elif kind == "remotes":
            self._remotes = data["list"]
            self._finding = False
            self.remotesChanged.emit()
        elif kind == "companion":
            self._companion = data["state"]
            self._code = data.get("code", self._code)
            if data["state"] == "closed":
                self._code = ""
            self.changed.emit()

    # ── what QML calls ──
    @Slot()
    def refresh(self) -> None:
        try:
            self._chats = self.svc.chats()
            self._contacts = self.svc.contacts()
        except Exception as error:  # noqa: BLE001
            self._set_status(str(error))
            return
        self.chatsChanged.emit()
        self.contactsChanged.emit()
        if self._chat:
            self._load(self._chat)

    def _load(self, chat: int, before: int = 0) -> None:
        older = self.svc.messages(chat, before)
        self._messages = older + self._messages if before else older
        self._chat_info = next((c for c in self._chats if c["id"] == chat), {})
        self.messagesChanged.emit()

    @Slot(int)
    def openChat(self, chat: int) -> None:
        self._chat = chat
        self._messages = []
        self._load(chat)
        self.svc.mark_read(chat)
        for c in self._chats:
            if c["id"] == chat:
                c["unread"] = 0
        self.chatsChanged.emit()

    @Slot()
    def loadOlder(self) -> None:
        if self._chat and self._messages:
            self._load(self._chat, self._messages[0]["date_ms"])

    @Slot(str)
    def search(self, text: str) -> None:
        self._results = self.svc.search(text) if text.strip() else {"messages": [], "contacts": [], "chats": []}
        self.searchChanged.emit()

    @Slot(str)
    def newChat(self, handle: str) -> None:
        chat = self.svc.core.call("chat-for", handle=handle)
        self._chats = self.svc.chats()
        if not any(c["id"] == chat for c in self._chats):
            self._chats.insert(0, {"id": chat, "title": handle, "handles": [handle], "last_text": "", "unread": 0,
                                   "last_ms": 0, "photo": "", "group": False})
        self.chatsChanged.emit()
        self.openChat(chat)

    @Slot(str, str)
    def send(self, text: str, image: str) -> None:
        handles = self._chat_info.get("handles") or []
        if not handles:
            self.toast.emit("This conversation has nobody to send to")
            return
        image = QUrl(image).toLocalFile() if image.startswith("file:") else image
        self.svc.send(handles, text, image)

    @Slot()
    def syncCable(self) -> None:
        self.svc.sync_backup()

    @Slot()
    def scanBluetooth(self) -> None:
        self.svc.bluetooth_devices(lambda devices: self._event.emit("devices", {"list": devices}))

    @Slot(str)
    def connectBluetooth(self, address: str) -> None:
        self._bt = "Connecting…"
        self.changed.emit()
        self.svc.connect_bluetooth(address)

    @Slot(str)
    def connectCompanion(self, host: str) -> None:
        host, _, port = host.strip().partition(":")
        self._companion = "connecting"
        self.changed.emit()
        self.svc.connect_companion(host, int(port) if port.isdigit() else 0)

    @Slot()
    def findRemotes(self) -> None:
        """Computers on the tailnet sharing their desktop (rdp-express)."""
        import threading

        from . import rdp
        self._finding = True
        self.remotesChanged.emit()

        def run():
            try:
                found = rdp.discover()
            except Exception:  # noqa: BLE001 - Tailscale is optional
                found = []
            self._event.emit("remotes", {"list": found})
        threading.Thread(target=run, daemon=True, name="find-remotes").start()

    @Slot()
    def syncContacts(self) -> None:
        self.svc.sync_contacts()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    QQuickStyle.setStyle("Material")
    app = QGuiApplication(argv)
    app.setApplicationName("Messages")
    app.setDesktopFileName(APP_ID)
    app.setOrganizationName("Nexora")
    app.setWindowIcon(QIcon.fromTheme(APP_ID))
    from .rdpview import RemoteView
    qmlRegisterType(RemoteView, "Nexora.Remote", 1, 0, "RemoteView")
    service = Service()
    bridge = Bridge(service)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("msg", bridge)
    engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
    if not engine.rootObjects():
        return 1
    code = app.exec()
    service.close()
    return code
