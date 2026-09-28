"""The QEMU test harness, without QEMU: scenarios are valid installer
configurations, and the serial-console expect logic works."""

import importlib.util
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from distrokit.installer import config as cfgmod
from distrokit.profiles import load_features, load_profiles

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("qemu_test", REPO / "tests/qemu/qemu_test.py")
qemu_test = importlib.util.module_from_spec(SPEC)
sys.modules["qemu_test"] = qemu_test  # dataclasses look their module up
SPEC.loader.exec_module(qemu_test)

SCENARIOS = sorted((REPO / "tests/qemu/scenarios").glob("*.json"))


@pytest.mark.parametrize("path", SCENARIOS, ids=lambda p: p.stem)
def test_scenarios_are_valid_install_configs(path):
    scn = json.loads(path.read_text())
    cfg = cfgmod.InstallConfig.from_dict(scn["config"])
    uefi = scn["firmware"] == "uefi"
    issues = cfgmod.validate(cfg, uefi=uefi, profiles=set(load_profiles()), features=load_features(),
                             disks={cfg.disk.disk: scn["disk_gib"] * 2**30}, check_system=False)
    assert not cfgmod.errors(issues), issues
    assert "console=ttyS0,115200" in cfg.kernel_params  # the harness logs in on the serial console
    assert cfg.user.root_password
    assert scn["disk_bus"] in ("virtio", "nvme", "sata")
    expected_disk = {"virtio": "/dev/vda", "nvme": "/dev/nvme0n1", "sata": "/dev/sda"}[scn["disk_bus"]]
    assert cfg.disk.disk == expected_disk
    names = [c.name for c in qemu_test.checks_for(scn)]
    assert {"identity", "boot-entries", "doctor", "desktop-layer"} <= set(names)
    assert len(names) == len(set(names))


def test_console_expect(tmp_path):
    path = tmp_path / "serial.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    received = []

    def serve():
        conn, _ = server.accept()
        conn.sendall(b"Booting...\r\nPlease enter passphrase for disk root: ")
        received.append(conn.recv(100))
        time.sleep(0.05)
        conn.sendall(b"\r\nqemu login: ")
        received.append(conn.recv(100))
        conn.sendall(b'( true ) >/tmp/o; echo "@@CHECK" "x" $?\r\n@@CHECK x 0\r\n')
        time.sleep(0.2)
        conn.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    con = qemu_test.Console(path, tmp_path / "log.txt")
    i, _m = con.expect([r"login: *$", r"passphrase for .*: *$"], 5)
    assert i == 1
    con.send("secret\n")
    i, _m = con.expect([r"login: *$", r"passphrase for .*: *$"], 5)
    assert i == 0
    con.send("root\n")
    _i, m = con.expect([r"^@@CHECK x (\d+)\s*$"], 5)  # the echoed command line does not match
    assert m.group(1) == "0"
    with pytest.raises(qemu_test.TestFailure) as failure:
        con.expect([r"never"], 2)
    assert "    | qemu login:" in str(failure.value)  # failures show the end of the console
    con.close()
    t.join(2)
    assert received == [b"secret\n", b"root\n"]
    assert "qemu login:" in (tmp_path / "log.txt").read_text()


def test_console_ignores_terminal_escapes(tmp_path):
    """bash 5.1+ prints ESC[?2004l before a command's output (bracketed
    paste): the line must still start with the marker, also when the
    sequence is cut in two between reads."""
    path = tmp_path / "serial.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)

    def serve():
        conn, _ = server.accept()
        conn.sendall(b"\x1b[?2004h[root@qemu ~]# echo x\r\n\x1b[?20")
        time.sleep(0.1)
        conn.sendall(b"04l\r@@CHECK identity 0\r\n\x1b[1;32mgreen\x1b[0m\r\n")
        time.sleep(0.3)
        conn.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    con = qemu_test.Console(path, tmp_path / "log.txt")
    _i, m = con.expect([r"^@@CHECK identity (\d+)\s*$"], 5)
    assert m.group(1) == "0"
    con.expect([r"^green$"], 5)
    con.close()
    t.join(2)
    assert "\x1b" not in (tmp_path / "log.txt").read_text()
