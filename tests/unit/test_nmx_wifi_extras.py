"""nmx: open networks with a sign-in page, the DNS-blocker bypass and finding enterprise networks' CAs."""

from __future__ import annotations

import io
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "nmx"))

from nmx import certs, cli, daemon, dnsbypass, net, profiles, security  # noqa: E402

from test_nmx import REPLIES, FakeSupplicant, fake_nmxd  # noqa: E402,F401


@pytest.fixture
def nmxd(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(net, "configure", lambda *a, **k: None)
    monkeypatch.setattr(net, "release", lambda *a, **k: None)
    monkeypatch.setattr(certs, "CHAINS", tmp_path / "chains")
    monkeypatch.setattr(certs, "CA_DIR", tmp_path / "ca")
    d = daemon.Daemon()
    d.store = profiles.Store(tmp_path / "connections")
    dev = daemon.Device("wlan0", "wifi")
    dev.supplicant = FakeSupplicant()
    scan = [("Hotel", "[ESS]", -70), ("Hotel", "[WPA2-PSK-CCMP][ESS]", -40), ("eduroam", "[WPA2-EAP-CCMP][ESS]", -50)]
    dev.scan = [{"bssid": f"aa:00:00:00:00:0{i}", "freq": 2412, "level": lvl, "flags": f, "ssid": s,
                 "security": security.from_flags(f)} for i, (s, f, lvl) in enumerate(scan)]
    d.devices["wlan0"] = dev
    d.events = []
    monkeypatch.setattr(d, "emit", lambda event, **f: d.events.append((event, f)))
    monkeypatch.setattr(d, "wait", lambda dev, timeout: {"ok": True, "message": "ok"})
    return d, dev


# ── a hotel's open network, broadcast under the same name as its staff's secured one ──

def test_open_network_with_a_secured_twin_is_joined_open(nmxd):
    d, dev = nmxd
    assert d.op_wifi_connect({"ssid": "Hotel"})["ok"], "no password asked for an open network"
    assert dev.supplicant.connected_with[-1]["key_mgmt"] == "NONE"


def test_a_password_picks_the_secured_twin(nmxd):
    d, dev = nmxd
    d.op_wifi_connect({"ssid": "Hotel", "password": "staffonly1"})
    assert "WPA-PSK" in dev.supplicant.connected_with[-1]["key_mgmt"]


def test_saved_open_profile_stays_open_when_the_secured_twin_is_stronger(nmxd):
    d, dev = nmxd
    prof = profiles.Profile.new("Hotel", "wifi", ssid="Hotel")
    d.store.save(prof)
    d.start_wifi(dev, prof)
    assert dev.supplicant.connected_with[-1]["key_mgmt"] == "NONE"


def test_an_open_network_never_fails_with_secrets(nmxd):
    d, dev = nmxd
    prof = profiles.Profile.new("Hotel", "wifi", ssid="Hotel")
    d.store.save(prof)
    d.start_wifi(dev, prof)
    d.on_event(dev, 'CTRL-EVENT-SSID-TEMP-DISABLED id=0 ssid="Hotel" auth_failures=1 duration=10 reason=WRONG_KEY')
    assert prof.uuid not in d.needs_secrets
    assert not any(e == "secrets-required" for e, _ in d.events)


# ── the DNS bypass ──

class FakeResolved:
    def __init__(self, dot_works=True, plain_works=True):
        self.calls = []
        self.dot = False
        self.works = {"dot": dot_works, "plain": plain_works}

    def __call__(self, cmd, timeout=15):
        self.calls.append(cmd)
        out = ""
        if cmd[1:2] == ["dnsovertls"]:
            self.dot = cmd[3] == "yes"
        if cmd[1:2] == ["dns"] and len(cmd) == 3:
            out = "Link 3 (wlan0): 192.0.2.1"
        if cmd[1:2] == ["domain"] and len(cmd) == 3:
            out = "Link 3 (wlan0): hotel.lan"
        code = 0
        if cmd[1:2] == ["query"]:
            code = 0 if self.works["dot" if self.dot else "plain"] else 1
        return subprocess.CompletedProcess(cmd, code, out, "")


def test_bypass_uses_dns_over_tls_and_puts_everything_back():
    fake = FakeResolved()
    bypass = dnsbypass.Bypass(run=fake)
    assert bypass.apply("wlan0") == "dot"
    assert ["resolvectl", "dnsovertls", "wlan0", "yes"] in fake.calls
    assert any(c[:3] == ["resolvectl", "dns", "wlan0"] and "1.1.1.1#cloudflare-dns.com" in c for c in fake.calls)
    assert ["resolvectl", "domain", "wlan0", "~.", "hotel.lan"] in fake.calls, "the network's search domain stays"
    fake.calls.clear()
    assert bypass.revert("wlan0")
    assert fake.calls[0] == ["resolvectl", "revert", "wlan0"]
    assert ["resolvectl", "dns", "wlan0", "192.0.2.1"] in fake.calls


def test_bypass_falls_back_to_plain_then_gives_up():
    assert dnsbypass.Bypass(run=FakeResolved(dot_works=False)).apply("wlan0") == "plain"
    fake = FakeResolved(dot_works=False, plain_works=False)
    bypass = dnsbypass.Bypass(run=fake)
    assert bypass.apply("wlan0") == ""
    assert fake.calls[-3][:2] == ["resolvectl", "revert"] or ["resolvectl", "revert", "wlan0"] in fake.calls
    assert bypass.status() == {"wlan0": "blocked"}
    assert bypass.apply("wlan0") == "", "not tried again until the link reconnects"


def test_daemon_bypass_is_off_by_default_and_never_on_a_portal(nmxd, monkeypatch):
    d, dev = nmxd
    fake = FakeResolved()
    d.bypass = dnsbypass.Bypass(run=fake)
    monkeypatch.setattr(d, "learn_certificates", lambda fetcher=None: [])
    dev.state = "connected"
    d.after_check("full")
    assert d.bypass.status() == {}, "off by default"
    d.state["dns-bypass"] = True
    d.after_check("portal")
    assert d.bypass.status() == {}, "a sign-in page needs the network's DNS"
    d.after_check("full")
    assert d.bypass.status() == {"wlan0": "dot"}
    d.after_check("portal")
    assert d.bypass.status() == {}, "a portal again (the session ran out): the network's DNS"
    d.after_check("full")
    d.op_dns_bypass_set({"enabled": False})
    d.after_check("full")
    assert d.bypass.status() == {}


def test_cli_dns_bypass(fake_nmxd):  # noqa: F811 - the fixture, imported from test_nmx
    REPLIES["dns-bypass"] = {"ok": True, "data": {"enabled": True, "links": {"wlan0": "dot"}}}
    try:
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            assert cli.main(["dns-bypass", "on"]) == 0
        assert fake_nmxd[0] == {"op": "dns-bypass-set", "enabled": True}
        assert out.getvalue().startswith("on\n") and "DNS-over-TLS" in out.getvalue()
    finally:
        del REPLIES["dns-bypass"]


# ── enterprise networks' CAs ──

def openssl(*args, cwd):
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    """A university's private root, an intermediate and its RADIUS server's certificate."""
    d = tmp_path_factory.mktemp("pki")
    ext = d / "ext.cnf"
    ext.write_text("[ca]\nbasicConstraints=critical,CA:true\nauthorityInfoAccess=caIssuers;URI:http://pki.uni.example/root.der\n"
                   "[srv]\nbasicConstraints=CA:false\nsubjectAltName=DNS:radius.uni.example\n"
                   "authorityInfoAccess=caIssuers;URI:http://pki.uni.example/inter.p7c\n")
    openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "root.key", "-out", "root.pem", "-days", "30",
            "-subj", "/CN=Uni Root CA", "-addext", "basicConstraints=critical,CA:true", cwd=d)
    openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "inter.key", "-out", "inter.csr", "-subj",
            "/CN=Uni Issuing CA", cwd=d)
    openssl("x509", "-req", "-in", "inter.csr", "-CA", "root.pem", "-CAkey", "root.key", "-CAcreateserial", "-out",
            "inter.pem", "-days", "30", "-extfile", str(ext), "-extensions", "ca", cwd=d)
    openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "srv.key", "-out", "srv.csr", "-subj",
            "/CN=radius.uni.example", cwd=d)
    openssl("x509", "-req", "-in", "srv.csr", "-CA", "inter.pem", "-CAkey", "inter.key", "-CAcreateserial", "-out",
            "srv.pem", "-days", "30", "-extfile", str(ext), "-extensions", "srv", cwd=d)
    der = {}
    for name in ("root", "inter", "srv"):
        openssl("x509", "-in", f"{name}.pem", "-outform", "DER", "-out", f"{name}.der", cwd=d)
        der[name] = (d / f"{name}.der").read_bytes()
    openssl("crl2pkcs7", "-nocrl", "-certfile", "inter.pem", "-outform", "DER", "-out", "inter.p7c", cwd=d)
    der["p7c"] = (d / "inter.p7c").read_bytes()
    return der


