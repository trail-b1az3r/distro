"""What a Wi-Fi network asks for, read from wpa_supplicant's scan flags, and the wpa_supplicant network block that
joins it.

The flags look like ``[WPA2-PSK-CCMP][WPS][ESS]``, ``[WPA2-PSK+SAE-CCMP][ESS]``, ``[RSN-SAE-CCMP]``,
``[WPA2-EAP+FT/EAP-CCMP-preauth]``, ``[WPA2-EAP-SUITE-B-192-GCMP-256]``, ``[WPA2-OWE-CCMP]``, ``[WEP]`` or just
``[ESS]``. Every proto/AKM/cipher group is read, not only the first, so a network advertising WPA1 and WPA2, or
WPA2-PSK and WPA3-SAE together (transition mode), is joined with everything it offers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SYSTEM_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

_CIPHER = r"(?:CCMP-256|GCMP-256|CCMP|TKIP|GCMP|WEP104|WEP40|BIP[-A-Z0-9]*|none)"
_GROUP = re.compile(rf"^(WPA2|WPA3|WPA|RSN|OSEN)-(.+?)-({_CIPHER}(?:\+{_CIPHER})*)(?:-preauth)?$")


@dataclass
class Security:
    """A network's security, as far as joining it goes."""

    kind: str = "open"            # open, owe, wep, psk, sae, psk-sae, eap, eap-suite-b
    wpa1: bool = False
    wpa2: bool = False            # an RSN element (WPA2 or WPA3)
    ft: bool = False              # fast transition (802.11r) offered
    sha256: bool = False          # the SHA-256 AKMs (PSK-SHA256, EAP-SHA256) offered
    owe_transition: bool = False  # an open network that has an OWE twin
    wps: bool = False
    akms: list[str] = field(default_factory=list)

    @property
    def needs_password(self) -> bool:
        return self.kind in ("wep", "psk", "sae", "psk-sae", "eap", "eap-suite-b")

    @property
    def needs_username(self) -> bool:
        return self.kind in ("eap", "eap-suite-b")

    @property
    def enterprise(self) -> bool:
        return self.kind in ("eap", "eap-suite-b")

    @property
    def pmf(self) -> int:
        """Protected management frames: 0 off, 1 when the AP offers it, 2 required (WPA3-only, OWE, Suite-B)."""
        if self.kind in ("sae", "owe", "eap-suite-b"):
            return 2
        if self.wpa2:
            return 1
        return 0

    @property
    def label(self) -> str:
        """The SECURITY column as nmcli prints it."""
        if self.kind == "open":
            return ""
        if self.kind == "owe":
            return "OWE"
        if self.kind == "wep":
            return "WEP"
        parts = []
        if self.wpa1:
            parts.append("WPA1")
        if self.kind in ("psk", "eap") and self.wpa2:
            parts.append("WPA2")
        if self.kind == "psk-sae":
            parts += ["WPA2", "WPA3"]
        if self.kind in ("sae", "eap-suite-b"):
            parts.append("WPA3")
        if self.enterprise:
            parts.append("802.1X")
        return " ".join(parts)

    @property
    def describe(self) -> str:
        """For people: what it is and what it asks for."""
        return {
            "open": "open (no password)",
            "owe": "Enhanced Open (encrypted, no password)",
            "wep": "WEP (password; outdated and insecure)",
            "psk": "WPA2 Personal (password)",
            "sae": "WPA3 Personal (password)",
            "psk-sae": "WPA2/WPA3 Personal (password)",
            "eap": "WPA2/WPA3 Enterprise (username and password)",
            "eap-suite-b": "WPA3 Enterprise 192-bit (username and password or certificate)",
        }[self.kind]


