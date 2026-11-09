"""nmx: security detection, wpa_supplicant blocks, profiles, the daemon's decisions and nmcli-compatible output."""

from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import stat
import sys
import threading
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "nmx"))

from nmx import cli, daemon, net, portal, profiles, security, wpa  # noqa: E402


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


def test_surface_card_only_its_client_interface(tmp_path):
    """Marvell mwifiex (Surface) makes mlan0, uap0 (access point) and wfd0 (Wi-Fi Direct) on one radio: nmx takes
    only mlan0, so no second supplicant fights over the radio and nmx never connects with uap0 or wfd0."""
    for name in ("mlan0", "uap0", "wfd0", "p2p-dev-wlan1", "wlan1"):
        d = tmp_path / name
        (d / "device").mkdir(parents=True)
        (d / "phy80211").mkdir()
        (d / "phy80211" / "name").write_text("phy1\n" if name.endswith("wlan1") else "phy0\n")
        (d / "type").write_text("1\n")
    assert net.devices(tmp_path) == {"mlan0": "wifi", "wlan1": "wifi"}


def test_one_client_interface_per_radio(tmp_path):
    for name in ("wlan0", "wlan9"):
        d = tmp_path / name
        (d / "device").mkdir(parents=True)
        (d / "phy80211").mkdir()
        (d / "phy80211" / "name").write_text("phy0\n")
    assert net.devices(tmp_path) == {"wlan0": "wifi"}


def test_iw_decides_the_interface_type(monkeypatch):
    monkeypatch.setattr(net.shutil, "which", lambda tool: "/usr/bin/iw")
    replies = {"mlan0": "Interface mlan0\n\tifindex 3\n\ttype managed\n", "uap0": "Interface uap0\n\ttype AP\n",
               "odd0": "Interface odd0\n\ttype P2P-client\n"}
    monkeypatch.setattr(net, "run", lambda cmd, timeout=15: net.subprocess.CompletedProcess(cmd, 0, replies[cmd[2]], ""))
    net._WIFI_TYPES.clear()
    assert net.wifi_station("mlan0") and not net.wifi_station("uap0") and not net.wifi_station("odd0")
    assert net.wifi_type("mlan0") == "managed"
    net._WIFI_TYPES.clear()


def test_surface_card_power_saving_off(nmxd):
    d, dev = nmxd
    dev.driver = "mwifiex_pcie"
    assert d.needs_power_save_off(dev)
    dev.driver = "iwlwifi"
    assert not d.needs_power_save_off(dev)


def test_remanage_networkmanager(nmxd, monkeypatch):
    d, dev = nmxd
    ran, given = [], []
    monkeypatch.setattr(net, "give_back_to_networkmanager", lambda iface: given.append(iface))
    monkeypatch.setattr(daemon, "networkmanager_installed", lambda: True)
    monkeypatch.setattr(net, "run", lambda cmd, timeout=15: ran.append(cmd) or net.subprocess.CompletedProcess(cmd, 0, "", ""))
    with pytest.raises(daemon.Failure) as denied:
        d.handle({"op": "device-remanagenm"}, 1000, {"wheel"})
    assert "sudo nmxcli device remanagenm" in str(denied.value)
    reply = d.handle({"op": "device-remanagenm"}, 0, set())
    assert reply["ok"] and "NetworkManager manages wlan0" in reply["message"]
    assert not dev.managed and json.loads(daemon.STATE.read_text())["unmanaged"] == ["wlan0"]
    assert ["systemctl", "enable", "--now", "NetworkManager.service"] in ran
    assert "wlan0" in given
    monkeypatch.setattr(d, "reconcile", lambda: None)
    d.handle({"op": "device-manage"}, 0, set())                      # and `device manage` takes them all back
    assert dev.managed


def test_remanage_without_networkmanager_says_how(nmxd, monkeypatch):
    d, _ = nmxd
    monkeypatch.setattr(net, "give_back_to_networkmanager", lambda iface: None)
    monkeypatch.setattr(net, "run", lambda cmd, timeout=15: net.subprocess.CompletedProcess(cmd, 0, "", ""))
    monkeypatch.setattr(daemon, "networkmanager_installed", lambda: False)
    reply = d.handle({"op": "device-remanagenm"}, 0, set())
    assert "sudo pacman -S networkmanager" in reply["message"]


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
    server.shutdown(socket.SHUT_RDWR)                # wakes the accept(): a closed but still waiting socket's fd
    server.close()                                   # number is reused by the next test's sockets


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


