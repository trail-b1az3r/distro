"""The iPhone over Bluetooth, through BlueZ: messages over MAP (Message Access Profile) and contacts over PBAP
(Phone Book Access Profile), both carried by obexd.

On the iPhone: pair it with this computer once (Settings > Bluetooth), then tap (i) next to the computer and turn on
"Show Notifications" (that is MAP: new messages, and replying) and "Sync Contacts" (PBAP). iOS gives MAP the
messages that arrive while connected and its recent ones, not the whole history: the full history, with pictures,
comes over the cable (backup.py).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from . import bmessage, vcard

MAP_MSE = "00001132-0000-1000-8000-00805f9b34fb"
PBAP_PSE = "0000112f-0000-1000-8000-00805f9b34fb"
OBEX = "org.bluez.obex"


class BluetoothError(RuntimeError):
    pass


def _value(v):
    return v.value if hasattr(v, "value") else v


def message_from_listing(props: dict, folder: str) -> dict:
    """A MAP message listing entry as a store message (the subject holds the text, or its start)."""
    p = {k: _value(v) for k, v in props.items()}
    sent = folder in ("sent", "outbox")
    handle = (p.get("RecipientAddress") if sent else p.get("SenderAddress")) or p.get("Sender") or ""
    return {"handle": handle, "from_me": sent, "date_ms": bmessage.timestamp_ms(p.get("Timestamp", "")),
            "text": p.get("Subject", ""), "service": "SMS" if str(p.get("Type", "")).startswith("sms") else "iMessage",
            "source": "map", "status": "sent" if p.get("Sent") else ""}


class PhoneLink:
    """One phone's MAP and PBAP sessions. Every method is a coroutine: run them on one asyncio loop."""

    def __init__(self, on_message: Callable[[dict], None] | None = None):
        self.on_message = on_message or (lambda m: None)
        self.system = None
        self.session = None
        self.map_path = ""
        self.pbap_path = ""
        self.address = ""
        self.workdir = Path(tempfile.mkdtemp(prefix="frontline-msg-obex-"))

    async def _buses(self):
        if self.system is None:
            try:
                from dbus_next.aio import MessageBus
                from dbus_next.constants import BusType
            except ImportError:
                raise BluetoothError("python-dbus-next is not installed") from None
            try:
                self.system = await MessageBus(bus_type=BusType.SYSTEM).connect()
                self.session = await MessageBus(bus_type=BusType.SESSION).connect()
            except (OSError, ValueError) as error:
                self.system = None
                raise BluetoothError(f"Bluetooth is not available: no D-Bus ({error.__class__.__name__}). "
                                     "Is bluetooth.service running?") from None

    async def _iface(self, bus, name: str, path: str, interface: str):
        intro = await bus.introspect(name, path)
        return bus.get_proxy_object(name, path, intro).get_interface(interface)

    async def devices(self) -> list[dict]:
        """Paired devices that offer messages or contacts (an iPhone offers both)."""
        await self._buses()
        manager = await self._iface(self.system, "org.bluez", "/", "org.freedesktop.DBus.ObjectManager")
        out = []
        for path, interfaces in (await manager.call_get_managed_objects()).items():
            dev = interfaces.get("org.bluez.Device1")
            if not dev:
                continue
            uuids = [u.lower() for u in _value(dev.get("UUIDs", [])) or []]
            if not _value(dev.get("Paired", False)):
                continue
            out.append({"path": path, "address": _value(dev["Address"]), "name": _value(dev.get("Alias") or dev.get("Name") or ""),
                        "connected": bool(_value(dev.get("Connected", False))),
                        "messages": MAP_MSE in uuids, "contacts": PBAP_PSE in uuids,
                        "icon": _value(dev.get("Icon", ""))})
        return [d for d in out if d["messages"] or d["contacts"]]

    async def connect(self, address: str) -> dict:
        await self._buses()
        client = await self._iface(self.session, OBEX, "/org/bluez/obex", "org.bluez.obex.Client1")
        from dbus_next import Variant
        self.address = address
        result = {"messages": False, "contacts": False}
        try:
            self.map_path = await client.call_create_session(address, {"Target": Variant("s", "map")})
            result["messages"] = True
        except Exception as error:  # noqa: BLE001 - dbus errors say what went wrong
            result["messages_error"] = self._explain(error, "Show Notifications")
        try:
            self.pbap_path = await client.call_create_session(address, {"Target": Variant("s", "PBAP")})
            result["contacts"] = True
        except Exception as error:  # noqa: BLE001
            result["contacts_error"] = self._explain(error, "Sync Contacts")
        if self.map_path:
            await self._watch_new_messages()
        return result

    @staticmethod
    def _explain(error: Exception, switch: str) -> str:
        text = str(error)
        if "Forbidden" in text or "refused" in text.lower() or "Not Authorized" in text:
            return f"the iPhone refused: turn on \"{switch}\" for this computer in its Bluetooth settings"
        if "ServiceUnknown" in text or "org.bluez.obex" in text and "not provided" in text:
            return "obexd is not running (install bluez-obex, or bluez-utils, and log in again)"
        return text

    async def disconnect(self) -> None:
        if not self.session:
            return
        client = await self._iface(self.session, OBEX, "/org/bluez/obex", "org.bluez.obex.Client1")
        for path in (self.map_path, self.pbap_path):
            if path:
                try:
                    await client.call_remove_session(path)
                except Exception:  # noqa: BLE001
                    pass
        self.map_path = self.pbap_path = ""

    async def _wait_transfer(self, path: str, timeout: float = 60) -> str:
        props = await self._iface(self.session, OBEX, path, "org.freedesktop.DBus.Properties")
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        filename = ""
        while loop.time() < end:
            try:
                values = await props.call_get_all("org.bluez.obex.Transfer1")
            except Exception:  # noqa: BLE001 - the transfer object goes away once it is complete
                return filename
            filename = _value(values.get("Filename", "")) or filename
            status = _value(values.get("Status", ""))
            if status == "complete":
                return filename
            if status == "error":
                raise BluetoothError("the transfer failed")
            await asyncio.sleep(0.2)
        raise BluetoothError("the transfer timed out")

    async def _map(self):
        if not self.map_path:
            raise BluetoothError("messages are not connected")
        return await self._iface(self.session, OBEX, self.map_path, "org.bluez.obex.MessageAccess1")

    async def full_text(self, message_path: str) -> str:
        message = await self._iface(self.session, OBEX, message_path, "org.bluez.obex.Message1")
        target = str(self.workdir / (message_path.rsplit("/", 1)[-1] + ".bmsg"))
        transfer, _ = await message.call_get(target, False)
        await self._wait_transfer(transfer)
        try:
            return bmessage.parse(Path(target).read_text(errors="replace")).text
        finally:
            Path(target).unlink(missing_ok=True)

    async def messages(self, limit: int = 200) -> list[dict]:
        """The recent messages the phone gives over MAP, received and sent."""
        from dbus_next import Variant
        access = await self._map()
        await access.call_set_folder("/")
        await access.call_set_folder("telecom/msg")
        out = []
        for folder in ("inbox", "sent"):
            try:
                listing = await access.call_list_messages(folder, {"MaxCount": Variant("q", limit)})
            except Exception:  # noqa: BLE001 - iOS has no "sent" over MAP on some versions
                continue
            for path, props in listing.items():
                msg = message_from_listing(props, folder)
                size = int(_value(props.get("Size", 0)) or 0)
                if size > len(msg["text"].encode()) + 8:
                    try:
                        msg["text"] = await self.full_text(path) or msg["text"]
                    except (BluetoothError, Exception):  # noqa: BLE001 - keep the subject then
                        pass
                out.append(msg)
        return out

    async def _watch_new_messages(self) -> None:
        """obexd turns the phone's new-message events (MNS) into new Message1 objects in the session."""
        manager = await self._iface(self.session, OBEX, "/", "org.freedesktop.DBus.ObjectManager")

        def added(path, interfaces):
            if path.startswith(self.map_path) and "org.bluez.obex.Message1" in interfaces:
                props = interfaces["org.bluez.obex.Message1"]
                folder = str(_value(props.get("Folder", "inbox"))).rsplit("/", 1)[-1].lower() or "inbox"
                msg = message_from_listing(props, folder)

                async def finish():
                    try:
                        msg["text"] = await self.full_text(path) or msg["text"]
                    except Exception:  # noqa: BLE001
                        pass
                    self.on_message(msg)
                asyncio.ensure_future(finish())

        manager.on_interfaces_added(added)

    async def send(self, to: str, text: str) -> None:
        """Sends a text through the phone. iOS takes this only with "Show Notifications" on; pictures go through
        the companion app."""
        access = await self._map()
        source = self.workdir / "out.bmsg"
        source.write_text(bmessage.build(to, text), encoding="utf-8")
        from dbus_next import Variant
        await access.call_set_folder("/")
        await access.call_set_folder("telecom/msg")
        transfer, _ = await access.call_push_message(str(source), "outbox",
                                                    {"Charset": Variant("s", "utf8"), "Retry": Variant("b", True)})
        try:
            await self._wait_transfer(transfer)
        finally:
            source.unlink(missing_ok=True)

    async def contacts(self) -> list[vcard.Card]:
        if not self.pbap_path:
            raise BluetoothError("contacts are not connected")
        from dbus_next import Variant
        book = await self._iface(self.session, OBEX, self.pbap_path, "org.bluez.obex.PhonebookAccess1")
        await book.call_select("int", "pb")
        target = str(self.workdir / "pb.vcf")
        fields = ["FN", "N", "TEL", "EMAIL", "ORG", "PHOTO", "UID"]
        transfer, _ = await book.call_pull_all(target, {"Format": Variant("s", "vcard30"),
                                                        "Fields": Variant("as", fields)})
        await self._wait_transfer(transfer, timeout=180)
        try:
            return vcard.parse(Path(target).read_text(errors="replace"))
        finally:
            Path(target).unlink(missing_ok=True)

    def cleanup(self) -> None:
        for f in self.workdir.glob("*"):
            f.unlink(missing_ok=True)
        try:
            os.rmdir(self.workdir)
        except OSError:
            pass