def from_flags(flags: str) -> Security:
    sec = Security()
    tokens = re.findall(r"\[([^\]]*)\]", flags or "")
    akms: set[str] = set()
    for token in tokens:
        if token == "WEP":
            akms.add("WEP")
            continue
        if token == "WPS" or token.startswith("WPS-"):
            sec.wps = True
            continue
        if token == "OWE-TRANS" or token == "OWE-TRANS-OPEN":
            sec.owe_transition = True
            continue
        match = _GROUP.match(token)
        if not match:
            continue
        proto, akm_text, _cipher = match.groups()
        if proto == "WPA":
            sec.wpa1 = True
        else:
            sec.wpa2 = True
        for akm in akm_text.split("+"):
            akms.add(akm)
    sec.akms = sorted(akms)
    sec.ft = any(a.startswith("FT/") for a in akms)
    sec.sha256 = any(a.endswith("SHA256") for a in akms)
    base = {a.split("/")[-1].replace("-SHA256", "") for a in akms}
    if any(a.startswith("EAP-SUITE-B") for a in base):
        sec.kind = "eap-suite-b"
    elif "EAP" in base:
        sec.kind = "eap"
    elif "SAE" in base or "SAE-EXT-KEY" in base:
        sec.kind = "psk-sae" if "PSK" in base else "sae"
    elif "PSK" in base:
        sec.kind = "psk"
    elif "OWE" in base:
        sec.kind = "owe"
    elif "WEP" in base:
        sec.kind = "wep"
    else:
        sec.kind = "open"
    return sec


def kind_from_key_mgmt(key_mgmt: str) -> str:
    """A saved profile's wifi-sec.key-mgmt (NetworkManager's names) as a Security kind."""
    return {
        "": "open", "none": "open", "owe": "owe", "wpa-psk": "psk", "sae": "sae", "wpa-eap": "eap",
        "wpa-eap-suite-b-192": "eap-suite-b", "ieee8021x": "wep",
    }.get((key_mgmt or "").lower(), "open")


def key_mgmt_for_kind(kind: str) -> str:
    """The reverse: what a profile records."""
    return {
        "open": "", "owe": "owe", "wep": "none", "psk": "wpa-psk", "sae": "sae", "psk-sae": "wpa-psk",
        "eap": "wpa-eap", "eap-suite-b": "wpa-eap-suite-b-192",
    }[kind]


# ── wpa_supplicant's network block ────────────────────────────────────────────────────────────────────────────────


def hexstr(text: str) -> str:
    """A string field as hex: wpa_supplicant reads unquoted hex for every string, so nothing needs escaping."""
    return text.encode("utf-8").hex()


def quoted(text: str) -> str:
    if "\n" in text or "\r" in text:
        raise ValueError("a newline is not allowed here")
    return f'"{text}"'


def valid_psk(psk: str) -> bool:
    return (8 <= len(psk) <= 63 and all(32 <= ord(c) < 127 for c in psk)) or bool(re.fullmatch(r"[0-9a-fA-F]{64}", psk))


def anonymous_identity(identity: str) -> str:
    """The outer identity for PEAP/TTLS: the realm only, so the username itself travels inside the TLS tunnel."""
    if "@" in identity:
        return "anonymous@" + identity.split("@", 1)[1]
    return ""


class MissingSecrets(Exception):
    def __init__(self, need: list[str]):
        super().__init__("secrets required: " + ", ".join(need))
        self.need = need


def network_block(*, ssid: str, kind: str, psk: str = "", wep_key: str = "", eap: dict | None = None,
                  hidden: bool = False, bssid: str = "", priority: int = 0, ft: bool = True,
                  pmf: int | None = None) -> dict[str, str]:
    """SET_NETWORK fields (already encoded) for one network. Raises MissingSecrets when something is missing."""
    block: dict[str, str] = {"ssid": hexstr(ssid), "scan_ssid": "1" if hidden else "0"}
    if bssid:
        block["bssid"] = bssid.lower()
    if priority:
        block["priority"] = str(max(0, priority))
    if kind == "open":
        block["key_mgmt"] = "NONE"
    elif kind == "owe":
        block["key_mgmt"] = "OWE"
        block["ieee80211w"] = "2"
    elif kind == "wep":
        if not wep_key:
            raise MissingSecrets(["password"])
        block["key_mgmt"] = "NONE"
        block["auth_alg"] = "OPEN SHARED"
        block["wep_tx_keyidx"] = "0"
        block["wep_key0"] = wep_key if re.fullmatch(r"[0-9a-fA-F]{10}|[0-9a-fA-F]{26}", wep_key) else quoted(wep_key)
    elif kind in ("psk", "sae", "psk-sae"):
        if not psk:
            raise MissingSecrets(["password"])
        if kind != "sae" and not valid_psk(psk):
            raise ValueError("a WPA password is 8 to 63 characters (or 64 hex digits)")
        mgmt = []
        if kind in ("psk", "psk-sae"):
            mgmt += ["WPA-PSK", "WPA-PSK-SHA256"] + (["FT-PSK"] if ft else [])
        if kind in ("sae", "psk-sae"):
            mgmt += ["SAE"] + (["FT-SAE"] if ft else [])
            # SAE takes any length; quoted strings are read up to the last quote, so quotes inside are fine.
            block["sae_password"] = quoted(psk)
        if kind != "sae":
            block["psk"] = psk if re.fullmatch(r"[0-9a-fA-F]{64}", psk) else quoted(psk)
        block["key_mgmt"] = " ".join(mgmt)
        block["ieee80211w"] = "2" if kind == "sae" else "1"
    elif kind in ("eap", "eap-suite-b"):
        block.update(eap_fields(eap or {}, suite_b=(kind == "eap-suite-b"), ft=ft))
    else:
        raise ValueError(f"unknown security {kind!r}")
    if pmf is not None and kind not in ("open", "wep"):
        block["ieee80211w"] = str(pmf)
    return block


