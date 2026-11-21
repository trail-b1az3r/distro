"""vCards (2.1 and 3.0) as phones send them over Bluetooth PBAP: names, numbers, emails and photos."""

from __future__ import annotations

import base64
import binascii
import quopri
import re
from dataclasses import dataclass, field


@dataclass
class Card:
    name: str = ""
    org: str = ""
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    photo: bytes = b""
    uid: str = ""

    @property
    def handles(self) -> list[str]:
        return self.phones + self.emails


def unfold(text: str) -> list[str]:
    """Logical lines: a line starting with a space or tab continues the one before (and a quoted-printable line
    ending in '=' continues into the next)."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif lines and lines[-1].endswith("=") and "QUOTED-PRINTABLE" in lines[-1].split(":", 1)[0].upper():
            lines[-1] = lines[-1][:-1] + raw
        else:
            lines.append(raw)
    return [line for line in lines if line]


def _params(head: str) -> tuple[str, dict[str, str]]:
    parts = head.split(";")
    name = parts[0].split(".")[-1].upper()          # "item1.EMAIL" -> EMAIL
    params: dict[str, str] = {}
    for p in parts[1:]:
        key, _, value = p.partition("=")
        if value:
            params[key.upper()] = value
        else:
            params.setdefault("TYPE", "")
            params[key.upper()] = key                # 2.1: ";BASE64", ";QUOTED-PRINTABLE", ";CELL"
    return name, params


def _decode(value: str, params: dict[str, str]) -> str:
    if params.get("ENCODING", "").upper() in ("QUOTED-PRINTABLE",) or "QUOTED-PRINTABLE" in params:
        charset = params.get("CHARSET", "utf-8")
        try:
            return quopri.decodestring(value.encode("latin-1", "replace")).decode(charset, "replace")
        except LookupError:
            return quopri.decodestring(value.encode("latin-1", "replace")).decode("utf-8", "replace")
    return value.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").replace("\\\\", "\\")


def parse(text: str) -> list[Card]:
    cards: list[Card] = []
    card: Card | None = None
    n_name = ""
    for line in unfold(text):
        head, sep, value = line.partition(":")
        if not sep:
            continue
        name, params = _params(head)
        if name == "BEGIN" and value.strip().upper() == "VCARD":
            card, n_name = Card(), ""
            continue
        if card is None:
            continue
        if name == "END" and value.strip().upper() == "VCARD":
            if not card.name:
                card.name = n_name or card.org or (card.handles[0] if card.handles else "")
            cards.append(card)
            card = None
        elif name == "FN":
            card.name = _decode(value, params).strip()
        elif name == "N":
            parts = [p.strip() for p in _decode(value, params).split(";")]
            family, given = (parts + ["", ""])[:2]
            n_name = f"{given} {family}".strip()
        elif name == "ORG":
            card.org = _decode(value, params).split(";")[0].strip()
        elif name == "TEL":
            number = re.sub(r"[^\d+*#]", "", value.removeprefix("tel:"))
            if number and number not in card.phones:
                card.phones.append(number)
        elif name == "EMAIL":
            email = value.strip().lower()
            if email and email not in card.emails:
                card.emails.append(email)
        elif name == "PHOTO":
            encoding = params.get("ENCODING", "").upper()
            if encoding in ("B", "BASE64") or "BASE64" in params or value.startswith("data:"):
                data = value.split(",", 1)[1] if value.startswith("data:") else value
                try:
                    card.photo = base64.b64decode(re.sub(r"\s+", "", data), validate=False)
                except (binascii.Error, ValueError):
                    pass
        elif name == "UID":
            card.uid = value.strip()
    return cards
