"""nmx: security detection, wpa_supplicant blocks, profiles, the daemon's decisions and nmcli-compatible output."""

from __future__ import annotations

import io
import json
import os
import socket
import stat
import sys
import threading
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "nmx"))

from nmx import cli, daemon, net, profiles, security, wpa  # noqa: E402


# ── security ─────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("flags,kind,label,user,pmf", [
    ("[ESS]", "open", "", False, 0),
    ("[WEP][ESS]", "wep", "WEP", False, 0),
    ("[WPA2-PSK-CCMP][WPS][ESS]", "psk", "WPA2", False, 1),
    ("[WPA-PSK-TKIP][WPA2-PSK-CCMP+TKIP][ESS]", "psk", "WPA1 WPA2", False, 1),
    ("[WPA2-PSK+SAE-CCMP][ESS]", "psk-sae", "WPA2 WPA3", False, 1),
    ("[RSN-SAE-CCMP][ESS]", "sae", "WPA3", False, 2),
    ("[WPA2-SAE+FT/SAE-CCMP][ESS]", "sae", "WPA3", False, 2),
    ("[WPA2-EAP+FT/EAP-CCMP-preauth][ESS]", "eap", "WPA2 802.1X", True, 1),
    ("[WPA2-EAP-SUITE-B-192-GCMP-256][ESS]", "eap-suite-b", "WPA3 802.1X", True, 2),
    ("[WPA2-OWE-CCMP][ESS]", "owe", "OWE", False, 2),
    ("[WPA2-PSK-SHA256-CCMP][ESS]", "psk", "WPA2", False, 1),
])
def test_security_from_scan_flags(flags, kind, label, user, pmf):
    sec = security.from_flags(flags)
    assert (sec.kind, sec.label, sec.needs_username, sec.pmf) == (kind, label, user, pmf)
    assert sec.needs_password == (kind not in ("open", "owe"))


def test_ft_and_wps_are_noticed():
    sec = security.from_flags("[WPA2-PSK+FT/PSK-CCMP][WPS][ESS]")
    assert sec.ft and sec.wps


def test_psk_block_hex_ssid_and_both_akms():
    block = security.network_block(ssid='Café "home"', kind="psk", psk="correct horse")
    assert block["ssid"] == 'Café "home"'.encode().hex()
    assert block["psk"] == '"correct horse"'
    assert block["key_mgmt"].split() == ["WPA-PSK", "WPA-PSK-SHA256", "FT-PSK"]
    assert block["ieee80211w"] == "1"


def test_transition_mode_joins_with_psk_and_sae():
    block = security.network_block(ssid="x", kind="psk-sae", psk="password1")
    assert "SAE" in block["key_mgmt"].split() and "WPA-PSK" in block["key_mgmt"].split()
    assert block["sae_password"] == '"password1"' and block["ieee80211w"] == "1"


def test_wpa3_only_requires_pmf_and_takes_short_passwords():
    block = security.network_block(ssid="x", kind="sae", psk="short")
    assert block["ieee80211w"] == "2" and "psk" not in block


def test_bad_wpa2_password_is_refused():
    with pytest.raises(ValueError):
        security.network_block(ssid="x", kind="psk", psk="short")


def test_missing_secrets_say_what_is_needed():
    with pytest.raises(security.MissingSecrets) as psk:
        security.network_block(ssid="x", kind="psk")
    assert psk.value.need == ["password"]
    with pytest.raises(security.MissingSecrets) as eap:
        security.network_block(ssid="x", kind="eap", eap={})
    assert eap.value.need == ["username", "password"]
    with pytest.raises(security.MissingSecrets) as tls:
        security.network_block(ssid="x", kind="eap", eap={"eap": "tls", "identity": "me"})
    assert tls.value.need == ["certificate"]


