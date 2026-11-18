"""A small iPhone backup, as idevicebackup2 makes them: sms.db (with an iOS 16 message whose text is only in
attributedBody, a group chat, a reaction to skip and a picture) and the address book."""

from __future__ import annotations

import hashlib
import plistlib
import sqlite3
from pathlib import Path

APPLE = 978307200


def file_id(domain: str, path: str) -> str:
    return hashlib.sha1(f"{domain}-{path}".encode()).hexdigest()


def place(backup: Path, domain: str, path: str) -> Path:
    fid = file_id(domain, path)
    target = backup / fid[:2] / fid
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def typedstream(text: str) -> bytes:
    b = text.encode()
    length = bytes([len(b)]) if len(b) < 0x80 else b"\x81" + len(b).to_bytes(2, "little")
    return (b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12NSAttributedString\x00\x84\x84\x08NSObject"
            b"\x00\x85\x92\x84\x84\x84\x08NSString\x01\x94\x84\x01+" + length + b + b"\x86\x84\x02iI\x01")


def ns(unix: int) -> int:
    return (unix - APPLE) * 1_000_000_000


def make(backup: Path, encrypted: bool = False) -> Path:
    backup.mkdir(parents=True, exist_ok=True)
    (backup / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": encrypted}))
    sms = place(backup, "HomeDomain", "Library/SMS/sms.db")
    db = sqlite3.connect(sms)
    db.executescript("""
    CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT, service TEXT);
    CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, guid TEXT, chat_identifier TEXT, display_name TEXT, service_name TEXT);
    CREATE TABLE message (ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, attributedBody BLOB, handle_id INTEGER,
        date INTEGER, is_from_me INTEGER, service TEXT, associated_message_type INTEGER DEFAULT 0);
    CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
    CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
    CREATE TABLE attachment (ROWID INTEGER PRIMARY KEY, guid TEXT, filename TEXT, mime_type TEXT, transfer_name TEXT);
    CREATE TABLE message_attachment_join (message_id INTEGER, attachment_id INTEGER);
    INSERT INTO handle VALUES (1, '+15550102030', 'iMessage'), (2, 'bo@example.com', 'iMessage');
    INSERT INTO chat VALUES (1, 'iMessage;-;+15550102030', '+15550102030', '', 'iMessage'),
                            (2, 'iMessage;+;chat99', 'chat99', 'Climbing crew', 'iMessage');
    INSERT INTO chat_handle_join VALUES (1, 1), (2, 1), (2, 2);
    """)
    rows = [
        (1, "m1", "Are we still on for pizza tonight?", None, 1, ns(1_700_000_000), 0, "iMessage", 0, 1),
        (2, "m2", "Yes! 7pm at the café", None, 0, ns(1_700_000_060), 1, "iMessage", 0, 1),
        (3, "m3", None, typedstream("Sent from iOS 17: the text is only in attributedBody"), 1, ns(1_700_000_120), 0,
         "iMessage", 0, 1),
        (4, "m4", "Loved “Yes! 7pm at the café”", None, 1, ns(1_700_000_130), 0, "iMessage", 2000, 1),
        (5, "m5", "￼", None, 2, ns(1_700_000_500), 0, "iMessage", 0, 2),
        (6, "m6", "Bouldering on Saturday?", None, 2, ns(1_700_000_600), 0, "iMessage", 0, 2),
    ]
    for r in rows:
        db.execute("INSERT INTO message VALUES (?,?,?,?,?,?,?,?,?)", r[:9])
        db.execute("INSERT INTO chat_message_join VALUES (?, ?)", (r[9], r[0]))
    rel = "Library/SMS/Attachments/ab/11/AT1/IMG_0001.JPG"
    db.execute("INSERT INTO attachment VALUES (1, 'AT1', ?, 'image/jpeg', 'IMG_0001.JPG')", ("~/" + rel,))
    db.execute("INSERT INTO message_attachment_join VALUES (5, 1)")
    db.commit()
    db.close()
    place(backup, "MediaDomain", rel).write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    book = place(backup, "HomeDomain", "Library/AddressBook/AddressBook.sqlitedb")
    db = sqlite3.connect(book)
    db.executescript("""
    CREATE TABLE ABPerson (ROWID INTEGER PRIMARY KEY, First TEXT, Last TEXT, Organization TEXT, Nickname TEXT);
    CREATE TABLE ABMultiValue (UID INTEGER PRIMARY KEY, record_id INTEGER, property INTEGER, value TEXT);
    INSERT INTO ABPerson VALUES (1, 'Ann', 'Lee', NULL, NULL), (2, 'Bo', NULL, 'Crag Gym', NULL);
    INSERT INTO ABMultiValue VALUES (1, 1, 3, '(555) 010-2030'), (2, 2, 4, 'Bo@Example.com');
    """)
    db.commit()
    db.close()
    return backup
