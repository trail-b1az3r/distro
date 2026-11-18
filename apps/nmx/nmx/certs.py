"""Finding an enterprise (802.1X) network's CA certificate on its own.

An enterprise network's RADIUS server shows its certificate chain during every login attempt (wpa_supplicant's
CTRL-EVENT-EAP-PEER-CERT events carry each certificate, depth 0 being the server's own). nmx keeps that chain for
each network it tries, whether the login worked or not. Phones "trust on first use" by pinning the server's
certificate, which breaks the day it is renewed; nmx does that too at first, but once some Wi-Fi is fully online it
finds the CA that signed the server's certificate:

1. If the chain ends in a CA this system already trusts, the profile uses the system's CA bundle.
2. Otherwise the issuer is fetched over the internet from the URL in the certificate itself (Authority Information
   Access, "CA Issuers"), hop by hop up to a self-signed root, which is saved in /var/lib/nmx/ca/.

Either way the server's name (from its certificate) becomes the profile's domain-suffix-match, so only that
organisation's servers are accepted, and the pin is dropped (a renewed certificate from the same CA keeps working).
Other saved enterprise profiles of the same organisation (the same domain, e.g. eduroam and the campus network,
or a realm in the username) that have no CA yet get the same one.

The certificate work is done with the openssl command; nothing here needs a Python crypto library.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from . import __version__
from .security import SYSTEM_CA_BUNDLE

CHAINS = Path(os.environ.get("NMX_CHAINS", "/var/lib/nmx/chains"))
CA_DIR = Path(os.environ.get("NMX_CA_DIR", "/var/lib/nmx/ca"))
MAX_HOPS = 5
FETCH_TIMEOUT = 10
MAX_CERT = 256 * 1024


def _slug(ssid: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", ssid).strip("._") or "network"
    return f"{safe[:40]}-{hashlib.sha256(ssid.encode()).hexdigest()[:8]}"


def openssl(args: list[str], data: bytes = b"") -> tuple[int, bytes]:
    try:
        result = subprocess.run(["openssl", *args], input=data, capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return 127, b""
    return result.returncode, result.stdout


# ── one certificate ──────────────────────────────────────────────────────────────────────────────────────────────

def info(der: bytes) -> dict:
    """subject, issuer, self_signed, issuers (AIA CA Issuers URLs), names (DNS names, then the CN)."""
    code, out = openssl(["x509", "-inform", "DER", "-noout", "-nameopt", "RFC2253", "-subject", "-issuer",
                         "-ext", "subjectAltName,authorityInfoAccess"], der)
    if code != 0:
        return {}
    text = out.decode(errors="replace")
    subject = re.search(r"^subject=\s*(.*)$", text, re.M)
    issuer = re.search(r"^issuer=\s*(.*)$", text, re.M)
    subject = subject.group(1).strip() if subject else ""
    issuer = issuer.group(1).strip() if issuer else ""
    names = re.findall(r"DNS:([^,\s]+)", text)
    cn = re.search(r"(?:^|,)CN=([^,]+)", subject)
    if cn and "." in cn.group(1) and cn.group(1) not in names:
        names.append(cn.group(1))
    return {"subject": subject, "issuer": issuer, "self_signed": bool(subject) and subject == issuer,
            "issuers": re.findall(r"CA Issuers - URI:(\S+)", text), "names": names}


def to_pem(der: bytes) -> bytes:
    code, out = openssl(["x509", "-inform", "DER", "-outform", "PEM"], der)
    return out if code == 0 else b""


def pem_to_ders(pem: bytes) -> list[bytes]:
    out = []
    for block in re.findall(rb"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", pem, re.S):
        code, der = openssl(["x509", "-outform", "DER"], block + b"\n")
        if code == 0 and der:
            out.append(der)
    return out


def parse_download(data: bytes) -> list[bytes]:
    """A CA Issuers download: one DER certificate, a PKCS#7 bundle (.p7c) or PEM."""
    if b"-----BEGIN CERTIFICATE-----" in data:
        return pem_to_ders(data)
    if info(data):
        return [data]
    for form in ("DER", "PEM"):
        code, pem = openssl(["pkcs7", "-inform", form, "-print_certs"], data)
        if code == 0 and pem:
            return pem_to_ders(pem)
    return []


