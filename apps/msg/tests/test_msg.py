"""nexora-msg: the store (Rust, through Python), backups, Bluetooth's formats and the companion's protocol."""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fakephone  # noqa: E402
from nexora_msg import bmessage, companion, core, vcard  # noqa: E402
from nexora_msg.service import Service  # noqa: E402


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXORA_MSG_DATA", str(tmp_path / "data"))
    try:
        core.find_binary()
    except core.CoreError:
        subprocess.run(["cargo", "build", "--quiet"], cwd=APP / "core", check=True)
    (tmp_path / "data").mkdir()
    s = Service(tmp_path / "data" / "messages.db")
    yield s
    s.close()


def test_backup_import_reads_everything(svc, tmp_path):
    backup = fakephone.make(tmp_path / "backup")
    result = svc.import_backup(str(backup))
    assert result == {"added": 5, "seen": 5, "contacts": 2}, "the reaction is not a message"
    chats = {c["title"]: c for c in svc.chats()}
    assert set(chats) == {"Ann Lee", "Climbing crew"}, "names from the address book; the group's own name"
    ann = svc.messages(chats["Ann Lee"]["id"])
    assert [m["text"] for m in ann] == ["Are we still on for pizza tonight?", "Yes! 7pm at the café",
                                        "Sent from iOS 17: the text is only in attributedBody"], "no reactions"
    assert ann[1]["from_me"] and ann[0]["sender"] == "Ann Lee"
    group = svc.messages(chats["Climbing crew"]["id"])
    picture = group[0]["attachments"][0]
    assert picture["mime"] == "image/jpeg" and Path(picture["path"]).read_bytes().startswith(b"\xff\xd8")
    assert group[1]["sender"] == "Bo", "emails match whatever their case"
    assert chats["Climbing crew"]["last_text"] == "Bouldering on Saturday?"
    # Again: nothing twice.
    assert svc.import_backup(str(backup))["added"] == 0


def test_search_finds_messages_people_and_chats(svc, tmp_path):
    svc.import_backup(str(fakephone.make(tmp_path / "backup")))
    found = svc.search("cafe 7pm")
    assert len(found["messages"]) == 1 and "\x02café\x03" in found["messages"][0]["snippet"]
    assert svc.search("attributed")["messages"][0]["text"].startswith("Sent from iOS 17")
    assert [c["name"] for c in svc.search("crag")["contacts"]] == ["Bo"]
    assert [c["title"] for c in svc.search("climb")["chats"]] == ["Climbing crew"]
    assert svc.search("nothing-like-this")["messages"] == []


def test_bluetooth_and_backup_copies_are_one_message(svc, tmp_path):
    # A message over Bluetooth first (no id, the time to the second), then the backup's copy.
    added = svc.add_messages([{"handle": "+1 555-010-2030", "date_ms": 1_700_000_000_500, "from_me": False,
                               "text": "Are we still on for pizza tonight?", "source": "map"}])
    assert added == 1
    svc.import_backup(str(fakephone.make(tmp_path / "backup")))
    chats = svc.chats()
    ann = next(c for c in chats if c["title"] == "Ann Lee")
    texts = [m["text"] for m in svc.messages(ann["id"])]
    assert texts.count("Are we still on for pizza tonight?") == 1
    assert len(chats) == 2


def test_encrypted_backup_is_refused_clearly(svc, tmp_path):
    backup = fakephone.make(tmp_path / "backup")
    (backup / "Manifest.plist").write_text("<plist><dict><key>IsEncrypted</key>\n\t<true/></dict></plist>")
    with pytest.raises(core.CoreError, match="encrypted"):
        svc.import_backup(str(backup))


def test_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXORA_MSG_DATA", str(tmp_path / "data"))
    backup = fakephone.make(tmp_path / "backup")
    env = {**os.environ, "PYTHONPATH": str(APP)}
    store = str(tmp_path / "s.db")
    run = lambda *a: subprocess.run([sys.executable, "-m", "nexora_msg", "--store", store, *a], env=env,
                                    capture_output=True, text=True, timeout=60)
    out = run("import", str(backup))
    assert out.returncode == 0 and "5 new messages" in out.stdout, out.stderr
    out = run("search", "pizza")
    assert "Ann Lee" in out.stdout and "pizza" in out.stdout


# ── Bluetooth formats ──

def test_vcards_from_pbap():
    text = ("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Ann Lee\r\nN:Lee;Ann;;;\r\nTEL;TYPE=CELL:+1 (555) 010-2030\r\n"
            "EMAIL;TYPE=INTERNET:Ann@Example.com\r\nPHOTO;ENCODING=b;TYPE=JPEG:" + base64.b64encode(b"\xff\xd8xy").decode()[:4]
            + "\r\n " + base64.b64encode(b"\xff\xd8xy").decode()[4:] + "\r\nEND:VCARD\r\n"
            "BEGIN:VCARD\r\nVERSION:2.1\r\nN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:M=C3=BCller;J=C3=BCrgen\r\n"
            "TEL;CELL:0049 30 1234\r\nEND:VCARD\r\n")
    ann, juergen = vcard.parse(text)
    assert ann.name == "Ann Lee" and ann.phones == ["+15550102030"] and ann.emails == ["ann@example.com"]
    assert ann.photo == b"\xff\xd8xy"
    assert juergen.name == "Jürgen Müller" and juergen.phones == ["0049301234"]


