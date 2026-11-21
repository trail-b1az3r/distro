"""The remote desktop viewer's protocol (against a stand-in for rdp-express) and Tailscale discovery."""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frontline_msg import rdp, tailscale  # noqa: E402


def test_keys_match_the_rust_server():
    # apps/rdp-express/src/link.rs checks the same values.
    assert rdp.derive(b"shared", "12345678", b"c", b"s").hex() == \
        "17d548fba1169b2bad12ddd1f3733f39b64d63ac19ff4c93a127a7e04ab02c65"
    assert rdp.derive(b"shared", None, b"c", b"s").hex() == \
        "2f2fd7dd402a5d18c0749184a8c3763cc0afee8d39631efbcdecbb80661f7e68"


class FakeServer(threading.Thread):
    """rdp-express's side of the protocol: hello, the pairing code, one frame, then it records the input."""

    def __init__(self, code: str = "", known: set | None = None):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.port = self.srv.getsockname()[1]
        self.code, self.known = code, known if known is not None else set()
        self.key = rdp.X25519PrivateKey.generate()
        self.inputs: list[bytes] = []
        self.sessions = 0

    def run(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            self.serve(conn)

    def serve(self, conn):
        hello = json.loads(rdp.read_frame(conn))
        known = hello["pub"] in self.known
        if not known and not self.code:
            rdp.write_frame(conn, json.dumps({"hello": "rdp-express-server", "error": "pair first"}).encode())
            conn.close()
            return
        mine = os.urandom(16)
        pub = self.key.public_key().public_bytes(rdp.serialization.Encoding.Raw, rdp.serialization.PublicFormat.Raw)
        rdp.write_frame(conn, json.dumps({"hello": "rdp-express-server", "v": 1, "known": known, "name": "desk",
                                          "pub": base64.b64encode(pub).decode(),
                                          "nonce": base64.b64encode(mine).decode()}).encode())
        shared = self.key.exchange(rdp.X25519PublicKey.from_public_bytes(base64.b64decode(hello["pub"])))
        key = rdp.derive(shared, None if known else self.code, base64.b64decode(hello["nonce"]), mine)
        inbound, out = rdp.Sealer(key, b"C2S\0"), rdp.Sealer(key, b"S2C\0")
        try:
            first = inbound.open(rdp.read_frame(conn))
        except rdp.RemoteError:
            conn.close()
            return
        assert first[:1] == b"\x10"
        self.known.add(hello["pub"])
        self.sessions += 1
        rdp.write_frame(conn, out.seal(b"\x01" + json.dumps({"name": "desk", "output": "DP-1", "width": 64,
                                                             "height": 32, "pointer": True,
                                                             "keyboard": True}).encode()))
        jpeg = bytes.fromhex("ffd8ffe000104a46494600")  # only the bytes are checked
        frame = b"\x02" + struct.pack(">IHHH", 1, 64, 32, 1) + struct.pack(">HHHHI", 0, 0, 64, 32, len(jpeg)) + jpeg
        rdp.write_frame(conn, out.seal(frame))
        conn.settimeout(3)
        try:
            while True:
                self.inputs.append(inbound.open(rdp.read_frame(conn)))
        except (rdp.RemoteError, OSError):
            conn.close()


def test_pairs_with_the_code_then_knows_the_viewer(tmp_path):
    server = FakeServer(code="12345678")
    server.start()
    key = rdp.identity(tmp_path / "id.key")
    with pytest.raises(rdp.RemoteError, match="pairing code was wrong"):
        rdp.Remote(key=key).connect("127.0.0.1", server.port, code="0000 0000")
    frames, done = [], threading.Event()
    r = rdp.Remote(key=key, on_frame=lambda *a: (frames.append(a), done.set()))
    r.connect("127.0.0.1", server.port, code="1234 5678")
    assert r.info["output"] == "DP-1" and r.server == "desk"
    assert done.wait(3) and frames[0][:3] == (1, 64, 32) and frames[0][3][0][:4] == (0, 0, 64, 32)
    r.pointer(10, 20)
    r.button(rdp.BTN_LEFT, True)
    r.scroll(-1)
    r.key(30, True)
    import time
    time.sleep(0.3)
    r.close()
    time.sleep(0.2)
    got = server.inputs
    assert got[0] == b"\x15" + struct.pack(">I", 1), "the frame is acknowledged"
    assert struct.pack(">BHH", 0x11, 10, 20) in got and struct.pack(">BIB", 0x12, 0x110, 1) in got
    assert struct.pack(">Bhh", 0x13, -1, 0) in got and struct.pack(">BIB", 0x14, 30, 1) in got
    # Next time, no code: the server knows this viewer's key.
    r2 = rdp.Remote(key=key)
    r2.connect("127.0.0.1", server.port)
    assert server.sessions == 2
    r2.close()


def test_unknown_viewer_without_a_code_is_told_how_to_pair(tmp_path):
    server = FakeServer(code="")
    server.start()
    with pytest.raises(rdp.RemoteError, match="pair first"):
        rdp.Remote(key=rdp.identity(tmp_path / "id.key")).connect("127.0.0.1", server.port)


STATUS = {"Peer": {
    "a": {"HostName": "Anns-iPhone", "DNSName": "anns-iphone.tail1.ts.net.", "OS": "iOS", "Online": True,
          "TailscaleIPs": ["100.64.0.5", "fd7a:115c:a1e0::5"]},
    "b": {"HostName": "desk", "DNSName": "desk.tail1.ts.net.", "OS": "linux", "Online": True,
          "TailscaleIPs": ["100.64.0.7"]},
    "c": {"HostName": "old-laptop", "OS": "linux", "Online": False, "TailscaleIPs": ["100.64.0.9"]},
}}


def test_tailscale_peers_and_who_answers(monkeypatch):
    peers = tailscale.peers(STATUS)
    assert [p["name"] for p in peers] == ["Anns-iPhone", "desk"], "offline devices are left out"
    assert peers[0] == {"name": "Anns-iPhone", "host": "100.64.0.5", "dns": "anns-iphone.tail1.ts.net",
                        "address": "100.64.0.5", "os": "ios"}
    monkeypatch.setattr(tailscale, "answers", lambda host, port, timeout=1.5: host == "100.64.0.7")
    assert [p["name"] for p in tailscale.listening(rdp.PORT, ("linux",), STATUS)] == ["desk"]
    assert tailscale.listening(rdp.PORT, ("ios",), STATUS) == []


def test_companion_is_found_on_tailscale(monkeypatch):
    from frontline_msg import companion
    monkeypatch.setattr(companion, "_bonjour", lambda timeout: [])
    monkeypatch.setattr(tailscale, "status", lambda: STATUS)
    monkeypatch.setattr(tailscale, "answers", lambda host, port, timeout=1.5: port == companion.PORT)
    assert companion.discover() == [{"name": "Anns-iPhone", "host": "100.64.0.5", "port": 47800, "via": "tailscale"}]


def test_viewer_keys_map_to_linux_codes():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from frontline_msg.rdpview import evdev_code
    assert evdev_code(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier)) == 30
    assert evdev_code(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)) == 28
    assert evdev_code(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_1, Qt.KeyboardModifier.NoModifier)) == 2
    assert evdev_code(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_0, Qt.KeyboardModifier.NoModifier)) == 11
    # With a platform scan code (xkb: Linux code + 8), that wins.
    e = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, 38, 0, 0)
    assert evdev_code(e) == 30
