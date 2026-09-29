"""System diagnostics (``<cli> doctor``).

Every check is read-only and works without root. A check returns a status,
a one-line summary, optional details, and, when something is wrong, the
exact command that fixes it (``<cli> repair`` runs those).
"""

from __future__ import annotations

import json
import os
import platform as pyplatform
import shutil
import tarfile
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .. import boot, pkg, util
from ..branding import Branding, load as load_branding

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"


@dataclass
class Check:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)
    fix: str = ""  # command that fixes it
    critical: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


class Doctor:
    def __init__(self, root: Path | str = "/", branding: Branding | None = None, user_home: Path | None = None):
        self.root = Path(root)
        self.b = branding or load_branding()
        self.home = user_home or Path.home()
        self.live = str(self.root) == "/"

    def p(self, path: str) -> Path:
        return self.root / path.lstrip("/")

    # -- individual checks --------------------------------------------------
    def kernel(self) -> Check:
        release = pyplatform.release()
        kernels = boot.installed_kernels(self.root)
        if not kernels:
            return Check("Kernel", FAIL, "No kernel is installed", fix="sudo pacman -S linux")
        details = [f"{k.pkgbase} {k.version}" for k in kernels]
        if self.live and not self.p(f"/usr/lib/modules/{release}").is_dir():
            return Check("Kernel", WARN, f"Running {release}, which was updated on disk: reboot to use the new kernel",
                         details, critical=False)
        return Check("Kernel", OK, f"{release}" if self.live else ", ".join(details), details)

    def gpu(self) -> Check:
        from ..gpu import status as gpu_status
        from ..hardware import detect

        try:
            report = detect(self.root if not self.live else "/")
            statuses = gpu_status.gather(report, self.root, self.b)
        except Exception as exc:  # noqa: BLE001
            return Check("GPU", WARN, f"Could not inspect graphics: {exc}", critical=False)
        if not statuses:
            return Check("GPU", WARN, "No display adapter found", critical=False)
        problems = [f"{s.vendor} {s.model}: {p}" for s in statuses for p in s.problems]
        details = [f"{s.vendor} {s.model}: {s.driver} ({s.status})" for s in statuses]
        if any(s.status == "Needs attention" for s in statuses):
            return Check("GPU", FAIL, "; ".join(problems[:2]), details + problems, fix=f"sudo {self.b.cli} repair-gpu")
        if any(s.status != "Configured" for s in statuses):
            return Check("GPU", WARN, "Graphics driver not configured by the GPU manager", details + problems,
                         fix=f"sudo {self.b.cli} gpu configure", critical=False)
        return Check("GPU", OK, ", ".join(f"{s.vendor} {s.model} ({s.driver})" for s in statuses), details)

    def vulkan(self) -> Check:
        icds = list(self.p("/usr/share/vulkan/icd.d").glob("*.json")) if self.p("/usr/share/vulkan/icd.d").is_dir() else []
        if not icds:
            return Check("Vulkan", WARN, "No Vulkan driver installed", fix=f"sudo {self.b.cli} gpu configure", critical=False)
        names = sorted(i.stem.replace("_icd", "").split(".")[0] for i in icds)
        if self.live and util.which("vulkaninfo"):
            rc, out = util.run_quiet(["vulkaninfo", "--summary"], timeout=20)
            if rc != 0:
                return Check("Vulkan", FAIL, "Vulkan drivers are installed but no device initialises",
                             [f"ICDs: {', '.join(names)}"], fix=f"sudo {self.b.cli} repair-gpu")
            devices = [line.split("=", 1)[1].strip() for line in out.splitlines() if "deviceName" in line]
            return Check("Vulkan", OK, ", ".join(devices) or "available", [f"ICDs: {', '.join(names)}"])
        return Check("Vulkan", OK, f"drivers: {', '.join(names)}")

    def network(self) -> Check:
        if not self.live:
            enabled = self.p("/etc/systemd/system/multi-user.target.wants/NetworkManager.service").exists()
            return Check("Network", OK if enabled else FAIL, "NetworkManager enabled" if enabled else "NetworkManager is not enabled",
                         fix="" if enabled else "sudo systemctl enable NetworkManager")
        rc, _ = util.run_quiet(["systemctl", "is-active", "--quiet", "NetworkManager"])
        if rc != 0:
            return Check("Network", FAIL, "NetworkManager is not running", fix="sudo systemctl enable --now NetworkManager")
        rc, out = util.run_quiet(["nmcli", "networking", "connectivity", "check"], timeout=15)
        state = out.strip() or "unknown"
        if state == "full":
            return Check("Network", OK, "Connected to the internet")
        if state in ("portal", "limited"):
            return Check("Network", WARN, f"Connectivity: {state} (captive portal or no internet)", critical=False)
        return Check("Network", WARN, "Not connected", fix="nmtui", critical=False)

    def audio(self) -> Check:
        if not self.live:
            return Check("Audio", SKIP, "checked on the running system")
        if os.geteuid() == 0:
            return Check("Audio", SKIP, "run as your user to check the audio session", critical=False)
        bad = []
        for unit in ("pipewire.service", "wireplumber.service", "pipewire-pulse.service"):
            rc, _ = util.run_quiet(["systemctl", "--user", "is-active", "--quiet", unit])
            if rc != 0:
                bad.append(unit)
        if bad:
            return Check("Audio", FAIL, f"Not running: {', '.join(bad)}",
                         fix="systemctl --user restart pipewire pipewire-pulse wireplumber")
        rc, out = util.run_quiet(["wpctl", "status"], timeout=10)
        sinks = []
        in_sinks = False
        for line in out.splitlines():
            if "Sinks:" in line:
                in_sinks = True
                continue
            if in_sinks:
                if not line.strip(" │├└─") or ":" in line and "Sources" in line:
                    break
                sinks.append(line.strip(" │├└─*").strip())
        if not sinks:
            return Check("Audio", WARN, "PipeWire is running but no output device was found", critical=False)
        return Check("Audio", OK, f"PipeWire, {len(sinks)} output device(s)", sinks[:5])

    def desktop(self) -> Check:
        missing = [p for p in ("/usr/bin/Hyprland", "/usr/bin/qs") if not self.p(p).exists()]
        if missing:
            return Check("Desktop", FAIL, f"Missing: {', '.join(missing)}", fix=f"sudo pacman -S {self.b.id}-desktop")
        if self.live and os.geteuid() != 0:
            hypr = self.home / ".config" / "hypr"
            if not (hypr / "hyprland.lua").exists():
                return Check("Desktop", FAIL, "Hyprland configuration missing", fix=f"{self.b.cli} reset-desktop")
            if not (hypr / self.b.id / "init.lua").exists():
                return Check("Desktop", WARN, f"The {self.b.name} desktop layer is missing",
                             fix=f"{self.b.cli} update --desktop-only", critical=False)
            venv = self.home / ".local" / "state" / "quickshell" / ".venv" / "bin" / "python"
            if not venv.exists():
                return Check("Desktop", WARN, "The shell's Python environment is not set up yet (colour themes need it)",
                             fix=f"{self.b.cli} setup resume", critical=False)
        dm = self.p("/etc/systemd/system/display-manager.service")
        if not dm.exists():
            return Check("Desktop", WARN, "No display manager enabled", fix="sudo systemctl enable sddm", critical=False)
        return Check("Desktop", OK, "Hyprland with the Quickshell desktop")

    def bootloader(self) -> Check:
        cfg = boot.load_config(self.root, self.b)
        if cfg is None:
            return Check("Bootloader", WARN, "No boot configuration recorded (not installed by the installer?)", critical=False)
        kernels = boot.installed_kernels(self.root)
        details = [f"{cfg.bootloader} ({cfg.firmware}), ESP {cfg.esp}, boot {cfg.boot_dir}"]
        boot_root = self.p(cfg.boot_dir)
        # kernel_prefix "/" means the kernels live at the top of their own
        # partition (ESP or XBOOTLDR), which must be mounted there; otherwise
        # /boot is a plain directory on the root file system.
        separate = cfg.kernel_prefix == "/" and cfg.boot_dir != "/"
        if self.live and separate and not os.path.ismount(boot_root):
            return Check("Bootloader", FAIL, f"{cfg.boot_dir} is not mounted; kernel updates will not reach the boot partition",
                         details, fix=f"sudo mount {cfg.boot_dir}")
        missing = [k.pkgbase for k in kernels if not (boot_root / k.image).exists() or not (boot_root / k.initramfs).exists()]
        if missing:
            return Check("Bootloader", FAIL, f"Kernel or initramfs missing in {cfg.boot_dir}: {', '.join(missing)}",
                         details, fix=f"sudo {self.b.cli} repair boot")
        if cfg.bootloader == "systemd-boot":
            entries = boot_root / "loader" / "entries"
            absent = [k.pkgbase for k in kernels if not (entries / f"{self.b.id}-{k.pkgbase}.conf").exists()]
            if absent:
                return Check("Bootloader", FAIL, f"No boot entry for: {', '.join(absent)}", details,
                             fix=f"sudo {self.b.cli} repair boot")
        else:
            cfgfile = boot_root / "grub" / "grub.cfg"
            if not cfgfile.exists():
                return Check("Bootloader", FAIL, "grub.cfg is missing", details, fix=f"sudo {self.b.cli} repair boot")
        try:
            free = shutil.disk_usage(boot_root).free
            if free < 60 * 2**20:
                return Check("Bootloader", WARN, f"Only {util.human_bytes(free)} free on {cfg.boot_dir}",
                             details, critical=False)
        except OSError:
            pass
        return Check("Bootloader", OK, f"{cfg.bootloader}, {len(kernels)} kernel(s)", details)

    def package_manager(self) -> Check:
        lock = self.p("/var/lib/pacman/db.lck")
        if lock.exists():
            rc, _ = util.run_quiet(["pgrep", "-x", "pacman"])
            if rc != 0:
                return Check("Package manager", FAIL, "A stale pacman lock is blocking updates",
                             fix=f"sudo {self.b.cli} repair packages")
        installed = pkg.installed_packages(self.root)
        if not installed:
            return Check("Package manager", FAIL, "The package database is empty or unreadable")
        for keyring in ("archlinux-keyring", "endeavouros-keyring"):
            if keyring not in installed:
                return Check("Package manager", FAIL, f"{keyring} is not installed", fix=f"sudo pacman -S {keyring}")
        details = [f"{len(installed)} packages installed"]
        if self.live and util.which("pacman"):
            rc, out = util.run_quiet(["pacman", "-Dk"], timeout=60)
            if rc != 0:
                issues = [line for line in out.splitlines() if line.strip()][:10]
                return Check("Package manager", FAIL, "Missing dependencies between installed packages",
                             details + issues, fix=f"sudo {self.b.cli} repair packages")
        return Check("Package manager", OK, f"pacman, {len(installed)} packages", details)

    def ai_backend(self) -> Check:
        state = util.read_json(self.b.system_paths(self.root).install_record, {}) or {}
        backend = (state.get("ai_backend") or {}).get("name", "")
        feats = state.get("features", {})
        wanted = feats.get("hypernix") or feats.get("assistant", "none") != "none"
        if not backend:
            return Check("AI backend", SKIP, "no AI configuration recorded", critical=False)
        details = [f"backend: {backend}"]
        if backend.startswith("cuda") and self.live:
            if not util.which("nvidia-smi"):
                return Check("AI backend", FAIL, "CUDA backend, but the NVIDIA driver tools are missing", details,
                             fix=f"sudo {self.b.cli} repair-gpu")
            rc, _ = util.run_quiet(["nvidia-smi", "-L"], timeout=15)
            if rc != 0:
                return Check("AI backend", FAIL, "CUDA backend, but the NVIDIA driver is not loaded", details,
                             fix=f"sudo {self.b.cli} repair-gpu", critical=False)
        hyp = self.home / ".local" / "bin" / "hypernix"
        if wanted and os.geteuid() != 0 and not hyp.exists() and feats.get("hypernix"):
            return Check("AI backend", WARN, "HyperNix was selected but is not installed yet", details,
                         fix=f"{self.b.cli} setup resume", critical=False)
        return Check("AI backend", OK, state.get("ai_backend", {}).get("description", backend), details)

    def disk_space(self) -> Check:
        usage = shutil.disk_usage(self.root)
        pct = usage.free / usage.total * 100
        summary = f"{util.human_bytes(usage.free)} free of {util.human_bytes(usage.total)}"
        if pct < 5:
            return Check("Disk space", FAIL, summary, fix="sudo paccache -rk1; sudo pacman -Rns $(pacman -Qdtq)")
        if pct < 12:
            return Check("Disk space", WARN, summary, fix="sudo paccache -rk2", critical=False)
        return Check("Disk space", OK, summary)

    def services(self) -> Check:
        if not self.live:
            return Check("Services", SKIP, "checked on the running system", critical=False)
        rc, out = util.run_quiet(["systemctl", "--failed", "--no-legend", "--plain"], timeout=15)
        failed = [line.split()[0] for line in out.splitlines() if line.strip()]
        if failed:
            return Check("Services", WARN, f"Failed: {', '.join(failed[:4])}", failed,
                         fix="journalctl -b -u " + failed[0], critical=False)
        return Check("Services", OK, "No failed services")

    def time_sync(self) -> Check:
        if not self.live:
            return Check("Time", SKIP, "", critical=False)
        rc, out = util.run_quiet(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
        if out.strip() == "yes":
            return Check("Time", OK, "Clock synchronised")
        return Check("Time", WARN, "Clock not synchronised (TLS and package signatures can fail)",
                     fix="sudo timedatectl set-ntp true", critical=False)

    # -- run ------------------------------------------------------------------
    def checks(self) -> list[Callable[[], Check]]:
        return [self.kernel, self.gpu, self.vulkan, self.network, self.audio, self.desktop, self.bootloader,
                self.package_manager, self.ai_backend, self.disk_space, self.services, self.time_sync]

    def run(self) -> list[Check]:
        results = []
        for fn in self.checks():
            try:
                results.append(fn())
            except Exception as exc:  # noqa: BLE001 - a broken check must not hide the others
                name = fn.__name__.replace("_", " ").capitalize()
                results.append(Check(name, WARN, f"check failed: {exc}", critical=False))
        return results


def render(results: list[Check], style: util.Style | None = None, verbose: bool = False) -> str:
    style = style or util.style
    lines = [style.header("System Doctor")]
    for r in results:
        if r.status == SKIP and not verbose:
            continue
        text = f"{r.name}" + (f" — {r.summary}" if verbose or r.status != OK else "")
        lines.append({OK: style.ok, WARN: style.warn, FAIL: style.fail}.get(r.status, style.info)(text))
        if verbose:
            lines += [style.dim(f"    {d}") for d in r.details]
        if r.fix and r.status in (WARN, FAIL):
            lines.append(style.dim(f"    fix: {r.fix}"))
    critical = [r for r in results if r.status == FAIL and r.critical]
    lines.append("")
    if critical:
        lines.append(style.fail(f"{len(critical)} critical problem(s). `sudo {load_branding().cli} repair` can fix most of them."))
    elif any(r.status in (FAIL, WARN) for r in results):
        lines.append("No critical problems detected; see the warnings above.")
    else:
        lines.append("No critical problems detected.")
    return "\n".join(lines)


def write_report(results: list[Check], dest: Path, branding: Branding | None = None) -> Path:
    """A support bundle: doctor results, hardware report and recent logs.
    Nothing is sent anywhere; the user decides whether to share it."""
    from ..hardware import detect

    branding = branding or load_branding()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = dest / f"{branding.id}-report-{stamp}.tar.gz"
    tmp = Path(tempfile.mkdtemp())
    (tmp / "doctor.json").write_text(json.dumps([r.to_dict() for r in results], indent=2))
    try:
        (tmp / "hardware.json").write_text(detect().to_json())
    except Exception as exc:  # noqa: BLE001
        (tmp / "hardware.txt").write_text(f"hardware detection failed: {exc}")
    for name, cmd in {
        "journal-boot.txt": ["journalctl", "-b", "-p", "warning", "--no-pager", "-n", "400"],
        "uname.txt": ["uname", "-a"],
        "lsblk.txt": ["lsblk", "-f"],
        "lspci.txt": ["lspci", "-nnk"],
        "packages.txt": ["pacman", "-Q"],
    }.items():
        rc, out = util.run_quiet(cmd, timeout=30)
        (tmp / name).write_text(out)
    rec = branding.system_paths().install_record
    if rec.exists():
        (tmp / "install.json").write_text(rec.read_text())
    with tarfile.open(path, "w:gz") as tar:
        tar.add(tmp, arcname=f"{branding.id}-report-{stamp}")
    shutil.rmtree(tmp, ignore_errors=True)
    return path
