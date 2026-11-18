"""The Wi-Fi DNS-blocker bypass (off by default: `nmxcli dns-bypass on`).

Many school, office and hotel networks block sites by answering DNS for them with nothing, or with a block page.
With the bypass on, a Wi-Fi link's names are looked up through public resolvers over DNS-over-TLS (port 853,
encrypted and checked against the resolver's certificate, so the network can neither read nor rewrite the answers)
instead of through the network's own DNS server.

It only ever applies once the network is fully online. A captive portal's sign-in page lives on the network's own
DNS, so while a portal wants a sign-in (and on every new connection, until the check says "full") the network's
DNS is used as normal. If the network blocks DNS-over-TLS too, plain DNS to the same public resolvers is tried
(which still gets past a blocklist on the network's own DNS server); if that does not answer either, the network's
DNS is put back, so the bypass never leaves a link without working DNS.

All of it is runtime state in systemd-resolved (per link, via resolvectl): nothing is written to disk, and a
reconnection starts from the network's own settings again.
"""

from __future__ import annotations

import threading

from . import net

# (address, the name its certificate is checked against)
RESOLVERS = [
    ("1.1.1.1", "cloudflare-dns.com"), ("9.9.9.9", "dns.quad9.net"), ("1.0.0.1", "cloudflare-dns.com"),
    ("149.112.112.112", "dns.quad9.net"), ("2606:4700:4700::1111", "cloudflare-dns.com"), ("2620:fe::fe", "dns.quad9.net"),
]
TEST_NAMES = ("example.com", "nmcheck.gnome.org")


def _servers(dot: bool) -> list[str]:
    return [f"{addr}#{name}" if dot else addr for addr, name in RESOLVERS]


def _words(text: str) -> list[str]:
    """`resolvectl dns wlan0` prints 'Link 3 (wlan0): 192.0.2.1 2001:db8::1'."""
    return text.split(":", 1)[1].split() if ":" in text else []


class Bypass:
    def __init__(self, run=net.run):
        self.run = run
        self.lock = threading.Lock()
        self.applied: dict[str, dict] = {}       # iface -> {"mode": "dot" | "plain", "dns": [...], "domains": [...]}
        self.refused: set[str] = set()           # links where neither worked (until they reconnect)

    def works(self, iface: str) -> bool:
        self.run(["resolvectl", "flush-caches"], timeout=5)
        for name in TEST_NAMES:
            result = self.run(["resolvectl", "query", "--cache=no", "--legend=no", "-i", iface, name], timeout=12)
            if result.returncode == 0:
                return True
        return False

    def apply(self, iface: str) -> str:
        """Use the public resolvers on this link. Returns the mode now in use ('dot', 'plain' or '' if neither
        works here)."""
        with self.lock:
            if iface in self.applied:
                return self.applied[iface]["mode"]
            if iface in self.refused:
                return ""
            before = {
                "dns": [w for w in _words(self.run(["resolvectl", "dns", iface], timeout=5).stdout)],
                "domains": [w for w in _words(self.run(["resolvectl", "domain", iface], timeout=5).stdout)
                            if w != "~."],
            }
            for mode in ("dot", "plain"):
                self.run(["resolvectl", "dns", iface, *_servers(mode == "dot")], timeout=5)
                self.run(["resolvectl", "dnsovertls", iface, "yes" if mode == "dot" else "no"], timeout=5)
                # "~." routes every name to this link's servers; the network's own search domains stay.
                self.run(["resolvectl", "domain", iface, "~.", *before["domains"]], timeout=5)
                self.run(["resolvectl", "default-route", iface, "yes"], timeout=5)
                if self.works(iface):
                    self.applied[iface] = {"mode": mode, **before}
                    return mode
            self._restore(iface, before)
            self.refused.add(iface)
            return ""

    def _restore(self, iface: str, before: dict) -> None:
        self.run(["resolvectl", "revert", iface], timeout=5)
        if before.get("dns"):
            self.run(["resolvectl", "dns", iface, *before["dns"]], timeout=5)
        if before.get("domains"):
            self.run(["resolvectl", "domain", iface, *before["domains"]], timeout=5)
        self.run(["resolvectl", "flush-caches"], timeout=5)

    def revert(self, iface: str) -> bool:
        """Back to the network's own DNS (a portal to sign in to, or the bypass turned off)."""
        with self.lock:
            before = self.applied.pop(iface, None)
            if before is None:
                return False
            self._restore(iface, before)
            return True

    def revert_all(self) -> list[str]:
        return [iface for iface in list(self.applied) if self.revert(iface)]

    def forget(self, iface: str) -> None:
        """The link was configured again (a new connection): resolved has the network's settings once more."""
        with self.lock:
            self.applied.pop(iface, None)
            self.refused.discard(iface)

    def status(self) -> dict[str, str]:
        with self.lock:
            out = {iface: info["mode"] for iface, info in self.applied.items()}
            out.update({iface: "blocked" for iface in self.refused})
            return out
