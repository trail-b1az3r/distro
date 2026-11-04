"""Captive portals: is this network asking us to sign in, and where?

Three sources, best first:

1. RFC 8910 / RFC 8908. The network says it has a portal in DHCP (option 114) or a router advertisement;
   systemd-networkd keeps the URI it was given, and that URI is a small JSON API that answers
   {"captive": true, "user-portal-url": "https://..."} until we have signed in.
2. The probe. We fetch a known plain-HTTP page without following redirects. The real page means we are online;
   a redirect (or HTTP 511) is the portal, and its Location is the sign-in page.
3. A page in place of the probe. Some portals answer 200 with their own page; we read a <meta refresh>,
   a script redirect or the first form/link out of it, and fall back to the probe URL, which a browser
   will be redirected from anyway.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from . import __version__, net

CHECK_URL = "http://nmcheck.gnome.org/check_network_status.txt"
CHECK_TEXT = "NetworkManager is online"
TIMEOUT = 6

_META = re.compile(r"""<meta[^>]+http-equiv\s*=\s*["']?refresh["']?[^>]*content\s*=\s*["'][^"']*?url\s*=\s*([^"'>\s]+)""", re.I)
_META_REVERSED = re.compile(r"""<meta[^>]+content\s*=\s*["'][^"']*?url\s*=\s*([^"'>\s]+)[^>]*http-equiv\s*=\s*["']?refresh""", re.I)
_SCRIPT = re.compile(r"""(?:window\.|document\.|top\.)?location(?:\.href)?\s*(?:=|\.replace\(|\.assign\()\s*["']([^"']+)["']""", re.I)
_FORM = re.compile(r"""<form[^>]+action\s*=\s*["'](https?://[^"']+)["']""", re.I)
_LINK = re.compile(r"""<a[^>]+href\s*=\s*["'](https?://[^"']+)["']""", re.I)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirect)


def url_in_page(body: str, base: str) -> str:
    """The sign-in page a portal's placeholder page points at, or ''."""
    for pattern in (_META, _META_REVERSED, _SCRIPT, _FORM, _LINK):
        match = pattern.search(body)
        if match:
            target = match.group(1).strip().strip(";")
            if target and not target.lower().startswith(("javascript:", "#", "data:")):
                return urllib.parse.urljoin(base, target)
    return ""


def probe(url: str = CHECK_URL, opener: urllib.request.OpenerDirector | None = None) -> tuple[str, str]:
    """('full' | 'portal' | 'limited', sign-in URL or '')."""
    opener = opener or _opener()
    request = urllib.request.Request(url, headers={"User-Agent": f"nmx/{__version__}", "Cache-Control": "no-cache"})
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            body = response.read(16384).decode(errors="replace")
            if body.strip().startswith(CHECK_TEXT) and response.geturl() == url:
                return "full", ""
            return "portal", url_in_page(body, response.geturl()) or url
    except urllib.error.HTTPError as error:
        if 300 <= error.code < 400 or error.code == 511:
            location = error.headers.get("Location", "") if error.headers else ""
            if location:
                return "portal", urllib.parse.urljoin(url, location)
            try:
                body = error.read(16384).decode(errors="replace")
            except OSError:
                body = ""
            return "portal", url_in_page(body, url) or url
        return "limited", ""
    except (OSError, ValueError):
        return "limited", ""


def api(uri: str, opener: urllib.request.OpenerDirector | None = None) -> tuple[bool | None, str]:
    """Ask an RFC 8908 captive-portal API. (captive?, user-portal-url); captive is None if it did not answer."""
    if not uri.lower().startswith("https://"):
        return None, ""                              # RFC 8908 requires TLS; anything else is not to be trusted
    opener = opener or urllib.request.build_opener()
    request = urllib.request.Request(uri, headers={"Accept": "application/captive+json",
                                                   "User-Agent": f"nmx/{__version__}"})
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            data = json.loads(response.read(65536).decode(errors="replace"))
    except (OSError, ValueError):
        return None, ""
    if not isinstance(data, dict) or not isinstance(data.get("captive"), bool):
        return None, ""
    portal = data.get("user-portal-url") if isinstance(data.get("user-portal-url"), str) else ""
    return data["captive"], portal


def advertised(iface: str) -> str:
    """The captive-portal URI networkd got from DHCP or a router advertisement for this link, or ''."""
    result = net.run(["networkctl", "status", iface, "--json=short"], timeout=5)
    if result.returncode != 0 or not result.stdout.strip():
        return ""
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return ""
    return find_uri(data)


def find_uri(data) -> str:
    """networkd puts the URI under CaptivePortal; search for it so changes in the JSON layout do not lose it."""
    if isinstance(data, dict):
        value = data.get("CaptivePortal")
        if isinstance(value, str) and value:
            return value
        values = list(data.values())
    elif isinstance(data, list):
        values = data
    else:
        return ""
    for value in values:
        found = find_uri(value)
        if found:
            return found
    return ""


def check(ifaces: list[str], probe_url: str = CHECK_URL) -> tuple[str, str, str]:
    """(connectivity, sign-in URL, device) for the connected interfaces."""
    said_free = False
    for iface in ifaces:
        uri = advertised(iface)
        if not uri:
            continue
        captive, portal = api(uri)
        if captive:
            return "portal", portal or probe(probe_url)[1] or probe_url, iface
        if captive is False:
            said_free = True
    state, url = probe(probe_url)
    if state == "portal" and said_free:
        # The network's own API says we are signed in; a transparent proxy rewriting the probe is not a portal.
        return "full", "", ""
    return state, url, ifaces[0] if state == "portal" and ifaces else ""
