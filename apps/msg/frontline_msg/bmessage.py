"""bMessage: how Bluetooth MAP carries one text message (MAP 1.x, section 3.1.3)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from . import vcard


@dataclass
class BMessage:
    text: str = ""
    sender: str = ""            # the originator's number or address
    sender_name: str = ""
    recipients: list[str] | None = None
    folder: str = ""
    kind: str = "SMS_GSM"       # SMS_GSM, SMS_CDMA, MMS, EMAIL, IM

    @property
    def from_me(self) -> bool:
        return self.folder.lower().rstrip("/").endswith(("sent", "outbox"))


def parse(text: str) -> BMessage:
    msg = BMessage(recipients=[])
    text = text.replace("\r\n", "\n")
    body_start = text.find("BEGIN:MSG\n")
    body_end = text.rfind("\nEND:MSG")
    if body_start >= 0 and body_end > body_start:
        msg.text = text[body_start + len("BEGIN:MSG\n"):body_end].strip("\n")
    head = text[:body_start] if body_start >= 0 else text
    for line in head.split("\n"):
        key, _, value = line.partition(":")
        if key == "FOLDER":
            msg.folder = value.strip()
        elif key == "TYPE":
            msg.kind = value.strip()
    envelope = head.find("BEGIN:BENV")
    originator = vcard.parse(head[:envelope] if envelope >= 0 else head)
    if originator:
        o = originator[0]
        msg.sender = (o.handles or [""])[0]
        msg.sender_name = o.name
    if envelope >= 0:
        for card in vcard.parse(head[envelope:]):
            msg.recipients.extend(card.handles[:1])
    return msg


def build(to: str, text: str, kind: str = "SMS_GSM") -> str:
    """A message to send (PushMessage into telecom/msg/outbox)."""
    body = f"BEGIN:MSG\r\n{text}\r\nEND:MSG\r\n"
    tel = "EMAIL" if "@" in to else "TEL"
    return ("BEGIN:BMSG\r\nVERSION:1.0\r\nSTATUS:READ\r\nTYPE:" + kind + "\r\nFOLDER:TELECOM/MSG/OUTBOX\r\n"
            "BEGIN:VCARD\r\nVERSION:2.1\r\nN:\r\nTEL:\r\nEND:VCARD\r\n"
            "BEGIN:BENV\r\nBEGIN:VCARD\r\nVERSION:2.1\r\nN:\r\n" + f"{tel}:{to}\r\n" + "END:VCARD\r\n"
            "BEGIN:BBODY\r\nCHARSET:UTF-8\r\n" + f"LENGTH:{len(body.encode())}\r\n" + body +
            "END:BBODY\r\nEND:BENV\r\nEND:BMSG\r\n")


def timestamp_ms(stamp: str) -> int:
    """MAP's "20261118T101500" (local time), "20261118T101500Z" or "20261118T101500+0100" as Unix ms."""
    stamp = stamp.strip()
    try:
        if stamp.endswith("Z"):
            when = dt.datetime.strptime(stamp[:-1], "%Y%m%dT%H%M%S").replace(tzinfo=dt.timezone.utc)
        elif len(stamp) > 15 and stamp[15] in "+-":
            when = dt.datetime.strptime(stamp, "%Y%m%dT%H%M%S%z")
        else:
            when = dt.datetime.strptime(stamp[:15], "%Y%m%dT%H%M%S").astimezone()
    except ValueError:
        return 0
    return int(when.timestamp() * 1000)
