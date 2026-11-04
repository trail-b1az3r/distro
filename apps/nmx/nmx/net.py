"""Links, addresses, rfkill and DHCP: the parts of the system nmxd drives besides wpa_supplicant.

Addressing (DHCP, IPv6 router advertisements, static addresses) is systemd-networkd's job: nmxd writes one runtime
.network file per device it manages and asks networkd to apply it. DNS goes through systemd-resolved.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

SYS_NET = Path(os.environ.get("NMX_SYS_NET", "/sys/class/net"))
NETWORKD = Path(os.environ.get("NMX_NETWORKD", "/run/systemd/network"))
NM_CONF = Path(os.environ.get("NMX_NM_CONF", "/etc/NetworkManager/conf.d/90-nmx.conf"))


def run(cmd: list[str], timeout: float = 15) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(cmd, 127, "", str(error))


def read(path: Path, default: str = "") -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return default


# ── devices ──────────────────────────────────────────────────────────────────────────────────────────────────────

def kind(iface: str, root: Path = SYS_NET) -> str:
    """wifi, ethernet, or '' for what nmx leaves alone (loopback, bridges, tunnels, VMs' and containers' links, and a
    Wi-Fi card's access-point and Wi-Fi Direct interfaces)."""
    base = root / iface
    if iface == "lo" or not (base / "device").exists():
        return ""
    if (base / "wireless").exists() or (base / "phy80211").exists():
        return "wifi" if wifi_station(iface, root) else ""
    if read(base / "type") == "1" and not (base / "bridge").exists() and not (base / "bonding").exists():
        return "ethernet"
    return ""


# A Wi-Fi card can show more than one interface: Marvell's mwifiex (Surface Pro 3 to 7, Surface Go, Surface Book)
# makes mlan0 for connecting, uap0 for being an access point and wfd0 for Wi-Fi Direct, all on one radio. A
# supplicant on each fought over that radio (scans failed busy, connections dropped), and nmx could pick uap0 or wfd0
# to connect with. Only the station (client) interface is nmx's.
VIRTUAL_WIFI = re.compile(r"^(uap|wfd|p2p|ap|mon)\d+$|^p2p-")


_WIFI_TYPES: dict[tuple[str, str], str] = {}


def wifi_type(iface: str) -> str:
    """nl80211's interface type ("managed", "AP", "P2P-client", "monitor"...), from `iw`, or '' when it cannot say.
    Asked once per interface (its ifindex changes when the driver makes it again), since nmxd looks every tick."""
    if not shutil.which("iw"):
        return ""
    key = (iface, read(SYS_NET / iface / "ifindex"))
    if key not in _WIFI_TYPES:
        match = re.search(r"^\s*type\s+(\S+)", run(["iw", "dev", iface, "info"], timeout=5).stdout, re.M)
        if not match:
            return ""                            # not cached: ask again next time
        _WIFI_TYPES[key] = match.group(1)
    return _WIFI_TYPES[key]


def power_save_off(iface: str) -> None:
    """Marvell mwifiex (the Surface's card) drops connections and stalls with Wi-Fi power saving on; linux-surface
    advises turning it off, as NetworkManager's wifi.powersave = 2 does there."""
    if shutil.which("iw"):
        run(["iw", "dev", iface, "set", "power_save", "off"], timeout=5)


def wifi_station(iface: str, root: Path = SYS_NET) -> bool:
    """Whether a Wi-Fi interface is one to connect with: `iw` says managed, or (without iw, or on a test's stand-in
    sysfs) its name is not one of the access-point, Wi-Fi Direct or monitor interfaces' names."""
    found = wifi_type(iface) if root == SYS_NET else ""
    if found:
        return found in ("managed", "station")
    return not VIRTUAL_WIFI.match(iface)


def phy(iface: str, root: Path = SYS_NET) -> str:
    """The radio (phy0...) a Wi-Fi interface belongs to, or ''."""
    return read(root / iface / "phy80211" / "name")


def devices(root: Path = SYS_NET) -> dict[str, str]:
    out = {}
    radios: set[str] = set()
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            k = kind(entry.name, root)
            if k == "wifi":
                radio = phy(entry.name, root)
                if radio and radio in radios:
                    continue                     # one interface per radio: two supplicants on one radio fight
                radios.add(radio or entry.name)
            if k:
                out[entry.name] = k
    return out


def driver(iface: str, root: Path = SYS_NET) -> str:
    try:
        return os.path.basename(os.readlink(root / iface / "device" / "driver" / "module"))
    except OSError:
        try:
            return os.path.basename(os.readlink(root / iface / "device" / "driver"))
        except OSError:
            return ""


def hwaddr(iface: str, root: Path = SYS_NET) -> str:
    return read(root / iface / "address").upper()


def mtu(iface: str, root: Path = SYS_NET) -> str:
    return read(root / iface / "mtu", "0")


def carrier(iface: str, root: Path = SYS_NET) -> bool:
    return read(root / iface / "carrier") == "1"


def link_up(iface: str) -> None:
    run(["ip", "link", "set", "dev", iface, "up"])


def link_is_up(iface: str, root: Path = SYS_NET) -> bool:
    try:
        return bool(int(read(root / iface / "flags", "0"), 16) & 0x1)
    except ValueError:
        return False


def addresses(iface: str) -> dict:
    """IPv4/IPv6 addresses, gateways and DNS servers, for `device show`."""
    info: dict = {"ip4": [], "ip6": [], "gw4": "", "gw6": "", "dns4": [], "dns6": [], "domains": [], "routes4": []}
    out = run(["ip", "-j", "addr", "show", "dev", iface]).stdout
    try:
        for link in json.loads(out or "[]"):
            for addr in link.get("addr_info", []):
                text = f"{addr.get('local')}/{addr.get('prefixlen')}"
                if addr.get("family") == "inet":
                    info["ip4"].append(text)
                elif addr.get("family") == "inet6" and addr.get("scope") != "link":
                    info["ip6"].append(text)
    except ValueError:
        pass
    for family, key in (("-4", "gw4"), ("-6", "gw6")):
        try:
            for route in json.loads(run(["ip", "-j", family, "route", "show", "dev", iface]).stdout or "[]"):
                if route.get("dst") == "default" and route.get("gateway") and not info[key]:
                    info[key] = route["gateway"]
                elif family == "-4" and route.get("dst") != "default":
                    info["routes4"].append(f"dst = {route.get('dst')}, nh = {route.get('gateway', '0.0.0.0')}, "
                                           f"mt = {route.get('metric', 0)}")
        except ValueError:
            pass
    if shutil.which("resolvectl"):
        for line in run(["resolvectl", "dns", iface]).stdout.split(":", 1)[-1].split():
            (info["dns6"] if ":" in line else info["dns4"]).append(line)
        info["domains"] = run(["resolvectl", "domain", iface]).stdout.split(":", 1)[-1].split()
    return info


# ── addressing through systemd-networkd ──────────────────────────────────────────────────────────────────────────

def network_file(iface: str, wifi: bool, ipv4: dict, ipv6: dict) -> str:
    metric = 600 if wifi else 100
    lines = ["# Written by nmxd; it is rewritten on every connection.", "[Match]", f"Name={iface}", "",
             "[Link]", "RequiredForOnline=no", "", "[Network]"]
    method4 = (ipv4.get("method") or "auto").lower()
    method6 = (ipv6.get("method") or "auto").lower()
    dhcp = []
    if method4 == "auto":
        dhcp.append("ipv4")
    if method6 in ("auto", "dhcp"):
        dhcp.append("ipv6")
    lines.append("DHCP=" + ("yes" if len(dhcp) == 2 else dhcp[0] if dhcp else "no"))
    lines.append("IPv6AcceptRA=" + ("yes" if method6 in ("auto", "dhcp") else "no"))
    lines.append("LinkLocalAddressing=" + ("ipv6" if method6 != "disabled" else "no"))
    lines.append("IPv6PrivacyExtensions=prefer-public")
    for addr in _split(ipv4.get("addresses") or ipv4.get("address1", "").split(",")[0]):
        lines.append(f"Address={addr}")
    gateway = ipv4.get("gateway") or (ipv4.get("address1", "").split(",")[1] if "," in ipv4.get("address1", "") else "")
    if method4 == "manual" and gateway:
        lines.append(f"Gateway={gateway}")
    for addr in _split(ipv6.get("addresses", "")):
        lines.append(f"Address={addr}")
    if ipv6.get("gateway"):
        lines.append(f"Gateway={ipv6['gateway']}")
    for dns in _split(ipv4.get("dns", "")) + _split(ipv6.get("dns", "")):
        lines.append(f"DNS={dns}")
    if ipv4.get("dns-search"):
        lines.append("Domains=" + " ".join(_split(ipv4["dns-search"])))
    lines += ["", "[DHCPv4]", f"RouteMetric={metric}", "UseDomains=yes",
              "UseDNS=" + ("no" if (ipv4.get("ignore-auto-dns") or "").lower() in ("yes", "true") else "yes"),
              "", "[IPv6AcceptRA]", f"RouteMetric={metric}", ""]
    return "\n".join(lines)


def _split(text: str) -> list[str]:
    return [p for p in text.replace(";", ",").replace(" ", ",").split(",") if p]


def configure(iface: str, wifi: bool, ipv4: dict, ipv6: dict, directory: Path = NETWORKD) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"10-nmx-{iface}.network"
    text = network_file(iface, wifi, ipv4, ipv6)
    if read(path) != text.strip():
        path.write_text(text)
        run(["networkctl", "reload"])
    run(["networkctl", "reconfigure", iface])


def release(iface: str, directory: Path = NETWORKD) -> None:
    path = directory / f"10-nmx-{iface}.network"
    if path.exists():
        path.unlink()
        run(["networkctl", "reload"])


def ensure_services() -> None:
    """networkd and resolved do the addressing and the DNS; start them if they are not running."""
    for unit in ("systemd-networkd.service", "systemd-resolved.service"):
        if run(["systemctl", "is-active", "--quiet", unit]).returncode != 0:
            run(["systemctl", "start", unit], timeout=30)


# ── rfkill ───────────────────────────────────────────────────────────────────────────────────────────────────────

def rfkill_state() -> tuple[bool, bool]:
    """(hardware enabled, software enabled) for Wi-Fi."""
    out = run(["rfkill", "-J", "-o", "TYPE,SOFT,HARD"]).stdout
    hw, sw = True, True
    try:
        for dev in json.loads(out or "{}").get("rfkilldevices", []):
            if dev.get("type") == "wlan":
                hw = hw and dev.get("hard") == "unblocked"
                sw = sw and dev.get("soft") == "unblocked"
    except ValueError:
        pass
    return hw, sw


def set_rfkill(enabled: bool) -> None:
    run(["rfkill", "unblock" if enabled else "block", "wlan"])


# ── NetworkManager, when it is installed too ─────────────────────────────────────────────────────────────────────

def tell_networkmanager(managed_by_nmx: list[str], path: Path = NM_CONF) -> None:
    """NetworkManager leaves nmx's devices alone (and gets one back the moment nmx is told to unmanage it)."""
    text = ("# Written by nmxd: these devices are managed by nmx. `sudo nmxcli device unmanage DEV` hands one back.\n"
            "[keyfile]\nunmanaged-devices=" + ";".join(f"interface-name:{i}" for i in managed_by_nmx) + "\n")
    if not managed_by_nmx:
        if path.exists():
            path.unlink()
    elif read(path) != text.strip():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        except OSError:
            return
    else:
        return
    if shutil.which("nmcli") and run(["systemctl", "is-active", "--quiet", "NetworkManager.service"]).returncode == 0:
        run(["nmcli", "general", "reload", "conf"])
        for iface in managed_by_nmx:
            run(["nmcli", "device", "set", iface, "managed", "no"])


def give_back_to_networkmanager(iface: str) -> None:
    if shutil.which("nmcli") and run(["systemctl", "is-active", "--quiet", "NetworkManager.service"]).returncode == 0:
        run(["nmcli", "device", "set", iface, "managed", "yes"])


RESOLV = Path(os.environ.get("NMX_RESOLV", "/etc/resolv.conf"))
RESOLVED_STUB = "/run/systemd/resolve/stub-resolv.conf"


def take_over(marker: Path, resolv: Path = RESOLV) -> list[str]:
    """The first start after `systemctl enable --now nmx`: DNS through systemd-resolved (the old resolv.conf kept as
    resolv.conf.before-nmx), systemd-networkd and -resolved on at boot, and NetworkManager off, since a
    NetworkManager that manages nothing tells apps the computer is offline. Once: after `sudo nmxcli device
    unmanage` hands things back, NetworkManager is never turned off again. Returns what it did."""
    if marker.exists():
        return []
    done = []
    try:
        if not (resolv.is_symlink() and os.readlink(resolv) == RESOLVED_STUB):
            if resolv.exists() and not resolv.is_symlink():
                shutil.copy2(resolv, resolv.with_name(resolv.name + ".before-nmx"))
            tmp = resolv.with_name(resolv.name + ".nmx-tmp")
            if tmp.is_symlink() or tmp.exists():
                tmp.unlink()
            tmp.symlink_to(RESOLVED_STUB)
            os.replace(tmp, resolv)
            done.append("DNS now goes through systemd-resolved")
    except OSError as error:
        done.append(f"could not point {resolv} at systemd-resolved: {error}")
    run(["systemctl", "enable", "systemd-networkd.service", "systemd-resolved.service"], timeout=30)
    if run(["systemctl", "is-enabled", "--quiet", "NetworkManager.service"]).returncode == 0 or \
            run(["systemctl", "is-active", "--quiet", "NetworkManager.service"]).returncode == 0:
        run(["systemctl", "disable", "--now", "NetworkManager.service"], timeout=60)
        done.append("NetworkManager turned off (its saved connections were imported)")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    return done


def reload_driver(module: str) -> bool:
    """The last resort after a suspend that left the card dead (Marvell mwifiex, some Realtek and Intel cards)."""
    if not module:
        return False
    run(["modprobe", "-r", module], timeout=30)
    ok = run(["modprobe", module], timeout=30).returncode == 0
    run(["udevadm", "settle", "--timeout=10"], timeout=15)
    return ok


def hostname() -> str:
    return read(Path("/etc/hostname")) or os.uname().nodename


def set_hostname(name: str) -> bool:
    return run(["hostnamectl", "set-hostname", name]).returncode == 0