def test_enterprise_block_hides_the_username_and_checks_the_server():
    block = security.network_block(ssid="eduroam", kind="eap",
                                   eap={"identity": "alice@uni.example", "password": "pw", "domain-suffix-match": "uni.example"})
    assert block["eap"] == "PEAP" and block["phase2"] == '"auth=MSCHAPV2"'
    assert bytes.fromhex(block["anonymous_identity"]).decode() == "anonymous@uni.example"
    assert block["ca_cert"] == f'"{security.SYSTEM_CA_BUNDLE}"'
    assert block["domain_suffix_match"] == '"uni.example"'


def test_pinned_certificate_replaces_the_ca_bundle():
    block = security.network_block(ssid="corp", kind="eap",
                                   eap={"identity": "bob", "password": "pw", "ca-cert": "hash://server/sha256/ab12"})
    assert block["ca_cert"] == '"hash://server/sha256/ab12"' and "domain_suffix_match" not in block


def test_ttls_and_eap_tls():
    ttls = security.eap_fields({"eap": "ttls", "identity": "u", "password": "p"})
    assert ttls["phase2"] == '"auth=PAP"'
    tls = security.eap_fields({"eap": "tls", "identity": "u", "client-cert": "/c.pem", "private-key": "file:///k.pem",
                               "private-key-password": "kp"})
    assert tls["client_cert"] == '"/c.pem"' and tls["private_key"] == '"/k.pem"' and "password" not in tls


def test_fallback_order_for_enterprise():
    eap = {"eap": "peap", "identity": "u", "password": "p"}
    seen = []
    while eap is not None:
        seen.append((eap["eap"], eap.get("phase2-auth", "")))
        eap = security.fallback_phase2(eap)
    assert seen == [("peap", ""), ("ttls", "pap"), ("ttls", "mschapv2"), ("peap", "gtc")]


# ── wpa_supplicant's text ────────────────────────────────────────────────────────────────────────────────────────

def test_scan_results_and_escaped_ssids():
    text = ("bssid / frequency / signal level / flags / ssid\n"
            "aa:bb:cc:dd:ee:ff\t2437\t-52\t[WPA2-PSK-CCMP][ESS]\tHome\n"
            "11:22:33:44:55:66\t5180\t-70\t[ESS]\tCaf\\xc3\\xa9 \\\"Free\\\"\n")
    rows = wpa.parse_scan_results(text)
    assert rows[0] == {"bssid": "aa:bb:cc:dd:ee:ff", "freq": 2437, "level": -52, "flags": "[WPA2-PSK-CCMP][ESS]", "ssid": "Home"}
    assert rows[1]["ssid"] == 'Café "Free"'


def test_event_fields_keep_quoted_spaces():
    name, f = wpa.parse_event("CTRL-EVENT-EAP-PEER-CERT depth=0 subject='/C=GB/CN=radius.uni.example' hash=abc123")
    assert name == "CTRL-EVENT-EAP-PEER-CERT" and f["subject"] == "/C=GB/CN=radius.uni.example" and f["hash"] == "abc123"
    _, alt = wpa.parse_event("CTRL-EVENT-EAP-PEER-ALT depth=0 DNS:radius.uni.example")
    assert alt["depth"] == "0" and alt["_0"] == "DNS:radius.uni.example"


