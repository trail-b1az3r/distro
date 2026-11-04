"""nmxd: keeps every Wi-Fi and Ethernet device connected, until `sudo nmxcli device unmanage` says otherwise.

It runs as root (nmx.service, which refuses `systemctl stop`). Clients talk to it over /run/nmx/nmx.sock, one JSON
request per line; anyone may read, members of wheel or network may connect and change things, and only root may
take a device out of nmx's hands.

What it does on its own:
  * brings managed devices up, starts a wpa_supplicant for each Wi-Fi card, and restarts it if it dies;
  * joins the best saved network in range (priority, then signal), backing off from ones that keep failing;
  * after a suspend (the system-sleep hook says so, and a jump of the boot clock past the monotonic one gives it
    away anyway) waits for the card, restarts its supplicant and reconnects; a card that stays dead gets its driver
    reloaded; a card that stops scanning is restarted the same way;
  * for enterprise networks fills in an anonymous outer identity, validates the server against the system
    certificates, pins the server's certificate on first use when the network has its own CA, remembers the
    server's domain, and falls back through PEAP/MSCHAPv2, TTLS/PAP, TTLS/MSCHAPv2 and PEAP/GTC when the first
    method is refused;
  * tells NetworkManager, when it is installed too, to keep its hands off nmx's devices.
"""

from __future__ import annotations

import grp
import json
import os
import pwd
import shutil
import signal
import socket
import socketserver
import struct
import sys
import threading
import time
import traceback
from pathlib import Path

from . import __version__, net, portal, profiles, security, wpa

RUN = wpa.RUN
SOCKET = RUN / "nmx.sock"
STATE = Path(os.environ.get("NMX_STATE", "/var/lib/nmx/state.json"))
CHECK_URL = os.environ.get("NMX_CHECK_URL", portal.CHECK_URL)
RECHECK = {"portal": 15, "limited": 60}                  # seconds between checks; 300 otherwise
WRITER_GROUPS = ("wheel", "network")
BACKOFF = [10, 30, 60, 120, 300]


def networkmanager_installed() -> bool:
    return bool(shutil.which("NetworkManager")) or Path("/usr/bin/NetworkManager").exists()


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


class Failure(Exception):
    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code = code
        self.extra = extra


class Device:
    def __init__(self, iface: str, kind: str):
        self.iface = iface
        self.kind = kind
        self.driver = net.driver(iface)
        self.managed = True
        self.present = True
        self.state = "disconnected"
        self.reason = ""
        self.profile: profiles.Profile | None = None
        self.pending_new = False             # the active profile is not saved yet (a first connection)
        self.supplicant: wpa.Supplicant | None = None
        self.scan: list[dict] = []
        self.scan_at = 0.0
        self.scan_requested = 0.0
        self.autoconnect_blocked = False     # `device disconnect`: no autoconnect until asked again
        self.deadline = 0.0
        self.waiters: list[dict] = []
        self.peer_cert: dict = {}
        self.cert_error = False
        self.retried_cert = False
        self.tried_methods: list[str] = []
        self.restarts = 0
        self.start_failures = 0
        self.next_start = 0.0                # after a failed start: not again before this
        self.last_driver_reload = 0.0
        self.event_thread: threading.Thread | None = None
        self.lock = threading.RLock()