def fetcher_for(pki):
    served = {"http://pki.uni.example/inter.p7c": pki["p7c"], "http://pki.uni.example/root.der": pki["root"]}
    fetched = []

    def fetch(url):
        fetched.append(url)
        return served.get(url, b"")
    fetch.fetched = fetched
    return fetch


def test_certificate_details(pki):
    srv = certs.info(pki["srv"])
    assert srv["names"] == ["radius.uni.example"] and not srv["self_signed"]
    assert srv["issuers"] == ["http://pki.uni.example/inter.p7c"]
    assert certs.info(pki["root"])["self_signed"]
    assert certs.parse_download(pki["p7c"]) == [pki["inter"]], "PKCS#7 bundles are read"
    assert certs.org_domain("radius1.it.uni.example") == "uni.example"
    assert certs.org_domain("wifi.ox.ac.uk") == "ox.ac.uk"


def test_root_is_fetched_hop_by_hop(pki, tmp_path):
    fetch = fetcher_for(pki)
    result = certs.resolve([pki["srv"]], "eduroam", fetcher=fetch, bundle=str(tmp_path / "none.pem"),
                           ca_dir=tmp_path)
    assert result["domain"] == "radius.uni.example" and "Uni Root CA" in result["root"]
    assert Path(result["ca-cert"]).read_bytes() == certs.to_pem(pki["root"])
    assert fetch.fetched == ["http://pki.uni.example/inter.p7c", "http://pki.uni.example/root.der"]


