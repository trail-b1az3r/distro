#!/usr/bin/env python3
"""Install the ISO in QEMU/KVM and check the installed system.

    tests/qemu/run.sh [--iso dist/X.iso] [--scenario NAME]... [--keep] [--timeout MIN]

For each scenario in tests/qemu/scenarios/*.json:

1. boot the ISO (kernel and initramfs taken from it, so the command line can
   carry ``console=ttyS0`` and ``<id>.autoinstall=fw_cfg``) with the
   scenario's installer configuration passed through QEMU's fw_cfg, and wait
   for the unattended installation to report its result;
2. boot the installed disk with the same firmware (UEFI/OVMF or BIOS),
   unlock it if encrypted, log in on the serial console and run checks:
   identity, boot loader entries, file systems, encryption, services, the
   user's desktop, the GPU tool and ``<cli> doctor``.

Only the standard library is used. Logs and a JSON report are written to
build/qemu/<scenario>/. KVM is used when /dev/kvm is usable (TCG otherwise,
which is very slow).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "lib"))

from distrokit.branding import load_file  # noqa: E402

B = load_file(REPO / "distro.conf")

OVMF_CANDIDATES = [
    ("/usr/share/edk2/x64/OVMF_CODE.4m.fd", "/usr/share/edk2/x64/OVMF_VARS.4m.fd"),  # Arch
    ("/usr/share/edk2-ovmf/x64/OVMF_CODE.fd", "/usr/share/edk2-ovmf/x64/OVMF_VARS.fd"),  # older Arch
    ("/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_VARS_4M.fd"),  # Debian/Ubuntu
    ("/usr/share/OVMF/OVMF_CODE.fd", "/usr/share/OVMF/OVMF_VARS.fd"),
    ("/usr/share/edk2/ovmf/OVMF_CODE.fd", "/usr/share/edk2/ovmf/OVMF_VARS.fd"),  # Fedora
]


class TestFailure(Exception):
    pass


# ---------------------------------------------------------------------------
# A small expect over QEMU's serial console
# ---------------------------------------------------------------------------


class EscapeFilter:
    """Removes terminal control sequences from console output: colours and
    cursor moves (CSI), bash's bracketed-paste switches (ESC[?2004h/l),
    systemd's context strings (OSC 3008, ESC]3008;...ESC\\), terminal
    queries (DCS), and carriage returns. Otherwise they glue themselves to the
    start of output lines. Keeps its state between reads, since a read can end
    anywhere inside a sequence."""

    def __init__(self) -> None:
        self.state = ""

    def feed(self, text: str) -> str:
        out = []
        for ch in text:
            st = self.state
            if not st:
                if ch == "\x1b":
                    self.state = "esc"
                elif ch != "\r":
                    out.append(ch)
            elif st == "esc":  # the character after ESC decides the kind
                self.state = {"[": "csi", "]": "str", "P": "str", "X": "str", "^": "str", "_": "str",
                              "(": "charset", ")": "charset", "*": "charset", "+": "charset"}.get(ch, "")
            elif st == "csi":  # parameters and intermediates, then one final byte
                if "@" <= ch <= "~":
                    self.state = ""
            elif st == "str":  # OSC, DCS...: ends with BEL or ESC \
                if ch == "\x07":
                    self.state = ""
                elif ch == "\x1b":
                    self.state = "str-esc"
            elif st == "str-esc":
                self.state = "" if ch == "\\" else "str"
            else:  # charset designation: one more character
                self.state = ""
        return "".join(out)


# login's password prompt, as PAM translates it for the installed locale.
PASSWORD_PROMPT = r"(?:Password|Passwort|Mot de passe|Contraseña|Senha|Hasło|Пароль|Wachtwoord|Lösenord): *$"


class Console:
    def __init__(self, path: Path, log: Path):
        self.log = log.open("w", encoding="utf-8", errors="replace")
        self.buf = ""
        self.filter = EscapeFilter()
        self.pos = 0
        self.lock = threading.Condition()
        deadline = time.time() + 30
        while True:
            try:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.connect(str(path))
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.2)
        self.closed = False
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        while True:
            try:
                data = self.sock.recv(65536)
            except OSError:
                data = b""
            text = self.filter.feed(data.decode("utf-8", errors="replace"))
            with self.lock:
                if not data:
                    self.closed = True
                else:
                    self.buf += text
                    self.log.write(text)
                    self.log.flush()
                self.lock.notify_all()
            if not data:
                return

    def expect(self, patterns: list[str], timeout: float) -> tuple[int, re.Match]:
        """Wait for the first of ``patterns`` after the last match."""
        regs = [re.compile(p, re.MULTILINE) for p in patterns]
        deadline = time.time() + timeout
        with self.lock:
            while True:
                hits = [(m.start(), i, m) for i, r in enumerate(regs) if (m := r.search(self.buf, self.pos))]
                if hits:
                    _start, i, m = min(hits, key=lambda h: h[0])
                    self.pos = m.end()
                    return i, m
                if self.closed:
                    raise TestFailure(f"console closed while waiting for {patterns}{self._last_lines()}")
                left = deadline - time.time()
                if left <= 0:
                    raise TestFailure(f"timed out after {timeout:.0f}s waiting for {patterns}{self._last_lines()}")
                self.lock.wait(min(left, 1.0))

    def _last_lines(self, lines: int = 40) -> str:
        """The end of the console (lock held), for failure messages: CI keeps
        the job log, and the log files only as artifacts."""
        tail = "\n".join("    | " + ln for ln in self.buf.splitlines()[-lines:])
        return f"; the console ended with:\n{tail}" if tail else "; the console printed nothing"

    def send(self, text: str) -> None:
        self.sock.sendall(text.encode())

    def tail(self, lines: int = 40) -> str:
        with self.lock:
            return "\n".join(self.buf.splitlines()[-lines:])

    def close(self) -> None:
        try:
            self.sock.close()
        finally:
            self.log.close()


# ---------------------------------------------------------------------------
# QEMU
# ---------------------------------------------------------------------------


@dataclass
class Machine:
    workdir: Path
    firmware: str  # uefi | bios
    memory_mib: int = 4096
    cpus: int = 2
    disk: Path | None = None
    disk_bus: str = "virtio"
    extra: list[str] = field(default_factory=list)
    proc: subprocess.Popen | None = None

    def kvm(self) -> bool:
        return os.access("/dev/kvm", os.R_OK | os.W_OK)

    def firmware_args(self) -> list[str]:
        if self.firmware != "uefi":
            return []
        code, vars_template = next(((c, v) for c, v in OVMF_CANDIDATES if Path(c).is_file() and Path(v).is_file()),
                                   (None, None))
        if code is None:
            raise TestFailure("OVMF firmware not found (install edk2-ovmf / ovmf)")
        vars_file = self.workdir / "OVMF_VARS.fd"
        if not vars_file.exists():
            shutil.copyfile(vars_template, vars_file)
        return ["-drive", f"if=pflash,format=raw,unit=0,file={code},readonly=on",
                "-drive", f"if=pflash,format=raw,unit=1,file={vars_file}"]

    def disk_args(self) -> list[str]:
        assert self.disk
        drive = f"file={self.disk},format=qcow2,if=none,id=target,cache=unsafe,discard=unmap"
        device = {"virtio": "virtio-blk-pci,drive=target,bootindex=1",
                  "nvme": "nvme,drive=target,serial=QEMUTEST0001,bootindex=1",
                  "sata": "ide-hd,drive=target,bus=ide.0,bootindex=1"}[self.disk_bus]
        return ["-drive", drive, "-device", device]

    def start(self, serial: Path, args: list[str]) -> None:
        accel = ["-accel", "kvm", "-cpu", "host"] if self.kvm() else ["-accel", "tcg", "-cpu", "max"]
        cmd = ["qemu-system-x86_64", "-machine", "q35", *accel, "-m", str(self.memory_mib), "-smp", str(self.cpus),
               *self.firmware_args(), *self.disk_args(),
               "-nic", "user,model=virtio-net-pci", "-device", "virtio-rng-pci",
               "-vga", "virtio", "-display", "none",
               "-serial", f"unix:{serial},server=on,wait=off",
               "-no-reboot", *args, *self.extra]
        (self.workdir / "qemu-cmdline.txt").write_text(" ".join(cmd) + "\n")
        self.proc = subprocess.Popen(cmd, stdout=(self.workdir / "qemu.log").open("a"), stderr=subprocess.STDOUT)

    def wait(self, timeout: float) -> int:
        assert self.proc
        try:
            return self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            raise TestFailure(f"QEMU did not power off within {timeout:.0f}s") from None

    def kill(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()


# ---------------------------------------------------------------------------
# ISO helpers
# ---------------------------------------------------------------------------


def extract_boot_files(iso: Path, dest: Path) -> tuple[Path, Path]:
    kernel, initrd = dest / "vmlinuz-linux", dest / "initramfs-linux.img"
    if kernel.exists() and initrd.exists():
        return kernel, initrd
    inner = ["arch/boot/x86_64/vmlinuz-linux", "arch/boot/x86_64/initramfs-linux.img"]
    if shutil.which("xorriso"):
        for path, out in zip(inner, (kernel, initrd), strict=True):
            subprocess.run(["xorriso", "-osirrox", "on", "-indev", str(iso), "-extract", "/" + path, str(out)],
                           check=True, capture_output=True)
    elif shutil.which("bsdtar"):
        subprocess.run(["bsdtar", "-xf", str(iso), "-C", str(dest), *inner], check=True)
        for path, out in zip(inner, (kernel, initrd), strict=True):
            (dest / path).rename(out)
    elif shutil.which("7z"):
        subprocess.run(["7z", "e", "-y", f"-o{dest}", str(iso), *inner], check=True, capture_output=True)
    else:
        raise TestFailure("need xorriso, bsdtar or 7z to read the ISO")
    return kernel, initrd


def iso_search_param(iso: Path) -> str:
    """archiso finds its medium by file system UUID (or label)."""
    uuid = subprocess.run(["blkid", "-p", "-o", "value", "-s", "UUID", str(iso)], capture_output=True,
                          text=True).stdout.strip()
    if uuid:
        return f"archisosearchuuid={uuid}"
    label = subprocess.run(["blkid", "-p", "-o", "value", "-s", "LABEL", str(iso)], capture_output=True,
                           text=True).stdout.strip()
    if not label:
        raise TestFailure(f"cannot read the UUID or label of {iso} (blkid)")
    return f"archisolabel={label}"


# ---------------------------------------------------------------------------
# Scenario
# ---------------------------------------------------------------------------


@dataclass
class Check:
    name: str
    command: str
    must_pass: bool = True


def checks_for(scn: dict) -> list[Check]:
    cfg, expect = scn["config"], scn.get("expect", {})
    user = cfg["user"]["username"]
    out = [
        Check("identity", f"grep -qx 'ID=\"{B.id}\"' /etc/os-release"),
        Check("hostname", f"test \"$(cat /etc/hostname)\" = {cfg['hostname']}"),
        Check("root-filesystem", f"test \"$(findmnt -n -o FSTYPE /)\" = {expect.get('filesystem', 'btrfs')}"),
        Check("network-manager", "systemctl is-active --quiet NetworkManager"),
        Check("display-manager", "systemctl is-enabled --quiet sddm"),
        Check("time-sync", "systemctl is-enabled --quiet systemd-timesyncd"),
        Check("packages", f"pacman -Qk {B.id}-core {B.id}-desktop {B.id}-branding >/dev/null"),
        Check("pacman-db", "pacman -Dk >/dev/null"),
        Check("user-groups", f"id -nG {user} | grep -qw wheel"),
        Check("desktop-layer", f"test -f /home/{user}/.config/hypr/{B.id}/init.lua"),
        Check("desktop-dots", f"test -f /home/{user}/.config/hypr/hyprland.lua"
                              f" && test -d /home/{user}/.config/quickshell/ii"),
        Check("desktop-owner", f"test \"$(stat -c %U /home/{user}/.config/hypr)\" = {user}"),
        Check("plymouth-theme", f"test -f /usr/share/plymouth/themes/{B.id}/{B.id}.plymouth"),
        Check("sddm-theme", f"grep -q 'Current={B.id}' /etc/sddm.conf.d/10-{B.id}.conf"),
        Check("install-record", f"test -s /var/lib/{B.id}/install.json && test -s /var/lib/{B.id}/hardware.json"),
        Check("gpu-tool", f"{B.id}-gpu status >/dev/null"),
        Check("cli", f"{B.cli} system >/dev/null && {B.cli} hardware >/dev/null"),
        Check("doctor", f"{B.cli} doctor"),
        Check("system-running", "systemctl is-system-running --wait || { systemctl --failed --no-pager; false; }",
              must_pass=False),
    ]
    if expect.get("bootloader") == "systemd-boot":
        out.append(Check("boot-entries", f"bootctl list --no-pager | grep -q '{B.id}-linux.conf'"))
        out.append(Check("boot-diagnostic", f"bootctl list --no-pager | grep -q '{B.id}-linux-diagnostic.conf'"))
    else:
        out.append(Check("boot-entries", f"grep -q \"menuentry '{B.name} Linux\" /boot/grub/grub.cfg"))
        out.append(Check("grub-theme", f"grep -q 'themes/{B.id}/theme.txt' /boot/grub/grub.cfg"))
    if expect.get("encrypted"):
        out.append(Check("encryption", "lsblk -n -o TYPE | grep -qx crypt"))
    if cfg.get("disk", {}).get("separate_home"):
        out.append(Check("separate-home", "findmnt -n /home >/dev/null"))
    if cfg.get("disk", {}).get("swap") == "zram":
        out.append(Check("zram", "swapon --show=NAME --noheadings | grep -q zram"))
    return out


def run_scenario(name: str, scn: dict, iso: Path, out: Path, timeout_min: float, keep: bool) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.log"):
        old.unlink()
    result: dict = {"scenario": name, "description": scn.get("description", ""), "checks": [], "ok": False}
    disk = out / "disk.qcow2"
    subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", str(disk), f"{scn.get('disk_gib', 48)}G"], check=True)
    (out / "OVMF_VARS.fd").unlink(missing_ok=True)
    machine = Machine(out, scn.get("firmware", "uefi"), scn.get("memory_mib", 4096), scn.get("cpus", 2), disk,
                      scn.get("disk_bus", "virtio"))
    if not machine.kvm():
        print("  (no usable /dev/kvm: TCG emulation, this takes a long time)")
        timeout_min *= 4
    started = time.time()
    try:
        # -- 1. unattended installation from the ISO -----------------------------
        kernel, initrd = extract_boot_files(iso, out)
        cfg_file = out / "install.json"
        cfg_file.write_text(json.dumps(scn["config"], indent=2))
        cfg_file.chmod(0o600)
        append = " ".join([
            "archisobasedir=arch", iso_search_param(iso), "console=tty0", "console=ttyS0,115200",
            "systemd.unit=multi-user.target", f"{B.id}.autoinstall=fw_cfg", f"{B.id}.autoinstall.poweroff=1",
        ])
        serial = out / "serial.sock"
        serial.unlink(missing_ok=True)
        machine.start(serial, ["-cdrom", str(iso), "-kernel", str(kernel), "-initrd", str(initrd),
                               "-append", append, "-fw_cfg", f"name=opt/{B.id}/config,file={cfg_file}"])
        con = Console(serial, out / "install.log")
        try:
            _i, m = con.expect([r"AUTOINSTALL: RESULT (\d+)"], timeout_min * 60)
            code = int(m.group(1))
            result["install_seconds"] = round(time.time() - started)
            if code != 0:
                raise TestFailure(f"installation failed with code {code}:\n{con.tail(60)}")
            machine.wait(300)
        finally:
            con.close()
        print(f"  installed in {result['install_seconds']}s")

        # -- 2. first boot of the installed system --------------------------------
        serial.unlink(missing_ok=True)
        machine.start(serial, [])
        con = Console(serial, out / "boot.log")
        try:
            cfg = scn["config"]
            boot_started = time.time()
            prompts = [r"login: *$", r"[Pp]assphrase for .*: *$|Please enter passphrase"]
            while True:
                i, _m = con.expect(prompts, 600)
                if i == 1:
                    con.send(cfg["disk"]["passphrase"] + "\n")
                    continue
                break
            result["boot_seconds"] = round(time.time() - boot_started)
            # A getty restarted late in the boot shows a fresh prompt and
            # drops what was typed at the old one: answer it again.
            for _attempt in range(3):
                con.send("root\n")
                i, _m = con.expect([PASSWORD_PROMPT, r"login: *$"], 60)
                if i == 0:
                    break
            else:
                raise TestFailure("the login prompt kept coming back after 'root'" + con._last_lines())
            con.send(cfg["user"]["root_password"] + "\n")
            con.expect([r"\]# *$|# *$"], 120)
            con.send("export TERM=dumb PAGER=cat SYSTEMD_PAGER= SYSTEMD_COLORS=0 NO_COLOR=1; "
                     "bind 'set enable-bracketed-paste off' 2>/dev/null\n")
            for check in checks_for(scn):
                con.send(f"( {check.command} ) >/tmp/check.out 2>&1; echo \"@@CHECK\" \"{check.name}\" $?\n")
                _i, m = con.expect([rf"^@@CHECK {re.escape(check.name)} (\d+)\s*$"], 900)
                rc = int(m.group(1))
                output = ""
                if rc != 0:
                    con.send(f"tail -n 25 /tmp/check.out; echo \"@@END\" \"{check.name}\"\n")
                    _i, mm = con.expect([rf"^@@END {re.escape(check.name)}\s*$"], 60)
                    output = con.buf[m.end():mm.start()].strip()[-3000:]
                status = "pass" if rc == 0 else ("fail" if check.must_pass else "warn")
                result["checks"].append({"name": check.name, "status": status, "rc": rc, "output": output})
                print(f"  {status:4}  {check.name}" + (f" (exit {rc})" if rc else ""))
                if output:
                    print("\n".join("        | " + ln for ln in output.splitlines()))
            con.send("systemctl poweroff\n")
            machine.wait(300)
        finally:
            con.close()
        failed = [c["name"] for c in result["checks"] if c["status"] == "fail"]
        result["ok"] = not failed
        if failed:
            result["error"] = "failed checks: " + ", ".join(failed)
    except TestFailure as exc:
        result["error"] = str(exc)
    finally:
        machine.kill()
        result["seconds"] = round(time.time() - started)
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        if not keep:
            disk.unlink(missing_ok=True)
    return result


# Boots of the ISO itself, through the firmware and the ISO's own boot loader,
# the way a machine starts it from a USB stick or a DVD (the installation
# scenarios above boot its kernel directly).
LIVE = {
    "live-uefi-usb": {"description": "the ISO as a USB stick on UEFI: firmware, the ISO's systemd-boot, live system",
                      "firmware": "uefi", "media": "usb"},
    "live-uefi-cdrom": {"description": "the ISO as a DVD on UEFI: El Torito, the ISO's systemd-boot, live system",
                        "firmware": "uefi", "media": "cdrom"},
}


def run_live_boot(name: str, scn: dict, iso: Path, out: Path, timeout_min: float) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.log"):
        old.unlink()
    result: dict = {"scenario": name, "description": scn["description"], "checks": [], "ok": False}
    disk = out / "disk.qcow2"  # an empty internal disk, as in a real machine
    subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", str(disk), "8G"], check=True)
    (out / "OVMF_VARS.fd").unlink(missing_ok=True)
    machine = Machine(out, scn["firmware"], 4096, 2, disk, "virtio")
    if scn["media"] == "usb":
        media = ["-drive", f"file={iso},format=raw,readonly=on,if=none,id=stick",
                 "-device", "qemu-xhci", "-device", "usb-storage,drive=stick,bootindex=0"]
    else:
        media = ["-drive", f"file={iso},format=raw,media=cdrom,readonly=on,if=none,id=dvd",
                 "-device", "ide-cd,drive=dvd,bus=ide.2,bootindex=0"]
    # systemd-boot appends this SMBIOS string to its entries' command line
    # (not with Secure Boot): the live system's console on the serial port.
    serial_console = ["-smbios", "type=11,value=io.systemd.boot.kernel-cmdline-extra=console=tty0 console=ttyS0,,115200"]
    serial = out / "serial.sock"
    serial.unlink(missing_ok=True)
    started = time.time()
    try:
        machine.start(serial, [*media, *serial_console])
        con = Console(serial, out / "live.log")
        try:
            con.expect([re.escape(B.pretty_name) + r" live"], 180)
            result["checks"].append({"name": "boot-menu", "status": "pass", "rc": 0, "output": ""})
            print("  pass  boot-menu (the ISO's boot loader started)")
            con.expect([r"login: *$"], timeout_min * 60)
            result["checks"].append({"name": "live-system", "status": "pass", "rc": 0, "output": ""})
            result["boot_seconds"] = round(time.time() - started)
            print(f"  pass  live-system (up in {result['boot_seconds']}s)")
        finally:
            con.close()
        result["ok"] = True
    except TestFailure as exc:
        result["error"] = str(exc)
    finally:
        machine.kill()
        result["seconds"] = round(time.time() - started)
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        disk.unlink(missing_ok=True)
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Install the ISO in QEMU and check the result.")
    p.add_argument("--iso", help="ISO to test (default: newest in dist/)")
    p.add_argument("--scenario", action="append", help="scenario name (default: all)")
    p.add_argument("--list", action="store_true")
    p.add_argument("--timeout", type=float, default=60, help="minutes allowed for the installation (KVM)")
    p.add_argument("--keep", action="store_true", help="keep the installed disk images")
    p.add_argument("--out", default=str(REPO / "build" / "qemu"))
    a = p.parse_args(argv)
    scenarios = {f.stem: json.loads(f.read_text()) for f in sorted((REPO / "tests/qemu/scenarios").glob("*.json"))}
    scenarios |= LIVE
    if a.list:
        for name, scn in scenarios.items():
            print(f"{name:28} {scn.get('description', '')}")
        return 0
    if a.iso:
        iso = Path(a.iso)
    else:
        candidates = sorted((REPO / "dist").glob("*.iso"), key=lambda f: f.stat().st_mtime)
        if not candidates:
            print("No ISO in dist/: build one with ./build.sh or pass --iso.", file=sys.stderr)
            return 2
        iso = candidates[-1]
    missing = [t for t in ("qemu-system-x86_64", "qemu-img", "blkid") if not shutil.which(t)]
    if missing:
        print("Missing: " + ", ".join(missing) + " (scripts/bootstrap.sh --with-qemu)", file=sys.stderr)
        return 2
    wanted = a.scenario or list(scenarios)
    unknown = [s for s in wanted if s not in scenarios]
    if unknown:
        print("Unknown scenario(s): " + ", ".join(unknown), file=sys.stderr)
        return 2
    results = []
    for name in wanted:
        print(f"== {name}: {scenarios[name].get('description', '')}")
        if name in LIVE:
            res = run_live_boot(name, LIVE[name], iso, Path(a.out) / name, 15)
        else:
            res = run_scenario(name, scenarios[name], iso, Path(a.out) / name, a.timeout, a.keep)
        results.append(res)
        print(f"   {'PASS' if res['ok'] else 'FAIL'} in {res['seconds']}s" + (f": {res.get('error', '')[:6000]}"
                                                                           if not res["ok"] else ""))
    summary = {"iso": iso.name, "results": results, "ok": all(r["ok"] for r in results)}
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "report.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