def test_bmessage_round_trip():
    built = bmessage.build("+15550102030", "On my way 🚲")
    assert "LENGTH:" in built and built.count("BEGIN:MSG") == 1
    length = int(built.split("LENGTH:")[1].split("\r\n")[0])
    assert length == len("BEGIN:MSG\r\nOn my way 🚲\r\nEND:MSG\r\n".encode())
    incoming = ("BEGIN:BMSG\r\nVERSION:1.0\r\nSTATUS:UNREAD\r\nTYPE:SMS_GSM\r\nFOLDER:TELECOM/MSG/INBOX\r\n"
                "BEGIN:VCARD\r\nVERSION:2.1\r\nN:Lee;Ann\r\nTEL:+15550102030\r\nEND:VCARD\r\nBEGIN:BENV\r\n"
                "BEGIN:BBODY\r\nCHARSET:UTF-8\r\nLENGTH:40\r\nBEGIN:MSG\r\nline one\r\nline two\r\nEND:MSG\r\n"
                "END:BBODY\r\nEND:BENV\r\nEND:BMSG\r\n")
    m = bmessage.parse(incoming)
    assert m.text == "line one\nline two" and m.sender == "+15550102030" and m.sender_name == "Ann Lee"
    assert not m.from_me
    assert bmessage.timestamp_ms("20231114T221320Z") == 1_700_000_000_000
    assert bmessage.timestamp_ms("20231114T231320+0100") == 1_700_000_000_000


def test_map_listing_entry():
    from nexora_msg.bluetooth import message_from_listing
    m = message_from_listing({"Subject": "hi", "SenderAddress": "+15550102030", "Timestamp": "20231114T221320Z",
                              "Type": "sms-gsm"}, "inbox")
    assert m == {"handle": "+15550102030", "from_me": False, "date_ms": 1_700_000_000_000, "text": "hi",
                 "service": "SMS", "source": "map", "status": ""}
    assert message_from_listing({"RecipientAddress": "x@y.z", "Sent": True}, "sent")["from_me"]


# ── the companion's protocol, against a stand-in for the iPhone app ──

class FakePhone(threading.Thread):
    """What apps/msg/ios does, in Python: the same hello, key and frames."""

    def __init__(self, paired: bool):
        super().__init__(daemon=True)
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.paired = paired
        self.key = companion.X25519PrivateKey.generate()
        self.code = ""
        self.got: list[dict] = []

    def run(self):
        conn, _ = self.server.accept()
        ch = companion.Channel(conn, b"P2D\0", b"D2P\0")
        hello = ch.recv()
        mine = os.urandom(16)
        ch.send({"hello": "nexora-msg-ios", "v": 1, "pub": base64.b64encode(companion.public_bytes(self.key)).decode(),
                 "nonce": base64.b64encode(mine).decode(), "paired": self.paired, "name": "Ann's iPhone"})
        shared = self.key.exchange(companion.X25519PublicKey.from_public_bytes(base64.b64decode(hello["pub"])))
        self.code = companion.pairing_code(shared)
        ch.aead = companion.ChaCha20Poly1305(companion.session_key(shared, base64.b64decode(hello["nonce"]), mine))
        if not self.paired:
            ch.send({"event": "paired"})          # the user tapped Pair
        while True:
            try:
                req = ch.recv()
            except (companion.CompanionError, OSError):
                return
            self.got.append(req)
            if req["op"] == "contacts":
                data = [{"id": "A1", "name": "Ann Lee", "phones": ["+15550102030"], "emails": [],
                         "photo": base64.b64encode(b"\xff\xd8photo").decode()}]
            else:
                data = {"result": "sent"}
            ch.send({"id": req["id"], "ok": True, "data": data})


def test_companion_pairs_encrypts_and_talks(tmp_path):
    phone = FakePhone(paired=False)
    phone.start()
    c = companion.Companion(key=companion.identity(tmp_path / "id.key"), name="desk")
    c.connect_tcp("127.0.0.1", phone.port)
    assert c.wait_paired(5)
    assert c.code == phone.code and len(c.code) == 6, "both sides show the same code"
    assert c.contacts()[0]["name"] == "Ann Lee"
    img = tmp_path / "cat.jpg"
    img.write_bytes(b"\xff\xd8cat")
    assert c.send(["+15550102030"], "look", img) == {"result": "sent"}
    sent = phone.got[-1]
    assert base64.b64decode(sent["image"]) == b"\xff\xd8cat" and sent["filename"] == "cat.jpg"
    c.close()
    # The key is kept: the same computer next time.
    assert companion.public_bytes(companion.identity(tmp_path / "id.key")) == companion.public_bytes(c.key)


def test_frames_are_encrypted_and_checked():
    a, b = socket.socketpair()
    key = os.urandom(32)
    left = companion.Channel(a, b"D2P\0", b"P2D\0")
    right = companion.Channel(b, b"P2D\0", b"D2P\0")
    left.aead = companion.ChaCha20Poly1305(key)
    right.aead = companion.ChaCha20Poly1305(key)
    left.send({"op": "ping", "secret": "pizza"})
    (length,) = struct.unpack(">I", b.recv(4, socket.MSG_PEEK))
    raw = b.recv(4 + length, socket.MSG_PEEK)
    assert b"pizza" not in raw, "nothing in the clear"
    assert right.recv() == {"op": "ping", "secret": "pizza"}
    # A replayed frame fails (the counter moved on).
    a.sendall(raw)
    with pytest.raises(companion.CompanionError):
        right.recv()