def test_control_socket_round_trip(tmp_path, monkeypatch):
    """The control client against a stand-in wpa_supplicant socket: replies, and events kept apart from them."""
    monkeypatch.setattr(wpa, "RUN", tmp_path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(str(tmp_path / "wlan0"))

    def serve():
        for _ in range(3):
            data, addr = server.recvfrom(4096)
            if data == b"STATUS":
                server.sendto(b"<3>CTRL-EVENT-SCAN-STARTED ", addr)   # an event first: skipped by request()
                server.sendto(b"wpa_state=COMPLETED\nssid=Home\nbssid=aa:bb:cc:dd:ee:ff\n", addr)
            elif data == b"ATTACH":
                server.sendto(b"OK\n", addr)
                server.sendto(b"<3>CTRL-EVENT-CONNECTED - Connection to aa:bb:cc:dd:ee:ff completed", addr)
            else:
                server.sendto(b"FAIL\n", addr)

    threading.Thread(target=serve, daemon=True).start()
    ctrl = wpa.Control("wlan0", tmp_path)
    assert wpa.parse_status(ctrl.request("STATUS")) == {"wpa_state": "COMPLETED", "ssid": "Home", "bssid": "aa:bb:cc:dd:ee:ff"}
    ctrl.ok("ATTACH")
    assert ctrl.recv_event(2).startswith("CTRL-EVENT-CONNECTED")
    with pytest.raises(wpa.WpaError):
        ctrl.ok("BOGUS")
    ctrl.close()
    server.close()


# ── profiles ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_nmcli_property_names(tmp_path):
    prof = profiles.Profile.new("Office", "wifi", ssid="corp")
    prof.set("wifi-sec.key-mgmt", "WPA-EAP")
    prof.set("802-1x.identity", "me")
    prof.set("802-11-wireless.hidden", "yes")
    prof.set("con-name", "Office 2")
    assert prof.kind == "eap" and prof.hidden and prof.id == "Office 2"
    with pytest.raises(ValueError):
        prof.set("bogus.key", "1")


def test_store_round_trip_is_private(tmp_path):
    store = profiles.Store(tmp_path / "c")
    prof = profiles.Profile.new("Home", "wifi", ssid="Home")
    prof.set("wifi-sec.key-mgmt", "wpa-psk")
    prof.set("wifi-sec.psk", "secret12")
    path = store.save(prof)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    again = store.find("Home")
    assert again is not None and again.get("wifi-security", "psk") == "secret12"
    assert store.find(prof.uuid).id == "Home"
    assert store.as_dict if False else again.as_dict()["wifi-security"]["psk"] == "<hidden>"


def test_networkmanager_keyfiles_import(tmp_path):
    nm = tmp_path / "nm"
    nm.mkdir()
    (nm / "Uni.nmconnection").write_text(
        "[connection]\nid=Uni\nuuid=1111\ntype=802-11-wireless\n\n[wifi]\nssid=eduroam\n\n"
        "[wifi-security]\nkey-mgmt=wpa-eap\n\n[802-1x]\neap=peap;\nidentity=a@uni\npassword=x\n"
        "ca-cert=file:///etc/ssl/uni.pem\nphase2-auth=mschapv2\n\n[ipv4]\nmethod=auto\n")
    (nm / "vpn.nmconnection").write_text("[connection]\nid=VPN\nuuid=2\ntype=vpn\n")
    store = profiles.Store(tmp_path / "c")
    assert profiles.import_networkmanager(store, nm) == ["Uni"]
    uni = store.find("eduroam")
    assert uni.type == "wifi" and uni.kind == "eap" and uni.eap()["ca-cert"] == "/etc/ssl/uni.pem"
    assert profiles.import_networkmanager(store, nm) == [], "imported once"


def test_profile_follows_what_the_ap_offers_now():
    prof = profiles.Profile.new("Home", "wifi", ssid="Home")
    prof.set("wifi-sec.key-mgmt", "wpa-psk")
    prof.set("wifi-sec.psk", "secret12")
    block = prof.network_block(security.from_flags("[WPA2-PSK+SAE-CCMP][ESS]"))
    assert "SAE" in block["key_mgmt"]


# ── addressing ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_networkd_file_dhcp_and_static():
    text = net.network_file("wlan0", True, {"method": "auto"}, {"method": "auto"})
    assert "Name=wlan0" in text and "DHCP=yes" in text and "RouteMetric=600" in text
    static = net.network_file("eth0", False, {"method": "manual", "addresses": "192.0.2.5/24", "gateway": "192.0.2.1",
                                              "dns": "9.9.9.9;1.1.1.1"}, {"method": "disabled"})
    assert "Address=192.0.2.5/24" in static and "Gateway=192.0.2.1" in static and "DNS=1.1.1.1" in static
    assert "DHCP=no" in static and "IPv6AcceptRA=no" in static


def test_take_over_once(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(net, "run", lambda cmd, timeout=15: calls.append(cmd) or __import__("subprocess").CompletedProcess(cmd, 0, "", ""))
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("nameserver 192.0.2.1\n")
    marker = tmp_path / "state/took-over"
    done = net.take_over(marker, resolv)
    assert resolv.is_symlink() and os.readlink(resolv) == net.RESOLVED_STUB
    assert (tmp_path / "resolv.conf.before-nmx").read_text() == "nameserver 192.0.2.1\n"
    assert ["systemctl", "disable", "--now", "NetworkManager.service"] in calls and len(done) == 2
    calls.clear()
    assert net.take_over(marker, resolv) == [] and calls == [], "only the first start"


def test_device_kinds(tmp_path):
    for name, files in {"wlan0": ["device", "wireless"], "eth0": ["device"], "lo": [], "br0": ["bridge"]}.items():
        d = tmp_path / name
        d.mkdir()
        for f in files:
            (d / f).mkdir()
        (d / "type").write_text("1\n")
    assert net.devices(tmp_path) == {"eth0": "ethernet", "wlan0": "wifi"}


# ── the daemon's decisions, with a stand-in wpa_supplicant ───────────────────────────────────────────────────────

class FakeSupplicant:
    def __init__(self):
        self.connected_with = []
        self.disconnects = 0

    def connect(self, fields):
        self.connected_with.append(dict(fields))
        return 0

    def disconnect(self):
        self.disconnects += 1

    def scan(self):
        pass

    def alive(self):
        return True

    def stop(self):
        pass


@pytest.fixture
def nmxd(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(net, "configure", lambda *a, **k: None)
    monkeypatch.setattr(net, "release", lambda *a, **k: None)
    monkeypatch.setattr(net, "tell_networkmanager", lambda *a, **k: None)
    d = daemon.Daemon()
    d.store = profiles.Store(tmp_path / "connections")
    dev = daemon.Device("wlan0", "wifi")
    dev.supplicant = FakeSupplicant()
    flags = {"Home": "[WPA2-PSK-CCMP][ESS]", "eduroam": "[WPA2-EAP-CCMP][ESS]", "Cafe": "[ESS]"}
    dev.scan = [{"bssid": f"aa:00:00:00:00:0{i}", "freq": 2412, "level": -50, "flags": f, "ssid": s,
                 "security": security.from_flags(f)} for i, (s, f) in enumerate(flags.items())]
    d.devices["wlan0"] = dev
    events = []
    monkeypatch.setattr(d, "emit", lambda event, **f: events.append((event, f)))
    d.events = events
    return d, dev


def eap_profile(store):
    prof = profiles.Profile.new("eduroam", "wifi", ssid="eduroam")
    prof.set("wifi-sec.key-mgmt", "wpa-eap")
    prof.set("802-1x.identity", "a@uni.example")
    prof.set("802-1x.password", "pw")
    prof.set("802-1x.eap", "peap")
    prof.set("802-1x.ca-cert", "auto")
    prof.set("nmx.eap-auto", "true")
    store.save(prof)
    return prof


def test_untrusted_server_certificate_is_pinned_once_and_retried(nmxd):
    d, dev = nmxd
    prof = eap_profile(d.store)
    d.start_wifi(dev, prof)
    d.on_event(dev, "CTRL-EVENT-EAP-PEER-CERT depth=0 subject='/CN=radius.uni.example' hash=deadbeef")
    d.on_event(dev, "CTRL-EVENT-EAP-TLS-CERT-ERROR reason=1 depth=0 subject='/CN=radius.uni.example' err='self-signed'")
    assert prof.get("nmx", "server-cert") == "hash://server/sha256/deadbeef"
    assert dev.supplicant.connected_with[-1]["ca_cert"] == '"hash://server/sha256/deadbeef"'
    assert ("certificate-trusted", {"device": "wlan0", "connection": "eduroam", "subject": "/CN=radius.uni.example",
                                    "sha256": "deadbeef"}) in d.events
    # A different certificate later is refused, not silently re-pinned.
    d.on_event(dev, "CTRL-EVENT-EAP-TLS-CERT-ERROR reason=1 depth=0 subject='/CN=evil' err='mismatch'")
    assert dev.state == "disconnected" and "certificate" in dev.reason.lower()


def test_refused_enterprise_login_tries_the_next_method(nmxd):
    d, dev = nmxd
    prof = eap_profile(d.store)
    d.start_wifi(dev, prof)
    d.on_event(dev, "CTRL-EVENT-EAP-FAILURE EAP authentication failed")
    assert dev.supplicant.connected_with[-1]["eap"] == "TTLS"
    assert dev.supplicant.connected_with[-1]["phase2"] == '"auth=PAP"'


def test_wrong_password_on_a_saved_network_asks_again(nmxd):
    d, dev = nmxd
    prof = profiles.Profile.new("Home", "wifi", ssid="Home")
    prof.set("wifi-sec.key-mgmt", "wpa-psk")
    prof.set("wifi-sec.psk", "oldpassword")
    d.store.save(prof)
    d.start_wifi(dev, prof)
    d.on_event(dev, 'CTRL-EVENT-SSID-TEMP-DISABLED id=0 ssid="Home" auth_failures=1 duration=10 reason=WRONG_KEY')
    assert prof.uuid in d.needs_secrets
    assert any(e == "secrets-required" and f["need"] == ["password"] for e, f in d.events)
    d.autoconnect(dev)
    assert len(dev.supplicant.connected_with) == 1, "no retry storm with the refused password"


def test_wifi_connect_reports_what_is_needed(nmxd):
    d, dev = nmxd
    with pytest.raises(daemon.Failure) as eap:
        d.op_wifi_connect({"ssid": "eduroam"})
    assert eap.value.code == "secrets" and eap.value.extra["need"] == ["username", "password"]
    with pytest.raises(daemon.Failure) as psk:
        d.op_wifi_connect({"ssid": "Home"})
    assert psk.value.extra["need"] == ["password"]
    assert d.store.all() == [], "nothing saved before it works"


def test_new_network_is_saved_only_when_it_connects(nmxd, monkeypatch):
    d, dev = nmxd
    monkeypatch.setattr(net, "addresses", lambda iface: {"ip4": ["192.0.2.9/24"], "ip6": []})
    monkeypatch.setattr(d, "check_connectivity", lambda force=False: "full")

    def connect_later():
        import time
        time.sleep(0.2)
        with dev.lock:
            d.on_event(dev, "CTRL-EVENT-CONNECTED - Connection to aa:00:00:00:00:00 completed")
        d.tick_device = None
        with dev.lock:
            d.succeed(dev)

    monkeypatch.setattr(d, "reconcile", lambda: None)
    threading.Thread(target=connect_later).start()
    reply = d.op_wifi_connect({"ssid": "Home", "password": "goodpassword", "wait": 5})
    assert reply["ok"]
    saved = d.store.find("Home")
    assert saved is not None and saved.get("wifi-security", "psk") == "goodpassword"


def test_permissions(nmxd):
    d, _ = nmxd
    assert d.handle({"op": "status"}, 1000, set())["ok"]
    with pytest.raises(daemon.Failure) as write:
        d.handle({"op": "radio", "wifi": "off"}, 1000, set())
    assert write.value.code == "permission"
    with pytest.raises(daemon.Failure) as unmanage:
        d.handle({"op": "device-unmanage", "ifname": "wlan0"}, 1000, {"wheel"})
    assert "sudo nmxcli device unmanage" in str(unmanage.value)


def test_unmanage_is_remembered(nmxd, monkeypatch):
    d, dev = nmxd
    monkeypatch.setattr(net, "give_back_to_networkmanager", lambda iface: None)
    d.handle({"op": "device-unmanage", "ifname": "wlan0"}, 0, set())
    assert not dev.managed and "wlan0" in json.loads(daemon.STATE.read_text())["unmanaged"]
    d.handle({"op": "device-manage", "ifname": "wlan0"}, 0, set())
    assert dev.managed and json.loads(daemon.STATE.read_text())["unmanaged"] == []


def test_signal_and_channels():
    assert daemon.signal_percent(-50) == 100 and daemon.signal_percent(-75) == 50 and daemon.signal_percent(-110) == 0
    assert daemon.channel(2437) == 6 and daemon.channel(5180) == 36


# ── nmcli-compatible output, against a stand-in nmxd ─────────────────────────────────────────────────────────────

REPLIES = {
    "status": {"ok": True, "data": {"running": "running", "version": "1", "state": "connected", "startup": "started",
                                    "connectivity": "full", "networking": "enabled", "wifi-hw": "enabled",
                                    "wifi": "enabled", "wwan-hw": "missing", "wwan": "enabled"}},
    "devices": {"ok": True, "data": [
        {"device": "wlan0", "type": "wifi", "state": "connected", "connection": "Home", "con-uuid": "u1", "reason": "",
         "managed": True, "driver": "mwifiex_pcie", "hwaddr": "AA:BB", "mtu": "1500"},
        {"device": "eth0", "type": "ethernet", "state": "unavailable", "connection": "", "con-uuid": "", "reason": "",
         "managed": True, "driver": "r8169", "hwaddr": "CC:DD", "mtu": "1500"}]},
    "wifi-list": {"ok": True, "data": [
        {"device": "wlan0", "in-use": True, "bssid": "AA:BB:CC:DD:EE:FF", "ssid": "Home", "freq": 2437, "chan": 6,
         "signal": 72, "level": -64, "security": "WPA2", "kind": "psk", "needs-username": False, "needs-password": True,
         "describe": "", "pmf": 1, "flags": "", "saved": True},
        {"device": "wlan0", "in-use": False, "bssid": "11:22:33:44:55:66", "ssid": "eduroam", "freq": 5180, "chan": 36,
         "signal": 40, "level": -80, "security": "WPA2 802.1X", "kind": "eap", "needs-username": True,
         "needs-password": True, "describe": "", "pmf": 1, "flags": "", "saved": False}]},
    "connections": {"ok": True, "data": [
        {"name": "Home", "uuid": "u1", "type": "wifi", "device": "wlan0", "autoconnect": True, "priority": 0,
         "ssid": "Home", "timestamp": "1", "active": True, "security": "WPA2"}]},
    "device-show": {"ok": True, "data": [
        {"device": "wlan0", "type": "wifi", "state": "connected", "connection": "Home", "con-uuid": "u1", "reason": "",
         "managed": True, "driver": "mwifiex_pcie", "hwaddr": "AA:BB", "mtu": "1500", "ip4": ["192.0.2.9/24"],
         "ip6": [], "gw4": "192.0.2.1", "gw6": "", "dns4": ["192.0.2.1"], "dns6": [], "domains": [], "routes4": []}]},
    "wifi-connect": {"ok": False, "code": "secrets", "error": "Secrets were required, but not provided.",
                     "need": ["username", "password"], "security": "WPA2/WPA3 Enterprise (username and password)"},
}


@pytest.fixture
def fake_nmxd(tmp_path, monkeypatch):
    path = tmp_path / "nmx.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(8)
    seen = []

    def serve():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn, conn.makefile("rwb") as stream:
                req = json.loads(stream.readline())
                seen.append(req)
                stream.write((json.dumps(REPLIES.get(req["op"], {"ok": True})) + "\n").encode())

    threading.Thread(target=serve, daemon=True).start()
    monkeypatch.setattr(cli.client, "SOCKET", str(path))
    yield seen
    server.close()


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


def test_halcyons_commands(fake_nmxd):
    code, out, _ = run("-g", "ACTIVE,SIGNAL,FREQ,SSID,BSSID,SECURITY", "d", "w")
    assert code == 0
    assert out.splitlines()[0] == "yes:72:2437 MHz:Home:AA\\:BB\\:CC\\:DD\\:EE\\:FF:WPA2"
    assert run("-t", "-f", "TYPE,STATE", "d", "status")[1].splitlines()[:2] == ["wifi:connected", "ethernet:unavailable"]
    assert run("-t", "-f", "CONNECTIVITY", "g")[1] == "full\n"
    assert run("-t", "-f", "NAME", "c", "show", "--active")[1] == "Home\n"
    assert run("radio", "wifi")[1] == "enabled\n"
    table = run("-f", "IN-USE,SIGNAL,SSID", "device", "wifi")[1].splitlines()
    assert table[0].split() == ["IN-USE", "SIGNAL", "SSID"] and table[1].split() == ["*", "72", "Home"]
    assert run("-t", "-f", "RUNNING", "general")[1] == "running\n"


def test_device_show_sections(fake_nmxd):
    out = run("-f", "GENERAL,IP4,IP6", "device", "show")[1]
    assert "GENERAL.STATE:" in out and "100 (connected)" in out and "IP4.ADDRESS[1]:" in out
    assert run("-t", "-f", "GENERAL.STATE", "device", "show", "wlan0")[1] == "GENERAL.STATE:100 (connected)\n"


def test_enterprise_needs_are_reported_like_nmcli(fake_nmxd):
    code, _, err = run("device", "wifi", "connect", "eduroam")
    assert code == 4 and "Secrets were required" in err and "username and password" in err


def test_connect_passes_enterprise_arguments(fake_nmxd):
    run("device", "wifi", "connect", "eduroam", "username", "a@uni", "password", "pw", "eap", "ttls", "phase2", "pap",
        "ca-cert", "system", "domain", "uni.example")
    req = fake_nmxd[-1]
    assert req["username"] == "a@uni" and req["eap"] == "ttls" and req["phase2-auth"] == "pap"
    assert req["ca-cert"] == "system" and req["domain-suffix-match"] == "uni.example"


def test_secrets_from_the_environment(fake_nmxd, monkeypatch):
    monkeypatch.setenv("NMX_PASSWORD", "hunter22")
    run("device", "wifi", "connect", "Home", "password", "env:NMX_PASSWORD")
    assert fake_nmxd[-1]["password"] == "hunter22"


def test_abbreviations_and_errors(fake_nmxd):
    assert cli.pick("c", list(cli.OBJECTS)) == "connection"
    assert cli.pick("d", list(cli.OBJECTS)) == "device"
    assert run("frobnicate")[0] == 2
    assert run("-t", "-f", "NOPE", "d")[0] == 2


def test_not_running(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.client, "SOCKET", str(tmp_path / "none.sock"))
    code, _, err = run("general")
    assert code == 8 and "not running" in err


def test_installing_the_package_changes_nothing():
    script = (ROOT / "packages/pkgbuild/nmx/nmx.install").read_text()
    post_install = script.split("post_install() {", 1)[1].split("}", 1)[0]
    commands = [line.strip() for line in post_install.splitlines() if line.strip() and not line.strip().startswith("echo")]
    assert commands == [], "it only says how to switch"


def test_unit_refuses_stop_and_comes_back():
    unit = (ROOT / "apps/nmx/data/nmx.service").read_text()
    assert "RefuseManualStop=yes" in unit and "Restart=always" in unit and "RestartPreventExitStatus=75" in unit
    hook = (ROOT / "apps/nmx/data/nmx.sleep").read_text()
    assert "--internal suspend" in hook and "--internal resume" in hook
    assert os.access(ROOT / "apps/nmx/data/nmx.sleep", os.X_OK)