def eap_fields(eap: dict, *, suite_b: bool = False, ft: bool = True) -> dict[str, str]:
    """The 802.1X part. eap: method, identity, password, anonymous-identity, phase2, ca-cert, domain-suffix-match,
    client-cert, private-key, private-key-password (NetworkManager's 802-1x names)."""
    method = (eap.get("eap") or "peap").split(";")[0].lower()
    identity = eap.get("identity", "")
    password = eap.get("password", "")
    need = []
    if method != "tls" and not identity:
        need.append("username")
    if method in ("peap", "ttls", "pwd", "leap", "fast") and not password:
        need.append("password")
    if method == "tls" and not (eap.get("client-cert") and eap.get("private-key")):
        need.append("certificate")
    if need:
        raise MissingSecrets(need)
    out: dict[str, str] = {}
    out["key_mgmt"] = "WPA-EAP-SUITE-B-192" if suite_b else " ".join(["WPA-EAP", "WPA-EAP-SHA256"] + (["FT-EAP"] if ft else []))
    out["ieee80211w"] = "2" if suite_b else "1"
    out["eap"] = method.upper()
    if identity:
        out["identity"] = hexstr(identity)
    anon = eap.get("anonymous-identity")
    if anon is None and method in ("peap", "ttls"):
        anon = anonymous_identity(identity)
    if anon:
        out["anonymous_identity"] = hexstr(anon)
    if password and method != "tls":
        out["password"] = hexstr(password)
    phase2 = (eap.get("phase2-auth") or "").lower()
    if method == "peap":
        out["phase2"] = quoted("auth=" + (phase2 or "mschapv2").upper())
    elif method == "ttls":
        phase2 = phase2 or "pap"
        prefix = "autheap=" if phase2 in ("md5", "gtc", "mschapv2-eap") else "auth="
        out["phase2"] = quoted(prefix + phase2.replace("-eap", "").upper())
    if method in ("peap", "ttls", "tls", "fast"):
        ca = eap.get("ca-cert", "auto") or "auto"
        if ca.startswith("file://"):
            ca = ca[len("file://"):]
        if ca in ("auto", "system"):
            out["ca_cert"] = quoted(SYSTEM_CA_BUNDLE)
        elif ca.startswith("hash://"):
            out["ca_cert"] = quoted(ca)
        elif ca != "none":
            out["ca_cert"] = quoted(ca)
        if eap.get("domain-suffix-match") and ca != "none" and not ca.startswith("hash://"):
            out["domain_suffix_match"] = quoted(eap["domain-suffix-match"])
    if method == "tls":
        out["client_cert"] = quoted(eap["client-cert"].removeprefix("file://"))
        out["private_key"] = quoted(eap["private-key"].removeprefix("file://"))
        if eap.get("private-key-password"):
            out["private_key_passwd"] = quoted(eap["private-key-password"])
    return out


def fallback_phase2(eap: dict) -> dict | None:
    """When an enterprise login fails before any certificate problem, the next method to try: PEAP/MSCHAPv2, then
    TTLS/PAP, then PEAP/GTC (what eduroam, campus and corporate networks use between them). None when tried all."""
    order = [("peap", "mschapv2"), ("ttls", "pap"), ("ttls", "mschapv2"), ("peap", "gtc")]
    current = ((eap.get("eap") or "peap").split(";")[0].lower(), (eap.get("phase2-auth") or "").lower()
               or ("mschapv2" if (eap.get("eap") or "peap").startswith("peap") else "pap"))
    if current not in order:
        return None
    index = order.index(current)
    if index + 1 >= len(order):
        return None
    method, phase2 = order[index + 1]
    return {**eap, "eap": method, "phase2-auth": phase2}