def fetch(url: str) -> bytes:
    if not url.lower().startswith(("http://", "https://")):
        return b""
    request = urllib.request.Request(url, headers={"User-Agent": f"nmx/{__version__}"})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
            return response.read(MAX_CERT)
    except (OSError, ValueError):
        return b""


# ── a network's chain ────────────────────────────────────────────────────────────────────────────────────────────

def save_chain(ssid: str, chain: dict[int, bytes], directory: Path | None = None) -> Path | None:
    """Keep what the server showed (depth -> DER). Only a chain with the server's own certificate is kept."""
    if 0 not in chain:
        return None
    base = (directory or CHAINS) / _slug(ssid)
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    for old in base.glob("depth-*.der"):
        old.unlink()
    for depth, der in sorted(chain.items()):
        (base / f"depth-{depth}.der").write_bytes(der)
    (base / "network.json").write_text(json.dumps({"ssid": ssid}))
    return base


def load_chain(ssid: str, directory: Path | None = None) -> list[bytes]:
    base = (directory or CHAINS) / _slug(ssid)
    files = sorted(base.glob("depth-*.der"), key=lambda p: int(p.stem.split("-")[1]))
    return [p.read_bytes() for p in files]


def complete(chain: list[bytes], fetcher=fetch) -> list[bytes]:
    """The chain with its missing issuers fetched (AIA), up to a self-signed root or MAX_HOPS."""
    chain = list(chain)
    for _ in range(MAX_HOPS):
        top = info(chain[-1]) if chain else {}
        if not top or top["self_signed"]:
            break
        found = None
        for url in top["issuers"]:
            for der in parse_download(fetcher(url)):
                if info(der).get("subject") == top["issuer"]:
                    found = der
                    break
            if found:
                break
        if found is None or found in chain:
            break
        chain.append(found)
    return chain


def trusted_by_system(chain: list[bytes], bundle: str = SYSTEM_CA_BUNDLE) -> bool:
    if not chain or not Path(bundle).exists():
        return False
    with tempfile.TemporaryDirectory() as tmp:
        leaf = Path(tmp, "leaf.pem")
        rest = Path(tmp, "rest.pem")
        leaf.write_bytes(to_pem(chain[0]))
        rest.write_bytes(b"".join(to_pem(der) for der in chain[1:]))
        args = ["verify", "-purpose", "any", "-CAfile", bundle]
        if len(chain) > 1:
            args += ["-untrusted", str(rest)]
        code, _ = openssl([*args, str(leaf)])
        return code == 0


def domain_of(names: list[str]) -> str:
    """The server's name, for domain-suffix-match: a wildcard's base, the shortest name first."""
    clean = sorted({n.lstrip("*.").lower() for n in names if "." in n}, key=len)
    return clean[0] if clean else ""


def org_domain(name: str) -> str:
    """'radius1.it.uni.example' -> 'uni.example' (the last two labels; three for a two-letter second level such as
    ac.uk or co.jp)."""
    parts = name.lower().strip(".").split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and len(parts[-2]) <= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def resolve(chain: list[bytes], ssid: str, fetcher=fetch, bundle: str = SYSTEM_CA_BUNDLE,
            ca_dir: Path | None = None) -> dict | None:
    """What a profile should trust for this server: {"ca-cert": "auto" | file path, "domain": ..., "root": subject}.
    None when no CA was found (the pin stays)."""
    if not chain:
        return None
    leaf = info(chain[0])
    if not leaf:
        return None
    domain = domain_of(leaf.get("names", []))
    if trusted_by_system(chain, bundle):
        root = info(chain[-1]).get("subject", "") if len(chain) > 1 else leaf.get("issuer", "")
        return {"ca-cert": "auto", "domain": domain, "root": root}
    full = complete(chain, fetcher)
    if trusted_by_system(full, bundle):
        return {"ca-cert": "auto", "domain": domain, "root": info(full[-1]).get("subject", "")}
    top = info(full[-1])
    if len(full) < 2 or not top.get("self_signed"):
        return None                              # no root found: a self-signed server stays pinned
    directory = ca_dir or CA_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_slug(ssid)}.pem"
    path.write_bytes(to_pem(full[-1]))
    path.chmod(0o644)
    return {"ca-cert": str(path), "domain": domain, "root": top["subject"]}
