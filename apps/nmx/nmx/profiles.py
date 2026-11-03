"""Saved connections: /etc/nmx/connections/*.nmx, readable by root only.

The format is NetworkManager's keyfile (INI with the same section and key names: connection, wifi, wifi-security,
802-1x, ipv4, ipv6), so nmcli property names map straight onto it and NetworkManager's own profiles import as they
are. nmx adds one section, [nmx], for what it learned: the RADIUS server's certificate and domain, pinned on first
use.
"""

from __future__ import annotations

import configparser
import os
import re
import uuid as uuidlib
from dataclasses import dataclass
from pathlib import Path

from . import security

CONNECTIONS = Path(os.environ.get("NMX_CONNECTIONS", "/etc/nmx/connections"))
NM_CONNECTIONS = Path(os.environ.get("NMX_NM_CONNECTIONS", "/etc/NetworkManager/system-connections"))

# nmcli's setting aliases and the short names its `connection add` takes.
SECTION_ALIASES = {
    "802-11-wireless": "wifi", "802-11-wireless-security": "wifi-security", "wifi-sec": "wifi-security",
    "802-3-ethernet": "ethernet", "con": "connection",
}
SHORT_PROPERTIES = {
    "con-name": "connection.id", "ifname": "connection.interface-name", "type": "connection.type",
    "autoconnect": "connection.autoconnect", "ssid": "wifi.ssid", "ip4": "ipv4.addresses", "gw4": "ipv4.gateway",
    "ip6": "ipv6.addresses", "gw6": "ipv6.gateway", "hidden": "wifi.hidden", "password": "wifi-security.psk",
    "psk": "wifi-security.psk", "identity": "802-1x.identity", "username": "802-1x.identity",
}
TYPE_ALIASES = {"802-11-wireless": "wifi", "wireless": "wifi", "wifi": "wifi", "802-3-ethernet": "ethernet", "ethernet": "ethernet"}
SECRET_KEYS = {("wifi-security", "psk"), ("wifi-security", "wep-key0"), ("802-1x", "password"), ("802-1x", "private-key-password")}


def normalise_property(name: str) -> tuple[str, str]:
    """'wifi-sec.psk' -> ('wifi-security', 'psk'); 'con-name' -> ('connection', 'id')."""
    name = SHORT_PROPERTIES.get(name, name)
    if "." not in name:
        raise ValueError(f"unknown property '{name}'")
    section, key = name.split(".", 1)
    section = SECTION_ALIASES.get(section, section)
    if section not in ("connection", "wifi", "wifi-security", "802-1x", "ipv4", "ipv6", "ethernet", "nmx"):
        raise ValueError(f"unknown setting '{section}'")
    return section, key


def truthy(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "yes", "true", "on")


@dataclass
class Profile:
    data: configparser.ConfigParser
    path: Path | None = None

    @staticmethod
    def new(name: str, type_: str, **props: str) -> "Profile":
        cp = _parser()
        cp["connection"] = {"id": name, "uuid": str(uuidlib.uuid4()), "type": TYPE_ALIASES.get(type_, type_),
                            "autoconnect": "true"}
        if cp["connection"]["type"] == "wifi":
            cp["wifi"] = {"mode": "infrastructure", "ssid": name}
        cp["ipv4"] = {"method": "auto"}
        cp["ipv6"] = {"method": "auto"}
        profile = Profile(cp)
        for key, value in props.items():
            profile.set(key, value)
        return profile

    # ── fields ──
    def get(self, section: str, key: str, default: str = "") -> str:
        section = SECTION_ALIASES.get(section, section)
        return self.data.get(section, key, fallback=default)

    def set(self, prop: str, value: str) -> None:
        section, key = normalise_property(prop)
        if section == "connection" and key == "type":
            value = TYPE_ALIASES.get(value, value)
        if section == "wifi-security" and key == "key-mgmt":
            value = value.lower()
        if section == "wifi" and key == "hidden":
            value = "true" if truthy(value) else "false"
        if section == "connection" and key == "autoconnect":
            value = "true" if truthy(value, True) else "false"
        if not self.data.has_section(section):
            self.data.add_section(section)
        if value == "":
            self.data.remove_option(section, key)
        else:
            self.data.set(section, key, value)

    @property
    def id(self) -> str:
        return self.get("connection", "id")

    @property
    def uuid(self) -> str:
        return self.get("connection", "uuid")

    @property
    def type(self) -> str:
        return TYPE_ALIASES.get(self.get("connection", "type"), self.get("connection", "type"))

    @property
    def ssid(self) -> str:
        return self.get("wifi", "ssid")

    @property
    def interface(self) -> str:
        return self.get("connection", "interface-name")

    @property
    def autoconnect(self) -> bool:
        return truthy(self.get("connection", "autoconnect"), True)

    @property
    def priority(self) -> int:
        try:
            return int(self.get("connection", "autoconnect-priority", "0"))
        except ValueError:
            return 0

    @property
    def hidden(self) -> bool:
        return truthy(self.get("wifi", "hidden"))

    @property
    def kind(self) -> str:
        """Security kind (security.Security.kind) of a Wi-Fi profile."""
        if not self.data.has_section("wifi-security"):
            return "open"
        mgmt = self.get("wifi-security", "key-mgmt")
        if mgmt == "none" and (self.get("wifi-security", "wep-key0") or self.get("wifi-security", "wep-key-type")):
            return "wep"
        kind = security.kind_from_key_mgmt(mgmt)
        if kind == "psk" and self.get("nmx", "sae") == "true":
            return "psk-sae"
        return kind

    def eap(self) -> dict:
        return dict(self.data["802-1x"]) if self.data.has_section("802-1x") else {}

    def network_block(self, scanned: security.Security | None = None) -> dict[str, str]:
        """wpa_supplicant fields for this profile. What the AP advertises now (scanned) refines the AKMs: a
        WPA2-only profile on a network that now offers WPA3 too joins with both."""
        kind = self.kind
        if scanned is not None and kind in ("psk", "sae", "psk-sae") and scanned.kind in ("psk", "sae", "psk-sae"):
            kind = scanned.kind
        if scanned is not None and kind == "eap" and scanned.kind == "eap-suite-b":
            kind = "eap-suite-b"
        eap = self.eap()
        pinned = self.get("nmx", "server-cert")
        if pinned and eap.get("ca-cert", "auto") in ("auto", ""):
            eap["ca-cert"] = pinned
        if self.get("nmx", "server-domain") and not eap.get("domain-suffix-match"):
            eap["domain-suffix-match"] = self.get("nmx", "server-domain")
        return security.network_block(
            ssid=self.ssid, kind=kind, psk=self.get("wifi-security", "psk"),
            wep_key=self.get("wifi-security", "wep-key0"), eap=eap, hidden=self.hidden,
            bssid=self.get("wifi", "bssid"), ft=scanned.ft if scanned else True)

    def ipv4(self) -> dict:
        return dict(self.data["ipv4"]) if self.data.has_section("ipv4") else {"method": "auto"}

    def ipv6(self) -> dict:
        return dict(self.data["ipv6"]) if self.data.has_section("ipv6") else {"method": "auto"}

    def as_dict(self, show_secrets: bool = False) -> dict[str, dict[str, str]]:
        out = {}
        for section in self.data.sections():
            out[section] = {k: ("<hidden>" if (section, k) in SECRET_KEYS and not show_secrets else v)
                            for k, v in self.data[section].items()}
        return out

    def text(self) -> str:
        lines = []
        for section in self.data.sections():
            lines.append(f"[{section}]")
            lines += [f"{k}={v}" for k, v in self.data[section].items()]
            lines.append("")
        return "\n".join(lines)