class Daemon:
    def __init__(self):
        self.store = profiles.Store()
        self.devices: dict[str, Device] = {}
        self.lock = threading.RLock()
        self.subscribers: list[socket.socket] = []
        self.failures: dict[str, tuple[int, float]] = {}     # profile uuid -> (count, retry after)
        self.needs_secrets: set[str] = set()                  # profile uuids whose saved secrets were refused
        self.connectivity = "unknown"
        self.portal_url = ""
        self.portal_device = ""
        self.checked_at = 0.0
        self.checking = threading.Lock()
        self.state = {"wifi": True, "networking": True, "unmanaged": []}
        self.load_state()
        self.boot_offset = self.clock_offset()
        self.stopping = False
        self.last_resume = -100.0

    # ── persistent state ──
    def load_state(self) -> None:
        try:
            self.state.update(json.loads(STATE.read_text()))
        except (OSError, ValueError):
            pass

    def save_state(self) -> None:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2))
        os.replace(tmp, STATE)

    # ── events to `nmxcli monitor` and Halcyon ──
    def emit(self, event: str, **fields) -> None:
        line = (json.dumps({"event": event, **fields}) + "\n").encode()
        with self.lock:
            for sub in list(self.subscribers):
                try:
                    sub.sendall(line)
                except OSError:
                    self.subscribers.remove(sub)

    def set_state(self, dev: Device, state: str, reason: str = "") -> None:
        if dev.state == state and dev.reason == reason:
            return
        was_connected = dev.state == "connected"
        dev.state, dev.reason = state, reason
        if was_connected and state != "connected" and self.connectivity not in ("unknown", "none"):
            self.check_connectivity_soon()
        name = dev.profile.id if dev.profile else ""
        self.emit("device", device=dev.iface, state=state, reason=reason, connection=name)

    # ── devices ──
    def reconcile(self) -> None:
        found = net.devices()
        with self.lock:
            for iface, kind in found.items():
                dev = self.devices.get(iface)
                if dev is None:
                    dev = self.devices[iface] = Device(iface, kind)
                    dev.managed = iface not in self.state["unmanaged"]
                    self.emit("device-added", device=iface, type=kind)
                elif not dev.present:
                    dev.present = True
                    dev.driver = net.driver(iface) or dev.driver
                    self.emit("device-added", device=iface, type=kind)
                if dev.managed:
                    self.take(dev)
            for iface, dev in self.devices.items():
                if iface not in found and dev.present:
                    dev.present = False
                    self.stop_supplicant(dev)
                    self.set_state(dev, "unavailable", "device gone")
                    self.emit("device-removed", device=iface)
            net.tell_networkmanager(sorted(i for i, d in self.devices.items() if d.managed and d.present))

    def take(self, dev: Device) -> None:
        """Hold a managed device: link up, supplicant running, addressing configured."""
        if not net.link_is_up(dev.iface) and not (dev.kind == "wifi" and not self.state["wifi"]):
            net.link_up(dev.iface)
        if dev.kind == "wifi":
            if not self.state["wifi"]:
                if dev.supplicant:
                    self.stop_supplicant(dev)
                self.set_state(dev, "unavailable", "radio off")
                return
            if (dev.supplicant is None or not dev.supplicant.alive()) and time.monotonic() >= dev.next_start:
                self.start_supplicant(dev)
        elif dev.kind == "ethernet":
            if not self.state["networking"]:
                return
            if net.carrier(dev.iface):
                if dev.state in ("disconnected", "unavailable") and not dev.autoconnect_blocked:
                    self.activate_ethernet(dev)
            elif dev.state not in ("unavailable",):
                dev.profile = None
                self.set_state(dev, "unavailable", "cable unplugged")

    def start_supplicant(self, dev: Device) -> None:
        try:
            if dev.supplicant:
                dev.supplicant.stop()
            dev.supplicant = wpa.Supplicant(dev.iface)
            dev.supplicant.start()
            if self.needs_power_save_off(dev):
                net.power_save_off(dev.iface)
            dev.restarts += 1
            dev.start_failures = 0
            self.set_state(dev, "disconnected")
            dev.event_thread = threading.Thread(target=self.event_loop, args=(dev, dev.supplicant), daemon=True)
            dev.event_thread.start()
            self.request_scan(dev)
        except (wpa.WpaError, OSError) as error:
            # Again in 2, 4, 8... up to 60 s: a card that is still waking up, or wpa_supplicant missing.
            dev.start_failures += 1
            dev.next_start = time.monotonic() + min(60, 2 ** dev.start_failures)
            if dev.start_failures <= 3 or dev.start_failures % 10 == 0:
                log(f"{dev.iface}: {error}")
            dev.supplicant = None
            self.set_state(dev, "unavailable", str(error))

    @staticmethod
    def needs_power_save_off(dev: Device) -> bool:
        """The Surface's Marvell card (mwifiex) is only steady with Wi-Fi power saving off."""
        return dev.kind == "wifi" and (dev.driver or net.driver(dev.iface)).startswith("mwifiex")

    def stop_supplicant(self, dev: Device) -> None:
        if dev.supplicant:
            sup, dev.supplicant = dev.supplicant, None
            try:
                sup.stop()
            except OSError:
                pass
        net.release(dev.iface)

    def request_scan(self, dev: Device) -> None:
        if dev.supplicant and time.monotonic() - dev.scan_requested > 4:
            dev.scan_requested = time.monotonic()
            try:
                dev.supplicant.scan()
            except (wpa.WpaError, OSError):
                pass

    # ── wpa_supplicant's events ──
    def event_loop(self, dev: Device, sup: wpa.Supplicant) -> None:
        while not self.stopping and dev.supplicant is sup and sup.events is not None:
            try:
                line = sup.events.recv_event(1.0)
            except OSError:
                break
            if not line:
                continue
            try:
                with dev.lock:
                    self.on_event(dev, line)
            except Exception:  # noqa: BLE001 - one bad event must not end the device's loop
                traceback.print_exc()

    def on_event(self, dev: Device, line: str) -> None:
        name, f = wpa.parse_event(line)
        if name == "CTRL-EVENT-SCAN-RESULTS":
            results = dev.supplicant.scan_results() if dev.supplicant else []
            for ap in results:
                ap["security"] = security.from_flags(ap["flags"])
            dev.scan = results
            dev.scan_at = time.monotonic()
            self.emit("scan", device=dev.iface, count=len(results))
            if dev.state == "disconnected":
                self.autoconnect(dev)
        elif name == "CTRL-EVENT-CONNECTED":
            self.set_state(dev, "getting-ip")
            if dev.profile is not None:
                net.configure(dev.iface, True, dev.profile.ipv4(), dev.profile.ipv6())
            dev.deadline = time.monotonic() + 40
        elif name == "CTRL-EVENT-DISCONNECTED":
            if dev.state in ("connected", "getting-ip"):
                self.set_state(dev, "disconnected", f"reason {f.get('reason', '?')}")
                self.request_scan(dev)
        elif name == "CTRL-EVENT-EAP-PEER-CERT" and f.get("depth") == "0":
            dev.peer_cert.update(subject=f.get("subject", ""), hash=f.get("hash", ""))
        elif name == "CTRL-EVENT-EAP-PEER-ALT" and f.get("depth") == "0":
            alt = f.get("_0", "")
            if alt.startswith("DNS:"):
                dev.peer_cert.setdefault("domain", alt[4:])
        elif name == "CTRL-EVENT-EAP-TLS-CERT-ERROR":
            dev.cert_error = True
            self.on_cert_error(dev, f)
        elif name == "CTRL-EVENT-EAP-FAILURE" or (name == "CTRL-EVENT-SSID-TEMP-DISABLED"
                                                  and f.get("reason") in ("AUTH_FAILED", "EAP_FAILURE")):
            if not dev.cert_error:
                self.on_auth_failure(dev)
        elif name == "CTRL-EVENT-SSID-TEMP-DISABLED" and f.get("reason") == "WRONG_KEY":
            self.fail(dev, "secrets", "Secrets were required, but not provided (the password was refused).",
                      need=["password"])
        elif name == "CTRL-EVENT-ASSOC-REJECT":
            dev.reason = f"association rejected (status {f.get('status_code', '?')})"
        elif name == "CTRL-EVENT-TERMINATING":
            dev.supplicant = None

    def on_cert_error(self, dev: Device, f: dict) -> None:
        """The server's certificate isn't signed by a CA this system trusts: the network has its own. Pin the
        server's certificate on first use (as phones do), tell the user its fingerprint, and connect again."""
        prof = dev.profile
        if prof is None or dev.retried_cert:
            self.fail(dev, "certificate", f"The network's certificate was refused: {f.get('err', 'untrusted')}.")
            return
        ca = prof.eap().get("ca-cert", "auto") or "auto"
        fingerprint = dev.peer_cert.get("hash", "")
        if ca != "auto" or prof.get("nmx", "server-cert") or not fingerprint:
            self.fail(dev, "certificate", f"The network's certificate does not match the one trusted before "
                                          f"({f.get('err', 'untrusted')}). If the network changed it, run: "
                                          f"nmxcli connection modify '{prof.id}' nmx.server-cert ''")
            return
        dev.retried_cert = True
        prof.set("nmx.server-cert", f"hash://server/sha256/{fingerprint}")
        prof.set("nmx.server-subject", dev.peer_cert.get("subject", ""))
        self.emit("certificate-trusted", device=dev.iface, connection=prof.id, subject=dev.peer_cert.get("subject", ""),
                  sha256=fingerprint)
        dev.cert_error = False
        self.start_wifi(dev, prof, keep_waiters=True)

    def on_auth_failure(self, dev: Device) -> None:
        prof = dev.profile
        if prof is not None and prof.kind in ("eap", "eap-suite-b") and prof.get("nmx", "eap-auto") == "true":
            nxt = security.fallback_phase2(prof.eap())
            if nxt is not None:
                prof.set("802-1x.eap", nxt["eap"])
                prof.set("802-1x.phase2-auth", nxt["phase2-auth"])
                log(f"{dev.iface}: trying {nxt['eap']}/{nxt['phase2-auth']} for {prof.id}")
                self.start_wifi(dev, prof, keep_waiters=True)
                return
        self.fail(dev, "secrets", "Secrets were required, but not provided (the username or password was refused).",
                  need=["username", "password"] if prof is not None and prof.kind.startswith("eap") else ["password"])

    # ── connecting ──
    def best_ap(self, dev: Device, ssid: str) -> dict | None:
        aps = [ap for ap in dev.scan if ap["ssid"] == ssid]
        return max(aps, key=lambda ap: ap["level"]) if aps else None

    def start_wifi(self, dev: Device, prof: profiles.Profile, keep_waiters: bool = False) -> None:
        if dev.supplicant is None:
            raise Failure("unavailable", f"{dev.iface} is not ready (radio off or the card is missing)")
        ap = self.best_ap(dev, prof.ssid)
        fields = prof.network_block(ap["security"] if ap else None)
        fields["bgscan"] = '"simple:30:-70:3600"'
        dev.profile = prof
        dev.peer_cert = {} if not keep_waiters else dev.peer_cert
        dev.cert_error = False
        if not keep_waiters:
            dev.retried_cert = False
        dev.autoconnect_blocked = False
        dev.supplicant.connect(fields)
        dev.deadline = time.monotonic() + (70 if prof.kind.startswith("eap") else 45)
        self.set_state(dev, "connecting", prof.id)

    def activate_ethernet(self, dev: Device, prof: profiles.Profile | None = None) -> None:
        if prof is None:
            candidates = [p for p in self.store.all() if p.type == "ethernet" and p.autoconnect
                          and p.interface in ("", dev.iface)]
            prof = max(candidates, key=lambda p: p.priority) if candidates else profiles.Profile.new(
                f"Wired connection ({dev.iface})", "ethernet")
            dev.pending_new = not candidates
        dev.profile = prof
        net.configure(dev.iface, False, prof.ipv4(), prof.ipv6())
        dev.deadline = time.monotonic() + 40
        self.set_state(dev, "getting-ip", prof.id)

    def autoconnect(self, dev: Device) -> None:
        if not self.state["networking"] or dev.autoconnect_blocked or dev.state != "disconnected":
            return
        now = time.monotonic()
        seen = {}
        for ap in dev.scan:
            if ap["level"] > seen.get(ap["ssid"], -999):
                seen[ap["ssid"]] = ap["level"]
        candidates = []
        for prof in self.store.all():
            if prof.type != "wifi" or not prof.autoconnect or prof.interface not in ("", dev.iface):
                continue
            if prof.uuid in self.needs_secrets:
                continue
            count, after = self.failures.get(prof.uuid, (0, 0.0))
            if now < after:
                continue
            if prof.ssid in seen:
                candidates.append((prof.priority, seen[prof.ssid], prof))
            elif prof.hidden:
                candidates.append((prof.priority, -200, prof))
        if not candidates:
            return
        candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
        prof = candidates[0][2]
        try:
            dev.pending_new = False
            self.start_wifi(dev, prof)
        except (Failure, wpa.WpaError, ValueError, security.MissingSecrets) as error:
            self.note_failure(prof)
            log(f"{dev.iface}: {prof.id}: {error}")

    def note_failure(self, prof: profiles.Profile) -> None:
        count, _ = self.failures.get(prof.uuid, (0, 0.0))
        self.failures[prof.uuid] = (count + 1, time.monotonic() + BACKOFF[min(count, len(BACKOFF) - 1)])

    def succeed(self, dev: Device) -> None:
        prof = dev.profile
        if prof is not None:
            self.failures.pop(prof.uuid, None)
            self.needs_secrets.discard(prof.uuid)
            learned = False
            if dev.peer_cert.get("domain") and not prof.get("nmx", "server-domain") and \
                    prof.kind.startswith("eap") and not prof.get("nmx", "server-cert"):
                prof.set("nmx.server-domain", dev.peer_cert["domain"])
                learned = True
            if dev.pending_new or learned or prof.get("nmx", "server-cert") or prof.get("nmx", "eap-auto") == "true":
                if prof.get("nmx", "eap-auto") == "true":
                    prof.set("nmx.eap-auto", "settled")
                prof.set("connection.timestamp", str(int(time.time())))
                self.store.save(prof)
                dev.pending_new = False
        self.set_state(dev, "connected", prof.id if prof else "")
        if self.needs_power_save_off(dev):
            net.power_save_off(dev.iface)          # the driver turns it back on with each association
        self.finish_waiters(dev, {"ok": True, "message": f"Device '{dev.iface}' successfully activated"
                                  + (f" with '{prof.uuid}'." if prof else ".")})
        self.check_connectivity_soon()

    def fail(self, dev: Device, code: str, message: str, **extra) -> None:
        prof = dev.profile
        if prof is not None:
            if code == "secrets" and not dev.pending_new:
                self.needs_secrets.add(prof.uuid)
                self.emit("secrets-required", device=dev.iface, connection=prof.id, ssid=prof.ssid,
                          need=extra.get("need", ["password"]))
            self.note_failure(prof)
        if dev.supplicant:
            try:
                dev.supplicant.disconnect()
            except (wpa.WpaError, OSError):
                pass
        dev.profile = None
        dev.pending_new = False
        self.set_state(dev, "disconnected", message)
        self.finish_waiters(dev, {"ok": False, "code": code, "error": message, **extra})

    def finish_waiters(self, dev: Device, result: dict) -> None:
        for waiter in dev.waiters:
            waiter["result"] = result
            waiter["event"].set()
        dev.waiters = []

    def wait(self, dev: Device, timeout: float) -> dict:
        waiter = {"event": threading.Event(), "result": None}
        with dev.lock:
            if dev.state == "connected":
                return {"ok": True, "message": f"Device '{dev.iface}' successfully activated."}
            dev.waiters.append(waiter)
        if not waiter["event"].wait(timeout):
            with dev.lock:
                if waiter in dev.waiters:
                    dev.waiters.remove(waiter)
            return {"ok": False, "code": "timeout", "error": "Timeout expired while activating the connection."}
        return waiter["result"]

    # ── the watchdog: once a second ──
    @staticmethod
    def clock_offset() -> float:
        return time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()

    def tick(self) -> None:
        offset = self.clock_offset()
        if offset - self.boot_offset > 5:
            log(f"slept for {offset - self.boot_offset:.0f} s: reconnecting")
            self.boot_offset = offset
            self.resume()
        self.boot_offset = offset
        self.reconcile()
        now = time.monotonic()
        for dev in list(self.devices.values()):
            if not dev.managed or not dev.present:
                continue
            with dev.lock:
                if dev.state in ("connecting", "getting-ip") and now > dev.deadline:
                    if dev.state == "getting-ip":
                        self.fail(dev, "ip", "No IP address was received (DHCP timed out).")
                    else:
                        self.fail(dev, "timeout", dev.reason or "The network did not answer.")
                if dev.state == "getting-ip":
                    info = net.addresses(dev.iface)
                    if info["ip4"] or (info["ip6"] and (dev.profile is None or
                                                        (dev.profile.ipv4().get("method") or "auto") == "disabled")):
                        self.succeed(dev)
                if dev.kind == "wifi" and self.state["wifi"] and dev.supplicant is not None:
                    self.wifi_watch(dev, now)
        if now - self.checked_at > RECHECK.get(self.connectivity, 300):
            self.check_connectivity_soon()

    def wifi_watch(self, dev: Device, now: float) -> None:
        if not dev.supplicant.alive():
            log(f"{dev.iface}: wpa_supplicant exited; restarting it")
            self.start_supplicant(dev)
            return
        if dev.state == "disconnected":
            if now - dev.scan_at > 20:
                self.request_scan(dev)
            if now - dev.scan_at > 90 and now - dev.scan_requested < 30 and dev.restarts < 50:
                # Asked for scans and none came: the card is stuck (common after a resume).
                log(f"{dev.iface}: no scan results for 90 s; restarting the supplicant")
                self.start_supplicant(dev)
                if now - dev.scan_at > 180 and now - dev.last_driver_reload > 600:
                    dev.last_driver_reload = now
                    log(f"{dev.iface}: still nothing; reloading its driver ({dev.driver})")
                    self.stop_supplicant(dev)
                    net.reload_driver(dev.driver)
            elif now - dev.scan_at < 30:
                self.autoconnect(dev)

    def suspend(self) -> None:
        for dev in self.devices.values():
            if dev.kind == "wifi" and dev.managed:
                with dev.lock:
                    self.stop_supplicant(dev)
                    dev.profile = None
                    self.set_state(dev, "unavailable", "suspended")

    def resume(self) -> None:
        """After a suspend: wait for the cards, restart their supplicants, scan and reconnect."""
        if time.monotonic() - self.last_resume < 8:
            return      # the sleep hook and the clock both noticed: once is enough
        self.last_resume = time.monotonic()
        deadline = time.monotonic() + 15
        wanted = {i for i, d in self.devices.items() if d.kind == "wifi" and d.managed}
        while wanted - set(net.devices()) and time.monotonic() < deadline:
            time.sleep(0.5)
        for iface in wanted - set(net.devices()):
            dev = self.devices[iface]
            log(f"{iface}: did not come back after resume; reloading {dev.driver or 'its driver'}")
            dev.last_driver_reload = time.monotonic()
            net.reload_driver(dev.driver)
        self.failures.clear()
        for dev in self.devices.values():
            if dev.kind == "wifi" and dev.managed and dev.iface in net.devices():
                with dev.lock:
                    dev.present = True
                    dev.scan_at = time.monotonic()
                    dev.next_start = 0.0
                    self.start_supplicant(dev)
            elif dev.kind == "ethernet" and dev.managed and dev.state == "connected":
                net.configure(dev.iface, False, dev.profile.ipv4() if dev.profile else {}, {})
        self.emit("resumed")

    def check_connectivity_soon(self) -> None:
        """Check in the background: a portal or a dead DNS server can take seconds to answer."""
        self.checked_at = time.monotonic()
        threading.Thread(target=self.check_connectivity, daemon=True, name="connectivity").start()

    def check_connectivity(self, force: bool = False) -> str:
        with self.checking:
            self.checked_at = time.monotonic()
            connected = [d.iface for d in self.devices.values()
                         if d.state == "connected" and d.present and d.managed and d.kind != "loopback"]
            if not connected:
                result, url, device = "none", "", ""
            else:
                result, url, device = portal.check(connected, CHECK_URL)
            self.checked_at = time.monotonic()
            changed = result != self.connectivity or url != self.portal_url
            if result == "portal" and result != self.connectivity:
                log(f"{device}: this network wants you to sign in at {url}")
            elif self.connectivity == "portal" and result == "full":
                log("signed in to the captive portal: online")
            self.connectivity, self.portal_url, self.portal_device = result, url, device
        if changed:
            self.emit("connectivity", state=result, url=url, device=device)
        return result

    # ── requests ──
    def device(self, ifname: str = "", kind: str = "") -> Device:
        with self.lock:
            if ifname:
                dev = self.devices.get(ifname)
                if dev is None or not dev.present:
                    raise Failure("not-found", f"Device '{ifname}' not found.")
                return dev
            for dev in self.devices.values():
                if dev.present and dev.managed and (not kind or dev.kind == kind):
                    return dev
        raise Failure("not-found", "No Wi-Fi device found." if kind == "wifi" else "No device found.")

    def handle(self, req: dict, uid: int, groups: set[str]) -> dict:
        op = req.get("op", "")
        writer = uid == 0 or bool(groups & set(WRITER_GROUPS))
        reads = {"status", "devices", "device-show", "wifi-list", "connections", "connection-show", "monitor",
                 "connectivity", "portal", "hostname"}
        if op not in reads and not writer:
            raise Failure("permission", "Not authorized: you need to be in the wheel or network group.")
        if op in ("device-manage", "device-unmanage", "device-remanagenm", "suspend", "resume", "reexec", "exit") \
                and uid != 0:
            raise Failure("permission", f"Only root may do that: sudo nmxcli device {op.split('-')[1]}"
                          if op.startswith("device") else "root only")
        handler = getattr(self, "op_" + op.replace("-", "_"), None)
        if handler is None:
            raise Failure("invalid", f"unknown request '{op}'")
        return handler(req)

    def op_status(self, req: dict) -> dict:
        hw, sw = net.rfkill_state()
        states = [d.state for d in self.devices.values() if d.present and d.managed]
        overall = ("connected" if "connected" in states else "connecting" if {"connecting", "getting-ip"} & set(states)
                   else "asleep" if not self.state["networking"] else "disconnected")
        return {"ok": True, "data": {
            "running": "running", "version": __version__, "state": overall, "startup": "started",
            "connectivity": self.connectivity, "portal-url": self.portal_url,
            "networking": "enabled" if self.state["networking"] else "disabled",
            "wifi-hw": "enabled" if hw else "disabled", "wifi": "enabled" if self.state["wifi"] and sw else "disabled",
            "wwan-hw": "missing", "wwan": "enabled", "hostname": net.hostname()}}

    def op_devices(self, req: dict) -> dict:
        rows = []
        for dev in sorted(self.devices.values(), key=lambda d: (d.kind != "ethernet", d.iface)):
            if not dev.present:
                continue
            rows.append({"device": dev.iface, "type": dev.kind, "state": dev.state if dev.managed else "unmanaged",
                         "connection": dev.profile.id if dev.profile and dev.state in ("connected", "connecting",
                                                                                      "getting-ip") else "",
                         "con-uuid": dev.profile.uuid if dev.profile else "", "reason": dev.reason,
                         "managed": dev.managed, "driver": dev.driver, "hwaddr": net.hwaddr(dev.iface),
                         "mtu": net.mtu(dev.iface)})
        rows.append({"device": "lo", "type": "loopback", "state": "unmanaged", "connection": "", "con-uuid": "",
                     "reason": "", "managed": False, "driver": "", "hwaddr": "00:00:00:00:00:00", "mtu": "65536"})
        return {"ok": True, "data": rows}

    def op_device_show(self, req: dict) -> dict:
        out = []
        for row in self.op_devices(req)["data"]:
            if req.get("ifname") and row["device"] != req["ifname"]:
                continue
            row = dict(row)
            row.update(net.addresses(row["device"]) if row["device"] != "lo" else {})
            out.append(row)
        if req.get("ifname") and not out:
            raise Failure("not-found", f"Device '{req['ifname']}' not found.")
        return {"ok": True, "data": out}

    def op_wifi_list(self, req: dict) -> dict:
        devs = [self.device(req["ifname"])] if req.get("ifname") else \
            [d for d in self.devices.values() if d.kind == "wifi" and d.present and d.managed]
        rescan = req.get("rescan", "auto")
        if rescan == "yes" or (rescan == "auto" and any(time.monotonic() - d.scan_at > 30 for d in devs)):
            for dev in devs:
                self.request_scan(dev)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and any(d.scan_at < d.scan_requested for d in devs if d.supplicant):
                time.sleep(0.2)
        rows = []
        for dev in devs:
            status = {}
            if dev.supplicant and dev.state == "connected":
                try:
                    status = dev.supplicant.status()
                except (wpa.WpaError, OSError):
                    status = {}
            for ap in sorted(dev.scan, key=lambda a: a["level"], reverse=True):
                sec: security.Security = ap["security"]
                rows.append({
                    "device": dev.iface, "in-use": status.get("bssid", "").lower() == ap["bssid"],
                    "bssid": ap["bssid"].upper(), "ssid": ap["ssid"], "freq": ap["freq"], "chan": channel(ap["freq"]),
                    "signal": signal_percent(ap["level"]), "level": ap["level"], "security": sec.label,
                    "kind": sec.kind, "needs-username": sec.needs_username, "needs-password": sec.needs_password,
                    "describe": sec.describe, "pmf": sec.pmf, "flags": ap["flags"],
                    "saved": bool(self.store.for_ssid(ap["ssid"]))})
        return {"ok": True, "data": rows}

    def op_wifi_rescan(self, req: dict) -> dict:
        for dev in [self.device(req.get("ifname", ""), "wifi")]:
            self.request_scan(dev)
        return {"ok": True}

    def op_wifi_connect(self, req: dict) -> dict:
        """nmcli device wifi connect SSID [password P] [username U] ...: a saved profile is updated with what was
        given; a new one is made from what the network advertises and saved once it works."""
        dev = self.device(req.get("ifname", ""), "wifi")
        ssid = req.get("ssid") or ""
        if not ssid and req.get("bssid"):
            ssid = next((ap["ssid"] for ap in dev.scan if ap["bssid"] == req["bssid"].lower()), "")
        if not ssid:
            raise Failure("invalid", "No network name given.")
        if not any(ap["ssid"] == ssid for ap in dev.scan) and not req.get("hidden"):
            self.request_scan(dev)
            time.sleep(3)
        ap = self.best_ap(dev, ssid)
        if ap is None and not req.get("hidden"):
            raise Failure("not-found", f"No network with SSID '{ssid}' found.")
        saved = self.store.for_ssid(ssid)
        prof = saved[0] if saved else profiles.Profile.new(req.get("name") or ssid, "wifi", ssid=ssid)
        new = not saved
        sec = ap["security"] if ap else None
        kind = (sec.kind if sec else None) or (prof.kind if not new else ("psk" if req.get("password") else "open"))
        if new or (sec and prof.kind != kind and not (prof.kind == "psk" and kind in ("sae", "psk-sae"))):
            prof.set("wifi-security.key-mgmt", security.key_mgmt_for_kind(kind))
            if kind == "psk-sae":
                prof.set("nmx.sae", "true")
        if req.get("hidden"):
            prof.set("wifi.hidden", "yes")
        if req.get("bssid"):
            prof.set("wifi.bssid", req["bssid"])
        password = req.get("password")
        if kind.startswith("eap"):
            if req.get("username"):
                prof.set("802-1x.identity", req["username"])
            if password:
                prof.set("802-1x.password", password)
            for key in ("eap", "phase2-auth", "ca-cert", "domain-suffix-match", "client-cert", "private-key",
                        "private-key-password", "anonymous-identity"):
                if req.get(key) is not None:
                    prof.set(f"802-1x.{key}", req[key])
            if not prof.get("802-1x", "eap"):
                prof.set("802-1x.eap", "tls" if req.get("client-cert") else "peap")
                prof.set("nmx.eap-auto", "true")
            prof.set("802-1x.ca-cert", prof.get("802-1x", "ca-cert") or "auto")
        elif kind == "wep" and password:
            prof.set("wifi-security.wep-key0", password)
        elif password:
            prof.set("wifi-security.psk", password)
        try:
            prof.network_block(sec)
        except security.MissingSecrets as missing:
            raise Failure("secrets", "Secrets were required, but not provided.", need=missing.need,
                          security=sec.describe if sec else "") from None
        except ValueError as error:
            raise Failure("invalid", str(error)) from None
        with dev.lock:
            if not new:
                self.store.save(prof)
            self.needs_secrets.discard(prof.uuid)
            self.failures.pop(prof.uuid, None)
            self.start_wifi(dev, prof)
            dev.pending_new = new
        result = self.wait(dev, float(req.get("wait") or 90))
        if not result.get("ok"):
            raise Failure(result.get("code", "failed"), result.get("error", "Connection activation failed."),
                          **{k: v for k, v in result.items() if k not in ("ok", "code", "error")})
        return result

    def op_connections(self, req: dict) -> dict:
        active = {d.profile.uuid: d.iface for d in self.devices.values()
                  if d.profile and d.state in ("connected", "connecting", "getting-ip")}
        rows = []
        for prof in self.store.all():
            rows.append({"name": prof.id, "uuid": prof.uuid, "type": prof.type, "device": active.get(prof.uuid, ""),
                         "autoconnect": prof.autoconnect, "priority": prof.priority, "ssid": prof.ssid,
                         "timestamp": prof.get("connection", "timestamp", "0"), "active": prof.uuid in active,
                         "security": security.Security(kind=prof.kind, wpa2=True).label if prof.type == "wifi" else ""})
        for dev in self.devices.values():
            if dev.pending_new and dev.profile and dev.profile.uuid in active:
                rows.append({"name": dev.profile.id, "uuid": dev.profile.uuid, "type": dev.profile.type,
                             "device": dev.iface, "autoconnect": True, "priority": 0, "ssid": dev.profile.ssid,
                             "timestamp": "0", "active": True, "security": ""})
        if req.get("active"):
            rows = [r for r in rows if r["active"]]
        return {"ok": True, "data": rows}

    def find_profile(self, key: str) -> profiles.Profile:
        prof = self.store.find(key)
        if prof is None:
            raise Failure("not-found", f"unknown connection '{key}'.")
        return prof

    def op_connection_show(self, req: dict) -> dict:
        prof = self.find_profile(req["id"])
        return {"ok": True, "data": prof.as_dict(show_secrets=bool(req.get("show-secrets")))}

    def op_connection_up(self, req: dict) -> dict:
        prof = self.find_profile(req["id"])
        dev = self.device(req.get("ifname", "") or prof.interface, prof.type)
        if prof.type == "ethernet":
            with dev.lock:
                dev.autoconnect_blocked = False
                self.activate_ethernet(dev, prof)
        else:
            if req.get("password") or req.get("username"):
                return self.op_wifi_connect({**req, "ssid": prof.ssid, "ifname": dev.iface})
            try:
                prof.network_block()
            except security.MissingSecrets as missing:
                raise Failure("secrets", "Secrets were required, but not provided.", need=missing.need) from None
            with dev.lock:
                self.needs_secrets.discard(prof.uuid)
                self.start_wifi(dev, prof)
        result = self.wait(dev, float(req.get("wait") or 90))
        if not result.get("ok"):
            raise Failure(result.get("code", "failed"), "Connection activation failed: " + result.get("error", ""),
                          **{k: v for k, v in result.items() if k not in ("ok", "code", "error")})
        return {"ok": True, "message": f"Connection successfully activated (D-Bus active path: /nmx/{prof.uuid})"}

    def deactivate(self, dev: Device) -> None:
        with dev.lock:
            dev.autoconnect_blocked = True
            if dev.kind == "wifi" and dev.supplicant:
                dev.supplicant.disconnect()
            net.release(dev.iface)
            dev.profile = None
            self.set_state(dev, "disconnected", "disconnected by request")

    def op_connection_down(self, req: dict) -> dict:
        prof = self.find_profile(req["id"])
        for dev in self.devices.values():
            if dev.profile and dev.profile.uuid == prof.uuid:
                self.deactivate(dev)
                return {"ok": True, "message": f"Connection '{prof.id}' successfully deactivated."}
        raise Failure("not-active", f"'{prof.id}' is not an active connection.")

    def op_connection_delete(self, req: dict) -> dict:
        prof = self.find_profile(req["id"])
        for dev in self.devices.values():
            if dev.profile and dev.profile.uuid == prof.uuid:
                self.deactivate(dev)
                dev.autoconnect_blocked = False
        self.store.delete(prof)
        return {"ok": True, "message": f"Connection '{prof.id}' ({prof.uuid}) successfully deleted."}

    def op_connection_add(self, req: dict) -> dict:
        props = dict(req.get("props", {}))
        type_ = props.pop("type", props.pop("connection.type", "wifi"))
        name = props.pop("con-name", props.pop("connection.id", "")) or props.get("ssid") or props.get("wifi.ssid") or type_
        try:
            prof = profiles.Profile.new(name, type_, **props)
        except ValueError as error:
            raise Failure("invalid", str(error)) from None
        self.store.save(prof)
        return {"ok": True, "message": f"Connection '{prof.id}' ({prof.uuid}) successfully added."}

    def op_connection_modify(self, req: dict) -> dict:
        prof = self.find_profile(req["id"])
        try:
            for key, value in req.get("props", {}).items():
                if key.startswith("+") or key.startswith("-"):
                    section, k = profiles.normalise_property(key[1:])
                    items = [i for i in prof.get(section, k).replace(";", ",").split(",") if i]
                    items = items + [value] if key[0] == "+" else [i for i in items if i != value]
                    prof.set(f"{section}.{k}", ",".join(items))
                else:
                    prof.set(key, value)
        except ValueError as error:
            raise Failure("invalid", str(error)) from None
        self.store.save(prof)
        self.needs_secrets.discard(prof.uuid)
        self.failures.pop(prof.uuid, None)
        return {"ok": True}

    def op_connection_import_nm(self, req: dict) -> dict:
        names = profiles.import_networkmanager(self.store)
        return {"ok": True, "message": f"Imported {len(names)} connection(s)" + (": " + ", ".join(names) if names else ".")}

    def op_device_connect(self, req: dict) -> dict:
        dev = self.device(req["ifname"])
        with dev.lock:
            dev.autoconnect_blocked = False
            self.failures.clear()
            if dev.kind == "ethernet":
                self.activate_ethernet(dev)
            else:
                self.request_scan(dev)
                self.autoconnect(dev)
        result = self.wait(dev, float(req.get("wait") or 90))
        if not result.get("ok"):
            raise Failure(result.get("code", "failed"), result.get("error", "activation failed"))
        return result

    def op_device_disconnect(self, req: dict) -> dict:
        dev = self.device(req["ifname"])
        self.deactivate(dev)
        return {"ok": True, "message": f"Device '{dev.iface}' successfully disconnected."}

    def op_device_unmanage(self, req: dict) -> dict:
        targets = [req["ifname"]] if req.get("ifname") else [i for i, d in self.devices.items() if d.managed]
        for iface in targets:
            dev = self.device(iface)
            with dev.lock:
                dev.managed = False
                self.stop_supplicant(dev)
                dev.profile = None
                self.set_state(dev, "unmanaged")
            if iface not in self.state["unmanaged"]:
                self.state["unmanaged"].append(iface)
        self.save_state()
        net.tell_networkmanager(sorted(i for i, d in self.devices.items() if d.managed and d.present))
        for iface in targets:
            net.give_back_to_networkmanager(iface)
        message = ("nmx no longer manages " + ", ".join(targets) + ". `sudo nmxcli device manage "
                   + (targets[0] if len(targets) == 1 else "") + "` takes it back.")
        if net.run(["systemctl", "is-active", "--quiet", "NetworkManager.service"]).returncode != 0:
            message += " To let NetworkManager have it: sudo systemctl enable --now NetworkManager"
        return {"ok": True, "message": message}

    def op_device_remanagenm(self, req: dict) -> dict:
        """Hand every device back to NetworkManager: nmx lets go of them all (remembered, like `device unmanage`),
        NetworkManager is turned on at boot and now, and told to manage them. `sudo nmxcli device manage` (with no
        device) takes them all back."""
        targets = [i for i, d in self.devices.items() if d.managed]
        message = self.op_device_unmanage({"ifname": ""})["message"] if targets else "nmx manages no devices."
        if not networkmanager_installed():
            return {"ok": True, "message": message + " NetworkManager is not installed: sudo pacman -S networkmanager, "
                    "then run this again."}
        enabled = net.run(["systemctl", "enable", "--now", "NetworkManager.service"], timeout=60)
        if enabled.returncode != 0:
            raise Failure("failed", "Could not start NetworkManager: " + (enabled.stderr.strip() or "systemctl failed"))
        for iface in targets or [i for i, d in self.devices.items() if d.present]:
            net.give_back_to_networkmanager(iface)
        return {"ok": True, "message": "NetworkManager manages " + (", ".join(targets) or "the devices")
                + " again, and starts at boot. `sudo nmxcli device manage` gives them all back to nmx."}

    def op_device_manage(self, req: dict) -> dict:
        targets = [req["ifname"]] if req.get("ifname") else list(self.state["unmanaged"])
        self.state["unmanaged"] = [i for i in self.state["unmanaged"] if i not in targets]
        self.save_state()
        for iface in targets:
            dev = self.devices.get(iface)
            if dev:
                dev.managed = True
                dev.autoconnect_blocked = False
                self.set_state(dev, "disconnected")
        self.reconcile()
        return {"ok": True, "message": "nmx manages " + ", ".join(targets or ["nothing new"]) + "."}

    def op_radio(self, req: dict) -> dict:
        if req.get("wifi") in ("on", "off"):
            on = req["wifi"] == "on"
            net.set_rfkill(on)
            self.state["wifi"] = on
            self.save_state()
            self.failures.clear()
            self.reconcile()
        return self.op_status(req)

    def op_networking(self, req: dict) -> dict:
        if req.get("enable") in ("on", "off"):
            on = req["enable"] == "on"
            self.state["networking"] = on
            self.save_state()
            for dev in self.devices.values():
                if not on and dev.managed:
                    self.deactivate(dev)
                dev.autoconnect_blocked = False
            self.reconcile()
        return self.op_status(req)

    def op_connectivity(self, req: dict) -> dict:
        if req.get("check"):
            self.check_connectivity(force=True)
        return {"ok": True, "data": self.connectivity, "url": self.portal_url}

    def op_portal(self, req: dict) -> dict:
        if req.get("check"):
            self.check_connectivity(force=True)
        return {"ok": True, "data": {"connectivity": self.connectivity, "url": self.portal_url,
                                     "device": self.portal_device}}

    def op_hostname(self, req: dict) -> dict:
        if req.get("name"):
            if not net.set_hostname(req["name"]):
                raise Failure("failed", "Could not set the hostname.")
        return {"ok": True, "data": net.hostname()}

    def op_reexec(self, req: dict) -> dict:
        """After an upgrade: run the new code. Supplicants are stopped and restarted by the new process."""
        threading.Timer(0.3, self.reexec).start()
        return {"ok": True}

    def reexec(self) -> None:
        self.shutdown()
        os.execv(sys.executable, [sys.executable, "-I", "/usr/bin/nmxd"])

    def op_exit(self, req: dict) -> dict:
        """The package is being removed: stop for good (exit status 75 is not restarted)."""
        def leave():
            self.shutdown()
            os._exit(75)
        threading.Timer(0.3, leave).start()
        return {"ok": True}

    def shutdown(self) -> None:
        self.stopping = True
        for dev in self.devices.values():
            if dev.supplicant:
                try:
                    dev.supplicant.stop()
                except OSError:
                    pass
        try:
            SOCKET.unlink()
        except FileNotFoundError:
            pass

    def op_suspend(self, req: dict) -> dict:
        self.suspend()
        return {"ok": True}

    def op_resume(self, req: dict) -> dict:
        self.boot_offset = self.clock_offset()
        threading.Thread(target=self.resume, daemon=True).start()
        return {"ok": True}

    # ── the socket ──
    def serve(self) -> None:
        daemon = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                uid, groups = peer(self.request)
                for raw in self.rfile:
                    try:
                        req = json.loads(raw)
                        if req.get("op") == "monitor":
                            with daemon.lock:
                                daemon.subscribers.append(self.request)
                            self.wfile.write(b'{"ok": true}\n')
                            # Held open: events are written by emit() until the client goes away.
                            self.request.recv(1)
                            return
                        reply = daemon.handle(req, uid, groups)
                    except Failure as failure:
                        reply = {"ok": False, "code": failure.code, "error": str(failure), **failure.extra}
                    except (ValueError, KeyError) as error:
                        reply = {"ok": False, "code": "invalid", "error": f"invalid request: {error}"}
                    except Exception as error:  # noqa: BLE001 - report, keep serving
                        traceback.print_exc()
                        reply = {"ok": False, "code": "failed", "error": str(error)}
                    self.wfile.write((json.dumps(reply, default=str) + "\n").encode())

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True

        try:
            SOCKET.unlink()
        except FileNotFoundError:
            pass
        server = Server(str(SOCKET), Handler)
        os.chmod(SOCKET, 0o666)
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def run(self) -> None:
        RUN.mkdir(parents=True, exist_ok=True)
        os.chmod(RUN, 0o755)
        if not (STATE.parent / "imported-networkmanager").exists():
            names = profiles.import_networkmanager(self.store)
            if names:
                log(f"imported from NetworkManager: {', '.join(names)}")
            STATE.parent.mkdir(parents=True, exist_ok=True)
            (STATE.parent / "imported-networkmanager").touch()
        net.ensure_services()
        self.serve()
        self.reconcile()
        # Opting in (systemctl enable --now nmx): the first start switches the system over, once.
        for line in net.take_over(STATE.parent / "took-over"):
            log(line)
        if self.state["wifi"]:
            net.set_rfkill(True)
        notify_ready()
        log(f"nmxd {__version__} running; managing " + (", ".join(i for i, d in self.devices.items() if d.managed) or "nothing yet"))
        while not self.stopping:
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the watchdog never dies
                traceback.print_exc()
            time.sleep(1)


