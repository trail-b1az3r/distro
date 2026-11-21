"""usbmuxd: a TCP connection to a port on an iPhone over its USB cable (or over Wi-Fi once paired), which is how the
desktop reaches the companion app without any network."""

from __future__ import annotations

import os
import plistlib
import socket
import struct

SOCKET = os.environ.get("USBMUXD_SOCKET_ADDRESS", "/var/run/usbmuxd")


class UsbmuxError(OSError):
    pass


def _connect() -> socket.socket:
    if SOCKET.startswith("UNIX:"):
        path = SOCKET[5:]
    elif ":" in SOCKET and not SOCKET.startswith("/"):
        host, port = SOCKET.rsplit(":", 1)
        return socket.create_connection((host, int(port)), timeout=5)
    else:
        path = SOCKET
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect(path)
    except OSError as error:
        s.close()
        raise UsbmuxError(f"usbmuxd is not running ({error}): install usbmuxd and plug the iPhone in") from None
    return s


def _exchange(s: socket.socket, message: dict, tag: int = 1) -> dict:
    payload = plistlib.dumps({"ClientVersionString": "frontline-msg", "ProgName": "frontline-msg", **message})
    s.sendall(struct.pack("<IIII", 16 + len(payload), 1, 8, tag) + payload)
    header = _read(s, 16)
    length, _version, _kind, _tag = struct.unpack("<IIII", header)
    return plistlib.loads(_read(s, length - 16))


def _read(s: socket.socket, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = s.recv(n - len(data))
        if not chunk:
            raise UsbmuxError("usbmuxd closed the connection")
        data += chunk
    return data


def devices() -> list[dict]:
    with _connect() as s:
        reply = _exchange(s, {"MessageType": "ListDevices"})
    out = []
    for d in reply.get("DeviceList", []):
        props = d.get("Properties", {})
        out.append({"id": d.get("DeviceID"), "udid": props.get("SerialNumber", ""),
                    "link": "usb" if props.get("ConnectionType") == "USB" else "wifi"})
    return out


def connect(device_id: int, port: int) -> socket.socket:
    """A socket to the phone's port; usbmuxd hands it over once it answers Result 0."""
    s = _connect()
    reply = _exchange(s, {"MessageType": "Connect", "DeviceID": device_id, "PortNumber": socket.htons(port)})
    if reply.get("Number", 1) != 0:
        s.close()
        raise UsbmuxError("the companion app is not running on the iPhone (or not listening)")
    s.settimeout(None)
    return s