# ── captive portals ──────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def hotspot():
    """A stand-in for the internet and for a hotel's portal, on localhost."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    pages = {
        "/online": (200, {}, portal.CHECK_TEXT + "\n"),
        "/redirect": (302, {"Location": "/login?orig=probe"}, ""),
        "/meta": (200, {}, '<html><head><meta http-equiv="refresh" content="0; url=https://portal.example/welcome">'),
        "/script": (200, {}, "<script>window.location.href = '/splash';</script>"),
        "/511": (511, {}, '<form method="post" action="https://wifi.example/auth">'),
        "/blank": (200, {}, "<html>hello</html>"),
        "/broken": (503, {}, "down"),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            code, headers, body = pages.get(self.path, (404, {}, ""))
            self.send_response(code)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_portal_probe(hotspot):
    assert portal.probe(hotspot + "/online") == ("full", "")
    assert portal.probe(hotspot + "/redirect") == ("portal", hotspot + "/login?orig=probe"), "redirects are not followed"
    assert portal.probe(hotspot + "/meta") == ("portal", "https://portal.example/welcome")
    assert portal.probe(hotspot + "/script") == ("portal", hotspot + "/splash")
    assert portal.probe(hotspot + "/511") == ("portal", "https://wifi.example/auth")
    assert portal.probe(hotspot + "/blank") == ("portal", hotspot + "/blank"), "the probe itself leads to the portal"
    assert portal.probe(hotspot + "/broken") == ("limited", "")
    assert portal.probe("http://127.0.0.1:9/") == ("limited", "")


def test_portal_api_and_networkd_hint(monkeypatch):
    assert portal.api("http://portal.example/api") == (None, ""), "RFC 8908 APIs are HTTPS only"
    assert portal.find_uri({"Interfaces": [{"Name": "wlan0", "DHCPv4Client": {"CaptivePortal": "https://p/api"}}]}) \
        == "https://p/api"
    assert portal.find_uri({"Name": "wlan0"}) == ""
    monkeypatch.setattr(net, "run", lambda cmd, timeout=15: net.subprocess.CompletedProcess(
        cmd, 0, json.dumps({"CaptivePortal": "https://p/api"}), ""))
    assert portal.advertised("wlan0") == "https://p/api"

    monkeypatch.setattr(portal, "api", lambda uri: (True, "https://p/login"))
    monkeypatch.setattr(portal, "probe", lambda url=portal.CHECK_URL: ("full", ""))
    assert portal.check(["wlan0"]) == ("portal", "https://p/login", "wlan0"), "the network's own word comes first"
    monkeypatch.setattr(portal, "api", lambda uri: (False, ""))
    monkeypatch.setattr(portal, "probe", lambda url=portal.CHECK_URL: ("portal", "http://x/"))
    assert portal.check(["wlan0"]) == ("full", "", ""), "signed in, says the network"
    monkeypatch.setattr(portal, "advertised", lambda iface: "")
    assert portal.check(["wlan0"]) == ("portal", "http://x/", "wlan0")


def test_daemon_reports_the_portal(nmxd, hotspot, monkeypatch):
    d, dev = nmxd
    monkeypatch.setattr(portal, "advertised", lambda iface: "")
    dev.state = "connected"
    monkeypatch.setattr(daemon, "CHECK_URL", hotspot + "/redirect")
    assert d.check_connectivity(force=True) == "portal"
    assert d.events[-1] == ("connectivity", {"state": "portal", "url": hotspot + "/login?orig=probe", "device": "wlan0"})
    assert d.handle({"op": "portal"}, 1000, set())["data"]["url"] == hotspot + "/login?orig=probe"
    assert d.op_status({})["data"]["portal-url"] == hotspot + "/login?orig=probe"
    assert daemon.RECHECK["portal"] < 60, "a portal is checked often, so signing in shows up quickly"
    monkeypatch.setattr(daemon, "CHECK_URL", hotspot + "/online")
    assert d.op_connectivity({"check": True}) == {"ok": True, "data": "full", "url": ""}
    assert d.events[-1][1]["state"] == "full"
    count = len(d.events)
    d.check_connectivity()
    assert len(d.events) == count, "no event when nothing changed"
    dev.state = "disconnected"
    assert d.check_connectivity() == "none"


def test_cli_portal(fake_nmxd, monkeypatch):
    REPLIES["portal"] = {"ok": True, "data": {"connectivity": "portal", "url": "http://hotel/login", "device": "wlan0"}}
    try:
        assert run("-t", "portal") == (0, "http://hotel/login\n", "")
        assert "wlan0 wants you to sign in" in run("portal")[1]
        opened = []
        monkeypatch.setattr(cli, "open_url", lambda url: opened.append(url) or 0)
        assert run("portal", "open")[0] == 0 and opened == ["http://hotel/login"]
        assert fake_nmxd[-1] == {"op": "portal", "check": False}
        run("p", "check")
        assert fake_nmxd[-1] == {"op": "portal", "check": True}
        REPLIES["portal"] = {"ok": True, "data": {"connectivity": "full", "url": "", "device": ""}}
        assert run("-t", "portal") == (10, "", "")
    finally:
        del REPLIES["portal"]
    assert cli.describe_event({"event": "connectivity", "state": "portal", "url": "http://hotel/login"}) == \
        "Connectivity is now 'portal': sign in at http://hotel/login"


def test_networkmanager_assist_enables_system_ca_only_when_profile_has_no_explicit_ca(monkeypatch):
    from nmx import nm_assist
    values = {
        "eligible": "peap;\nalice@uni.example\n--\n--\n--\n--\nno\n--",
        "custom-ca": "peap;\nbob@uni.example\nfile:///etc/ssl/custom.pem\n--\n--\n--\nno\n--",
        "custom-phase2": "ttls;\nbob@uni.example\n--\n--\nfile:///etc/ssl/inner.pem\n--\nno\n--",
        "pwd": "pwd;\nuser@uni.example\n--\n--\n--\n--\nno\n--",
        "already-trusted": "peap;\nalice@uni.example\n--\n--\n--\n--\nyes\n--",
        "no-domain": "peap;\nalice\n--\n--\n--\n--\nno\n--",
    }

    def fake_run(args):
        if args[:4] == ["nmcli", "-t", "-f", "UUID"]:
            return "\n".join(values)
        if args[:3] == ["nmcli", "-g", "802-1x.eap,802-1x.identity,802-1x.ca-cert,802-1x.ca-path,802-1x.phase2-ca-cert,802-1x.phase2-ca-path,802-1x.system-ca-certs,802-1x.domain-suffix-match"]:
            return values[args[-1]]
        return ""
    monkeypatch.setattr(nm_assist, 'run', fake_run)
    changed = []

    def modify(args, **kwargs):
        changed.append(args)
        return subprocess.CompletedProcess(args, 0, '', '')
    monkeypatch.setattr(nm_assist.subprocess, 'run', modify)
    nm_assist.ensure_system_ca()
    assert changed == [["nmcli", "connection", "modify", "eligible", "802-1x.system-ca-certs", "yes",
                        "802-1x.domain-suffix-match", "uni.example"]]


def test_networkmanager_assist_opens_portal_only_in_a_graphical_session(monkeypatch):
    from nmx import nm_assist
    monkeypatch.setattr(portal, 'probe', lambda: ('portal', 'http://login.example/'))
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    monkeypatch.delenv('DISPLAY', raising=False)
    monkeypatch.setattr(nm_assist, 'run', lambda _args: '')
    opened = []
    monkeypatch.setattr(nm_assist.subprocess, 'Popen', lambda args, **kwargs: opened.append((args, kwargs)))
    assert nm_assist.open_portal_if_needed('portal', '') == ''
    assert not opened
    monkeypatch.setenv('WAYLAND_DISPLAY', 'wayland-1')
    monkeypatch.setattr(nm_assist, 'run', lambda _args: 'WAYLAND_DISPLAY=wayland-1')
    assert nm_assist.open_portal_if_needed('portal', '') == 'http://login.example/'
    assert opened and opened[0][0] == ['xdg-open', 'http://login.example/']



def test_nmx_package_does_not_install_a_global_unmanaged_devices_rule():
    package = (ROOT / "packages" / "pkgbuild" / "nmx" / "PKGBUILD.in").read_text()
    assert "data/90-nmx-networkmanager.conf" not in package