def channel(freq: int) -> int:
    if 2412 <= freq <= 2472:
        return (freq - 2407) // 5
    if freq == 2484:
        return 14
    if 5000 <= freq <= 5900:
        return (freq - 5000) // 5
    if 5950 <= freq <= 7115:
        return (freq - 5950) // 5
    return 0


def signal_percent(dbm: int) -> int:
    """dBm as nmcli's 0-100 SIGNAL: -100 dBm or worse is 0, -50 or better is 100."""
    return max(0, min(100, 2 * (dbm + 100)))


def peer(sock: socket.socket) -> tuple[int, set[str]]:
    creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, gid = struct.unpack("3i", creds)
    groups: set[str] = set()
    try:
        user = pwd.getpwuid(uid).pw_name
        groups = {grp.getgrgid(g).gr_name for g in os.getgrouplist(user, gid)}
    except (KeyError, OSError):
        pass
    return uid, groups


def notify_ready() -> None:
    """sd_notify READY=1, without libsystemd."""
    path = os.environ.get("NOTIFY_SOCKET")
    if not path:
        return
    if path.startswith("@"):
        path = "\0" + path[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        try:
            sock.sendto(b"READY=1", path)
        except OSError:
            pass


def main() -> int:
    if os.geteuid() != 0:
        print("nmxd runs as root (systemctl start nmx)", file=sys.stderr)
        return 1
    daemon = Daemon()

    def on_term(signum, frame):
        daemon.shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, on_term)
    daemon.run()
    return 0
