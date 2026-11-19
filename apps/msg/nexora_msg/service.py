"""What the app does, without the UI: the store, the phone's links, syncing and sending. The UI (app.py) and the
command line (cli.py) both drive this."""

from __future__ import annotations

import asyncio
import base64
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import paths, wired
from .core import Core

Listener = Callable[[str, dict], None]


class Service:
    def __init__(self, store: Path | None = None, core: Core | None = None):
        self.core = core or Core(store or paths.store_path())
        self.listeners: list[Listener] = []
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self.loop.run_forever, daemon=True, name="bluetooth")
        self.loop_thread.start()
        self.phone = None              # bluetooth.PhoneLink
        self.companion = None          # companion.Companion

    # ── events to the UI ──
    def listen(self, listener: Listener) -> None:
        self.listeners.append(listener)

    def emit(self, kind: str, **data) -> None:
        for listener in list(self.listeners):
            listener(kind, data)

    def run_async(self, coro, done: Callable | None = None, kind: str = "") -> None:
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)

        def finished(f):
            try:
                result = f.result()
            except Exception as error:  # noqa: BLE001 - shown to the user
                self.emit("error", where=kind, message=str(error))
                return
            if done:
                done(result)
        future.add_done_callback(finished)

    def background(self, fn: Callable, kind: str) -> None:
        def run():
            try:
                fn()
            except Exception as error:  # noqa: BLE001
                self.emit("error", where=kind, message=str(error))
            finally:
                self.emit("busy", what=kind, busy=False)
        self.emit("busy", what=kind, busy=True)
        threading.Thread(target=run, daemon=True, name=kind).start()

    # ── the store ──
    def chats(self) -> list[dict]:
        return self.core.call("chats", limit=500)

    def messages(self, chat: int, before: int = 0, limit: int = 80) -> list[dict]:
        return self.core.call("messages", chat=chat, before=before, limit=limit)

    def search(self, query: str) -> dict:
        return self.core.call("search", query=query, limit=60)

    def contacts(self) -> list[dict]:
        return self.core.call("contacts")

    def mark_read(self, chat: int) -> None:
        self.core.call("mark-read", chat=chat)

    def add_messages(self, messages: list[dict]) -> int:
        return self.core.call("add-messages", messages=messages)["added"] if messages else 0

    # ── the cable ──
    def sync_backup(self, udid: str = "", link: str = "usb") -> None:
        def run():
            if not udid:
                found = wired.devices()
                if not found:
                    raise wired.WiredError("No iPhone found: plug it in with its cable and unlock it.")
                device = found[0]
            else:
                device = {"udid": udid, "link": link}
            folder = wired.backup(device["udid"], device.get("link", "usb"),
                                  lambda pct, text: self.emit("progress", what="backup", percent=pct, text=text))
            self.emit("progress", what="backup", percent=-1, text="Reading messages")
            result = self.core.call("import-backup", backup=str(folder))
            self.emit("synced", source="cable", **result)
        self.background(run, "backup")

    def import_backup(self, folder: str) -> dict:
        result = self.core.call("import-backup", backup=folder)
        self.emit("synced", source="backup", **result)
        return result

    # ── Bluetooth ──
    def bluetooth_devices(self, done: Callable[[list], None]) -> None:
        from .bluetooth import PhoneLink
        if self.phone is None:
            self.phone = PhoneLink(on_message=self._incoming)
        self.run_async(self.phone.devices(), done, "bluetooth")

    def connect_bluetooth(self, address: str) -> None:
        from .bluetooth import PhoneLink
        if self.phone is None:
            self.phone = PhoneLink(on_message=self._incoming)

        async def go():
            result = await self.phone.connect(address)
            self.emit("bluetooth", state="connected", address=address, **result)
            if result.get("messages"):
                added = self.add_messages(await self.phone.messages())
                self.emit("synced", source="bluetooth", added=added)
            if result.get("contacts"):
                await self._pull_contacts_bt()
        self.run_async(go(), kind="bluetooth")

    async def _pull_contacts_bt(self) -> None:
        cards = await self.phone.contacts()
        photos = paths.data_dir() / "photos"
        photos.mkdir(exist_ok=True)
        contacts = []
        for i, card in enumerate(cards):
            key = f"bt:{card.uid or card.name + ':' + ','.join(card.handles[:1])}"
            photo = ""
            if card.photo:
                path = photos / f"bt-{abs(hash(key)) % 10**12}.jpg"
                path.write_bytes(card.photo)
                photo = str(path)
            contacts.append({"key": key, "name": card.name, "org": card.org, "photo": photo, "handles": card.handles,
                             "source": "bluetooth"})
        if contacts:
            self.core.call("add-contacts", contacts=contacts)
        self.emit("contacts", source="bluetooth", count=len(contacts))

    def _incoming(self, message: dict) -> None:
        if self.add_messages([message]):
            self.emit("message", **message)
            notify(message)

    # ── the companion app ──
    def connect_companion(self, host: str = "", port: int = 0) -> None:
        from .companion import PORT, Companion

        def run():
            c = Companion(on_event=lambda e: self.emit("companion-event", **e),
                          on_close=lambda reason: self.emit("companion", state="closed", reason=reason))
            if host:
                c.connect_tcp(host, port or PORT)
            else:
                try:
                    c.connect_usb()
                except Exception as usb_error:  # noqa: BLE001 - no cable: the same Wi-Fi, or Tailscale
                    from .companion import discover
                    found = discover()
                    if not found:
                        raise RuntimeError(f"No iPhone on the cable ({usb_error}), on this Wi-Fi or on Tailscale: "
                                           "open Nexora Messages on the iPhone.") from None
                    c.connect_tcp(found[0]["host"], found[0]["port"])
            self.companion = c
            self.emit("companion", state="connected" if c.paired else "pairing", code=c.code, phone=c.phone)
            if not c.paired and not c.wait_paired():
                raise RuntimeError("the pairing code was not confirmed on the iPhone")
            self.emit("companion", state="connected", code=c.code, phone=c.phone)
            self._companion_contacts()
        self.background(run, "companion")

    def _companion_contacts(self) -> None:
        people = self.companion.contacts()
        photos = paths.data_dir() / "photos"
        photos.mkdir(exist_ok=True)
        contacts = []
        for p in people:
            photo = ""
            if p.get("photo"):
                path = photos / f"ios-{p['id'].replace('/', '_').replace(':', '_')[:60]}.jpg"
                path.write_bytes(base64.b64decode(p["photo"]))
                photo = str(path)
            contacts.append({"key": f"ios:{p['id']}", "name": p.get("name", ""), "org": p.get("org", ""),
                             "photo": photo, "handles": list(p.get("phones", [])) + list(p.get("emails", [])),
                             "source": "companion"})
        if contacts:
            self.core.call("add-contacts", contacts=contacts)
        self.emit("contacts", source="companion", count=len(contacts))

    def sync_contacts(self) -> None:
        if self.companion is not None and self.companion.paired:
            self.background(self._companion_contacts, "contacts")
        elif self.phone is not None and self.phone.pbap_path:
            self.run_async(self._pull_contacts_bt(), kind="contacts")
        else:
            self.emit("error", where="contacts", message="Connect the iPhone first (Bluetooth or the companion app).")

    # ── sending ──
    def send(self, handles: list[str], text: str, image: str = "") -> None:
        """A text goes over Bluetooth when it is connected; a picture (or a text when Bluetooth is not) through the
        companion app, which opens it in Messages on the phone for one tap."""
        def run():
            now = int(time.time() * 1000)
            via = ""
            if not image and self.phone is not None and self.phone.map_path and len(handles) == 1:
                fut = asyncio.run_coroutine_threadsafe(self.phone.send(handles[0], text), self.loop)
                fut.result(timeout=90)
                via = "bluetooth"
            elif self.companion is not None and self.companion.paired:
                result = self.companion.send(handles, text, Path(image) if image else None)
                via = "companion:" + str(result.get("result", "sent"))
            else:
                raise RuntimeError("Not connected: turn on Bluetooth messages, or open the companion app on the "
                                   "iPhone (pictures need the companion app).")
            attachments = []
            if image:
                kept = paths.data_dir() / "attachments" / "sent" / f"{now}-{Path(image).name}"
                kept.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(image, kept)
                attachments.append({"path": str(kept), "mime": "", "name": Path(image).name})
            status = "cancelled" if via.endswith("cancelled") else "sent"
            if status == "sent":
                message = {"handle": handles[0] if len(handles) == 1 else "", "chat_handles": handles,
                           "chat_key": "" if len(handles) == 1 else "g:local:" + ",".join(sorted(handles)),
                           "from_me": True, "date_ms": now, "text": text, "source": "local",
                           "attachments": attachments, "status": "sent"}
                self.add_messages([message])
            self.emit("sent", via=via, status=status)
        self.background(run, "send")

    def close(self) -> None:
        if self.companion is not None:
            self.companion.close()
        if self.phone is not None:
            fut = asyncio.run_coroutine_threadsafe(self.phone.disconnect(), self.loop)
            try:
                fut.result(timeout=3)
            except Exception:  # noqa: BLE001
                pass
            self.phone.cleanup()
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.core.close()


def notify(message: dict) -> None:
    if shutil.which("notify-send") and not message.get("from_me"):
        subprocess.Popen(["notify-send", "-a", "Messages", "-i", "nexora-msg", message.get("handle", "Message"),
                          message.get("text", "")[:200]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