def _parser() -> configparser.ConfigParser:
    cp = configparser.ConfigParser(interpolation=None, strict=False, delimiters=("=",), comment_prefixes=("#", ";"))
    cp.optionxform = str  # keys keep their case (NetworkManager's are lower-case anyway)
    return cp


def parse(text: str, path: Path | None = None) -> Profile:
    cp = _parser()
    cp.read_string(text)
    if not cp.has_option("connection", "id"):
        raise ValueError(f"{path or 'profile'}: no connection id")
    if not cp.has_option("connection", "uuid"):
        cp.set("connection", "uuid", str(uuidlib.uuid4()))
    type_ = cp.get("connection", "type", fallback="wifi")
    cp.set("connection", "type", TYPE_ALIASES.get(type_, type_))
    return Profile(cp, path)


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "connection"


class Store:
    def __init__(self, directory: Path = CONNECTIONS):
        self.directory = directory

    def all(self) -> list[Profile]:
        out = []
        if not self.directory.is_dir():
            return out
        for path in sorted(self.directory.glob("*.nmx")):
            try:
                out.append(parse(path.read_text(encoding="utf-8"), path))
            except (OSError, ValueError, configparser.Error):
                continue
        return out

    def find(self, key: str) -> Profile | None:
        """By name, UUID or (for Wi-Fi) SSID, as nmcli's `connection up ID` finds them."""
        profiles = self.all()
        for test in (lambda p: p.id == key, lambda p: p.uuid == key, lambda p: p.type == "wifi" and p.ssid == key):
            for profile in profiles:
                if test(profile):
                    return profile
        return None

    def for_ssid(self, ssid: str) -> list[Profile]:
        return [p for p in self.all() if p.type == "wifi" and p.ssid == ssid]

    def save(self, profile: Profile) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = profile.path or self.directory / f"{safe_name(profile.id)}.nmx"
        if profile.path is None:
            n = 1
            while path.exists():
                n += 1
                path = self.directory / f"{safe_name(profile.id)}-{n}.nmx"
        tmp = path.with_name(f".{path.name}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(profile.text())
        os.replace(tmp, path)
        profile.path = path
        return path

    def delete(self, profile: Profile) -> None:
        if profile.path:
            profile.path.unlink(missing_ok=True)


def import_networkmanager(store: Store, source: Path = NM_CONNECTIONS) -> list[str]:
    """Bring NetworkManager's saved Wi-Fi and Ethernet connections over, once. Returns the names imported."""
    imported = []
    if not source.is_dir():
        return imported
    have = {p.uuid for p in store.all()}
    for path in sorted(source.glob("*.nmconnection")):
        try:
            profile = parse(path.read_text(encoding="utf-8"), None)
        except (OSError, ValueError, configparser.Error):
            continue
        if profile.type not in ("wifi", "ethernet") or profile.uuid in have:
            continue
        eap = profile.eap()
        for key in ("ca-cert", "client-cert", "private-key"):
            if eap.get(key, "").startswith("file://"):
                profile.set(f"802-1x.{key}", eap[key][len("file://"):])
        store.save(profile)
        imported.append(profile.id)
    return imported