def test_a_root_the_system_trusts_means_the_system_bundle(pki, tmp_path):
    bundle = tmp_path / "bundle.pem"
    bundle.write_bytes(certs.to_pem(pki["root"]))
    result = certs.resolve([pki["srv"], pki["inter"]], "eduroam", fetcher=lambda url: b"", bundle=str(bundle))
    assert result["ca-cert"] == "auto"


def test_self_signed_server_stays_pinned(pki, tmp_path):
    assert certs.resolve([pki["root"]], "x", fetcher=lambda u: b"", bundle=str(tmp_path / "none"),
                         ca_dir=tmp_path) is None


def test_daemon_learns_the_ca_and_gives_it_to_the_other_networks(nmxd, pki, monkeypatch):
    d, dev = nmxd
    monkeypatch.setattr(security, "SYSTEM_CA_BUNDLE", "/nonexistent")
    monkeypatch.setattr(certs, "SYSTEM_CA_BUNDLE", "/nonexistent")
    edu = profiles.Profile.new("eduroam", "wifi", ssid="eduroam")
    for k, v in {"wifi-sec.key-mgmt": "wpa-eap", "802-1x.eap": "peap", "802-1x.identity": "a@uni.example",
                 "802-1x.password": "pw", "802-1x.ca-cert": "auto"}.items():
        edu.set(k, v)
    d.store.save(edu)
    campus = profiles.Profile.new("UniStaff", "wifi", ssid="UniStaff")
    for k, v in {"wifi-sec.key-mgmt": "wpa-eap", "802-1x.eap": "peap", "802-1x.identity": "a@uni.example",
                 "802-1x.password": "pw"}.items():
        campus.set(k, v)
    d.store.save(campus)
    # A login attempt: wpa_supplicant shows the server's certificate (and then the pin is made).
    d.start_wifi(dev, edu)
    d.on_event(dev, f"CTRL-EVENT-EAP-PEER-CERT depth=0 subject='/CN=radius.uni.example' cert={pki['srv'].hex()}")
    d.on_event(dev, "CTRL-EVENT-EAP-PEER-CERT depth=0 subject='/CN=radius.uni.example' hash=abc")
    d.on_event(dev, "CTRL-EVENT-EAP-TLS-CERT-ERROR reason=1 depth=1 subject='/CN=Uni Issuing CA' err='unknown CA'")
    d.fail(dev, "failed", "gone")
    assert certs.load_chain("eduroam") == [pki["srv"]]
    # Later, on working Wi-Fi:
    updated = d.learn_certificates(fetcher=fetcher_for(pki))
    assert sorted(updated) == ["UniStaff", "eduroam"]
    for name in ("eduroam", "UniStaff"):
        prof = d.store.find(name)
        assert Path(prof.get("802-1x", "ca-cert")).read_bytes() == certs.to_pem(pki["root"])
        assert prof.get("802-1x", "domain-suffix-match") == "radius.uni.example"
        assert prof.get("nmx", "server-cert") == "", "the pin is dropped for the real CA"
    block = d.store.find("eduroam").network_block()
    assert block["ca_cert"].endswith('.pem"') and block["domain_suffix_match"] == '"radius.uni.example"'
    assert d.learn_certificates(fetcher=fetcher_for(pki)) == [], "done once"
