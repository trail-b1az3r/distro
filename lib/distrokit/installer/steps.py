"""The installation itself: an ordered list of steps built from an
:class:`InstallConfig` and the hardware report.

Every step goes through a :class:`~distrokit.util.Runner`, so a dry run
records the exact commands (the installer's summary and the tests use this)
and a real run streams their output to the live log.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import socket
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .. import __version__, boot, pacmanconf, paths, pkg, surface, util
from ..ai import backends, tools
from ..branding import Branding, load as load_branding
from ..desktop import deploy as desktop_deploy
from ..gpu import apply as gpu_apply
from ..gpu.plan import build_plan
from ..hardware.report import HardwareReport
from ..profiles import load_editors, load_features, load_profiles, read_list, select_packages
from ..tasks import TaskQueue, queue_for_install
from . import disks, localization
from .config import InstallConfig, resolve_bootloader

Event = Callable[[dict[str, Any]], None]

MKINITCPIO_HOOKS = "base systemd plymouth autodetect microcode modconf kms keyboard sd-vconsole block sd-encrypt filesystems fsck"
SYSTEM_SERVICES = ["NetworkManager.service", "bluetooth.service", "sddm.service", "fstrim.timer",
                   "systemd-timesyncd.service", "power-profiles-daemon.service", "paccache.timer"]
USER_GROUPS = ["wheel", "video", "audio", "input", "i2c"]
ZRAM_SYSCTL = "vm.swappiness = 180\nvm.watermark_boost_factor = 0\nvm.watermark_scale_factor = 125\nvm.page-cluster = 0\n"


class InstallError(RuntimeError):
    pass


@dataclass
class Step:
    id: str
    label: str
    func: Callable[[], None]
    weight: float = 1.0
    critical: bool = True
    destructive: bool = False


def is_online(host: str = "geo.mirror.pkgbuild.com", port: int = 443, timeout: float = 4.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class Installation:
    def __init__(self, cfg: InstallConfig, report: HardwareReport, *, runner: util.Runner | None = None,
                 branding: Branding | None = None, target: Path | None = None, emit: Event | None = None,
                 online: bool | None = None):
        self.cfg = cfg
        self.hw = report
        self.runner = runner or util.Runner()
        self.branding = branding or load_branding()
        self.target = Path(target or f"/mnt/{self.branding.id}")
        self.emit = emit or (lambda _e: None)
        self.uefi = report.firmware.uefi
        self.bootloader = resolve_bootloader(cfg, self.uefi)
        self.online = (not cfg.offline) if online is None else (online and not cfg.offline)

        profiles = load_profiles()
        if cfg.profile not in profiles:
            raise InstallError(f"unknown profile {cfg.profile}")
        self.profile = profiles[cfg.profile]
        self.selection = select_packages(self.profile, cfg.features, filesystem=cfg.disk.filesystem,
                                         branding=self.branding)
        self.features = self.selection.features
        self.feature_defs = load_features()
        self.surface_info = surface.detect(report)
        self.surface_plan = surface.plan(self.surface_info, cfg.surface_kernel)
        kernels = list(dict.fromkeys(cfg.kernels + (["linux-surface"] if cfg.surface_kernel else [])))
        self.gpu_plan = build_plan(report, kernels=kernels, compute=bool(self.features.get("gpu_compute")),
                                   multilib=cfg.multilib, overrides=cfg.gpu_overrides, branding=self.branding)
        self.backend = backends.select(report, self.gpu_plan, cfg.ai.backend)
        disk = next((d for d in report.disks if d.path == cfg.disk.disk), None)
        self.disk_plan = disks.plan_disks(cfg, disk, uefi=self.uefi, ram_bytes=report.memory.total_bytes,
                                          all_disks=report.disks, required_bytes=int(self.profile.approx_size_gb * 2**30))
        self.state: dict[str, Any] = {"created_partitions": [], "opened": [], "mounted": False, "swap_on": []}
        self.missing_packages: list[str] = []
        self.warnings: list[str] = list(self.disk_plan.warnings)

    # -- helpers --------------------------------------------------------------
    def log(self, line: str) -> None:
        self.emit({"type": "log", "line": line})

    def run(self, cmd: list[str], **kw) -> util.Result:
        return self.runner.run(cmd, **kw)

    def chroot(self, cmd: list[str], **kw) -> util.Result:
        return boot.in_root(self.runner, self.target, cmd, **kw)

    def t(self, path: str) -> Path:
        return self.target / path.lstrip("/")

    def write(self, path: str, content: str, mode: int = 0o644) -> None:
        self.log(f"write {path}")
        if self.runner.dry_run:
            return
        util.atomic_write(self.t(path), content, mode)

    def uuid(self, device: str) -> str:
        if self.runner.dry_run:
            return f"UUID-OF-{device.rsplit('/', 1)[-1]}"
        out = self.runner.output(["blkid", "-s", "UUID", "-o", "value", device]).strip()
        if not out:
            raise InstallError(f"could not read the UUID of {device}")
        return out

    @property
    def user(self) -> str:
        return self.cfg.user.username

    @property
    def home(self) -> str:
        return f"/home/{self.user}"

    def pacman_conf(self, kind: str) -> Path:
        """The live ISO ships /etc/<id>/pacman-<kind>.conf; elsewhere (tests,
        installing from an installed system) one is generated."""
        shipped = Path(f"/etc/{self.branding.id}/pacman-{kind}.conf")
        if shipped.is_file():
            return shipped
        fd, name = tempfile.mkstemp(prefix=f"{self.branding.id}-pacman-{kind}-", suffix=".conf")
        with os.fdopen(fd, "w") as fh:
            fh.write(pacmanconf.render(kind, self.branding, multilib=self.cfg.multilib,
                                       offline_repo=f"/var/cache/{self.branding.id}/repo"))
        return Path(name)

    # -- package set ----------------------------------------------------------
    def packages(self) -> list[str]:
        pk = list(self.selection.packages)
        pk += self.cfg.kernels
        micro = self.hw.cpu.microcode_package
        if micro:
            pk.append(micro)
        # GPU: repo packages go into pacstrap; AUR ones too (the offline or
        # distribution repository carries them; missing ones are built later).
        pk += self.gpu_plan.packages + self.gpu_plan.compute_packages + self.gpu_plan.aur_packages
        if self.bootloader == "grub":
            pk += read_list("grub", self.branding)
        if self.cfg.secure_boot == "sbctl":
            pk.append("sbctl")
        if self.hw.virt.guest_list:
            pk += read_list(self.hw.virt.guest_list, self.branding)
        if self.hw.chassis.portable and not self.hw.virt.is_virtual:
            pk += read_list("laptop", self.branding)
            if self.hw.cpu.vendor == "intel":
                pk += read_list("intel-laptop", self.branding)
        for adapter in self.hw.network:
            pk += adapter.extra_packages
        if self.cfg.disk.swap == "zram":
            pk.append("zram-generator")
        wants_ai = self.features.get("hypernix") or self.features.get("assistant", "none") != "none" \
            or self.cfg.ai.model or self.cfg.ai.custom_model
        if wants_ai:
            pk.append(self.backend.llama_package)
        editors = load_editors()
        editor = editors.get(self.branding.get("CODE_EDITOR", "code"))
        if self.features.get("code_editor") and editor and not editor.redistributable:
            # Installed online with yay after the base system (licence).
            pk = [p for p in pk if p != editor.package]
            self.missing_packages.append(editor.package)
        if self.features.get("containers") == "docker":
            pass  # docker group handled in users()
        pk += self.cfg.extra_packages
        return list(dict.fromkeys(pk))

    # -- steps ----------------------------------------------------------------
    def steps(self) -> list[Step]:
        s = [
            Step("preflight", "Checking the system", self.preflight, 0.5),
            Step("mirrors", "Choosing fast mirrors", self.rank_mirrors, 1, critical=False),
            Step("partition", "Partitioning", self.partition, 1, destructive=True),
            Step("format", "Creating file systems" + (" and encryption" if self._encrypting else ""), self.format, 2, destructive=True),
            Step("mount", "Mounting", self.mount, 0.5),
            Step("pacstrap", "Installing packages", self.pacstrap, 40),
            Step("fstab", "Writing the file system table", self.fstab, 0.5),
            Step("system", "Configuring language, time, keyboard and network", self.configure_system, 3),
            Step("users", "Creating your account", self.users, 1),
            Step("drivers", "Configuring graphics drivers", self.drivers, 3),
        ]
        if self.surface_plan.enabled:
            s.append(Step("surface", "Installing the Surface kernel", self.surface, 8, critical=False))
        s += [
            Step("bootloader", "Installing the boot loader", self.bootloader_step, 3),
            Step("initramfs", "Building the initial RAM disk", self.initramfs, 6),
            Step("desktop", "Setting up the desktop", self.desktop, 3),
            Step("services", "Enabling services", self.services, 1),
        ]
        if self.cfg.disk.filesystem == "btrfs" and self.features.get("snapshots"):
            s.append(Step("snapshots", "Configuring snapshots", self.snapshots, 1, critical=False))
        s.append(Step("aur", "Building remaining packages", self.aur_packages, 6, critical=False))
        s.append(Step("user-setup", "Installing AI tools and models", self.user_setup, 15, critical=False))
        s.append(Step("finish", "Finishing", self.finish, 1))
        return s

    @property
    def _encrypting(self) -> bool:
        return any(v.encrypt for v in self.disk_plan.volumes)

    # 1 -----------------------------------------------------------------------
    def preflight(self) -> None:
        if not self.runner.dry_run and os.geteuid() != 0:
            raise InstallError("The installer must run as root.")
        for tool in ("sfdisk", "pacstrap", "arch-chroot", "genfstab"):
            if not self.runner.dry_run and not util.which(tool):
                raise InstallError(f"Required tool '{tool}' is missing from the live system.")
        self.run(["timedatectl", "set-ntp", "true"], check=False)
        if self.disk_plan.disk:
            self._release_disk(self.disk_plan.disk)
        self.log(f"Network: {'online' if self.online else 'offline (offline repository only)'}")
        if not self.runner.dry_run:
            self.t("").mkdir(parents=True, exist_ok=True)

    def _release_disk(self, disk: str) -> None:
        """Stop anything the live system activated on the target disk."""
        if self.runner.dry_run:
            return
        data = json.loads(self.runner.output(["lsblk", "-J", "-p", "-o", "NAME,TYPE,MOUNTPOINTS,FSTYPE", disk]) or "{}")

        def walk(nodes):
            for n in nodes:
                yield n
                yield from walk(n.get("children") or [])

        nodes = list(walk(data.get("blockdevices", [])))
        for n in nodes:
            if n.get("fstype") == "swap":
                self.run(["swapoff", n["name"]], check=False)
        for n in reversed(nodes):
            if n.get("type") == "crypt":
                self.run(["cryptsetup", "close", n["name"]], check=False)
            if n.get("type") == "lvm":
                self.run(["vgchange", "-an"], check=False)
        data = json.loads(self.runner.output(["lsblk", "-J", "-p", "-o", "NAME,MOUNTPOINTS", disk]) or "{}")
        mounted = [m for n in walk(data.get("blockdevices", [])) for m in (n.get("mountpoints") or []) if m]
        if self.cfg.disk.mode == "erase" and mounted:
            raise InstallError(f"{disk} is in use (mounted at {', '.join(mounted)}). Unmount it and try again.")

    def rank_mirrors(self) -> None:
        if not self.online or not self.cfg.rank_mirrors or self.runner.dry_run:
            return
        if util.which("reflector"):
            self.run(["reflector", "--protocol", "https", "--latest", "20", "--age", "12", "--sort", "rate",
                      "--download-timeout", "4", "--save", "/etc/pacman.d/mirrorlist"], check=False)
        if util.which("eos-rankmirrors"):
            self.run(["eos-rankmirrors"], check=False)

    # 2 -----------------------------------------------------------------------
    def partition(self) -> None:
        plan = self.disk_plan
        if plan.mode == "manual":
            self.log("Manual partitioning: the partition table is not changed.")
            return
        if plan.mode == "erase":
            self.run(["wipefs", "--all", "--force", plan.disk])
            self.run(["sfdisk", "--wipe", "always", "--wipe-partitions", "always", plan.disk], input=plan.sfdisk_script)
        else:
            self.run(["sfdisk", "--append", "--wipe-partitions", "always", plan.disk], input=plan.sfdisk_script)
        self.state["created_partitions"] = [v.number for v in plan.new_volumes if v.number]
        self.run(["partprobe", plan.disk], check=False)
        self.run(["udevadm", "settle"], check=False)
        if not self.runner.dry_run:
            self._resolve_partitions()

    def _resolve_partitions(self) -> None:
        """Match new partitions to their device nodes by start sector."""
        data = json.loads(self.runner.output(["sfdisk", "--json", self.disk_plan.disk]))
        table = data["partitiontable"]["partitions"]
        for v in self.disk_plan.new_volumes:
            if v.start_bytes:
                hit = next((p for p in table if p["start"] == v.start_bytes // 512), None)
                if hit:
                    v.device = hit["node"]
        deadline = time.time() + 15
        while time.time() < deadline and not all(Path(v.device).exists() for v in self.disk_plan.new_volumes):
            time.sleep(0.5)
        missing = [v.device for v in self.disk_plan.new_volumes if not Path(v.device).exists()]
        if missing:
            raise InstallError(f"partition devices did not appear: {', '.join(missing)}")

    def format(self) -> None:
        for desc, cmd, stdin in disks.format_commands(self.disk_plan):
            self.log(desc)
            secret = self.cfg.disk.passphrase if stdin == "PASSPHRASE" else stdin
            self.run(cmd, input=secret)
            if cmd[:2] == ["cryptsetup", "open"]:
                self.state["opened"].append(cmd[-1])

    def mount(self) -> None:
        plan = self.disk_plan
        root = plan.volume("root")
        assert root is not None
        tgt = str(self.target)
        self.run(["mkdir", "-p", tgt])
        if root.fs == "btrfs" and root.format:
            self.run(["mount", root.fs_device, tgt])
            for sub, mp in disks.BTRFS_SUBVOLUMES:
                if mp == "/home" and plan.volume("home") is not None:
                    continue
                self.run(["btrfs", "subvolume", "create", f"{tgt}/{sub}"])
            if plan.swapfile_bytes:
                self.run(["btrfs", "subvolume", "create", f"{tgt}/@swap"])
            self.run(["umount", tgt])
        for dev, mp, fs, opts in disks.mount_table(plan):
            where = tgt if mp == "/" else f"{tgt}{mp}"
            self.run(["mkdir", "-p", where])
            self.run(["mount", "-t", fs, "-o", opts, dev, where])
        self.state["mounted"] = True
        if plan.swapfile_bytes:
            size_mib = plan.swapfile_bytes // 2**20
            if root.fs == "btrfs":
                self.run(["mkdir", "-p", f"{tgt}/swap"])
                self.run(["mount", "-o", "subvol=@swap,noatime", root.fs_device, f"{tgt}/swap"])
                self.run(["btrfs", "filesystem", "mkswapfile", "--size", f"{size_mib}m", f"{tgt}/swap/swapfile"])
            else:
                self.run(["mkdir", "-p", f"{tgt}/swap"])
                self.run(["dd", "if=/dev/zero", f"of={tgt}/swap/swapfile", "bs=1M", f"count={size_mib}", "status=none"])
                self.run(["chmod", "600", f"{tgt}/swap/swapfile"])
                self.run(["mkswap", f"{tgt}/swap/swapfile"])
            self.run(["swapon", f"{tgt}/swap/swapfile"])
            self.state["swap_on"].append(f"{tgt}/swap/swapfile")
        swap = plan.volume("swap")
        if swap is not None:
            self.run(["swapon", swap.fs_device])
            self.state["swap_on"].append(swap.fs_device)

    # 3 -----------------------------------------------------------------------
    def split_available(self, packages: list[str], conf: Path) -> tuple[list[str], list[str]]:
        """Which packages the configured repositories can provide."""
        if self.runner.dry_run:
            return packages, []
        self.run(["pacman", "--config", str(conf), "-Sy"], check=False)
        res = self.runner.run(["pacman", "--config", str(conf), "-Sp", "--print-format", "%n", *packages],
                              check=False, capture=True, mutating=False)
        missing = re.findall(r"target not found: (\S+)", res.stderr + res.stdout)
        return [p for p in packages if p not in missing], missing

    def pacstrap(self) -> None:
        conf = self.pacman_conf("live" if self.online else "offline")
        wanted = self.packages()
        available, missing = self.split_available(wanted, conf)
        essential = {"base", "linux", "mkinitcpio", "sudo", "networkmanager", f"{self.branding.id}-core"}
        fatal = [p for p in missing if p in essential or p in self.cfg.kernels]
        if fatal:
            raise InstallError(f"essential packages are unavailable: {', '.join(fatal)}. "
                               "Connect to the internet or use a complete ISO.")
        if missing:
            self.log(f"Not in the repositories, will be built from the AUR after installation: {', '.join(missing)}")
            self.missing_packages += missing
        self.emit({"type": "packages", "count": len(available)})
        self.run(["pacstrap", "-K", "-C", str(conf), str(self.target), *available])
        # Keys for EndeavourOS and the distribution repository in the new system.
        self.chroot(["pacman-key", "--populate", "archlinux", "endeavouros"], check=False)

    def fstab(self) -> None:
        tgt = str(self.target)
        if self.runner.dry_run:
            self.log("genfstab -U " + tgt)
            return
        out = self.runner.output(["genfstab", "-U", tgt])
        # subvolid= pins a subvolume by number, which breaks snapshot rollbacks.
        out = re.sub(r",subvolid=\d+", "", out)
        out = out.replace(f"{tgt}/swap/swapfile", "/swap/swapfile")
        util.atomic_write(self.t("/etc/fstab"), out)

    # 4 -----------------------------------------------------------------------
    def configure_system(self) -> None:
        c = self.cfg
        b = self.branding
        # Locale
        gen = self.t("/etc/locale.gen")
        wanted = {c.locale, "en_US.UTF-8"}
        if not self.runner.dry_run and gen.is_file():
            lines = gen.read_text().splitlines()
            out = []
            for line in lines:
                stripped = line.lstrip("#").strip()
                if stripped in {localization.locale_gen_line(w) for w in wanted}:
                    out.append(stripped)
                else:
                    out.append(line)
            util.atomic_write(gen, "\n".join(out) + "\n")
        else:
            self.write("/etc/locale.gen", "".join(localization.locale_gen_line(w) + "\n" for w in sorted(wanted)))
        self.chroot(["locale-gen"])
        self.write("/etc/locale.conf", f"LANG={c.locale}\n")
        # Time
        self.chroot(["ln", "-sf", f"/usr/share/zoneinfo/{c.timezone}", "/etc/localtime"])
        self.chroot(["hwclock", "--systohc"], check=False)
        # Keyboard: console, X11 (login screen) and Hyprland (desktop deploy).
        keymap = localization.console_keymap(c.keyboard_layout, c.keyboard_variant, self.target)
        self.write("/etc/vconsole.conf", f"KEYMAP={keymap}\n")
        variant = f'    Option "XkbVariant" "{c.keyboard_variant}"\n' if c.keyboard_variant else ""
        self.write("/etc/X11/xorg.conf.d/00-keyboard.conf",
                   'Section "InputClass"\n    Identifier "system-keyboard"\n    MatchIsKeyboard "on"\n'
                   f'    Option "XkbLayout" "{c.keyboard_layout}"\n{variant}EndSection\n')
        # Network identity
        self.write("/etc/hostname", c.hostname + "\n")
        self.write("/etc/hosts", "127.0.0.1\tlocalhost\n::1\tlocalhost\n"
                                 f"127.0.1.1\t{c.hostname}.localdomain\t{c.hostname}\n")
        # Package manager
        self.write("/etc/pacman.conf", pacmanconf.render("target", b, multilib=c.multilib))
        # Initramfs: systemd-based, LUKS prompt inside the splash screen.
        self.write(f"/etc/mkinitcpio.conf.d/10-{b.id}.conf",
                   f"# {b.pretty_name}: systemd-based initramfs with Plymouth.\nHOOKS=({MKINITCPIO_HOOKS})\n")
        # sudo for the wheel group
        self.write(f"/etc/sudoers.d/10-{b.id}-wheel", "%wheel ALL=(ALL:ALL) ALL\n", 0o440)
        # Swap
        if c.disk.swap == "zram":
            self.write("/etc/systemd/zram-generator.conf",
                       "[zram0]\nzram-size = min(ram / 2, 8192)\ncompression-algorithm = zstd\nswap-priority = 100\n")
            self.write(f"/etc/sysctl.d/99-{b.id}-zram.conf", ZRAM_SYSCTL)
        # Displays for the desktop's i2c brightness control (ddcutil), as in the dots.
        self.write("/etc/modules-load.d/i2c-dev.conf", "i2c-dev\n")
        # Kernel command line
        boot.set_fragment("00-root", self._root_params(), self.target, b, "Root file system (installer)") \
            if not self.runner.dry_run else self.log("kernel parameters: " + " ".join(self._root_params()))
        if not self.runner.dry_run:
            boot.set_fragment("10-quiet", boot.QUIET_PARAMS, self.target, b, "Quiet boot with splash screen")
            resume = self._resume_params()
            if resume:
                boot.set_fragment("40-resume", resume, self.target, b, "Hibernation")
        # Login screen
        self.write(f"/etc/sddm.conf.d/10-{b.id}.conf",
                   f"[General]\nNumlock=on\n\n[Theme]\nCurrent={b.id}\nCursorTheme=Bibata-Modern-Classic\n")
        if c.user.autologin:
            self.write(f"/etc/sddm.conf.d/20-{b.id}-autologin.conf",
                       f"[Autologin]\nUser={self.user}\nSession=hyprland.desktop\nRelogin=false\n")

    def _root_params(self) -> list[str]:
        plan = self.disk_plan
        root = plan.volume("root")
        assert root is not None
        params: list[str] = []
        for v in plan.volumes:
            if v.encrypt and v.role in ("root", "home", "swap"):
                params.append(f"rd.luks.name={self.uuid(v.device)}={v.mapper}")
        if root.encrypt:
            params.append(f"root=/dev/mapper/{root.mapper}")
        else:
            params.append(f"root=UUID={self.uuid(root.device)}")
        if root.fs == "btrfs":
            params.append("rootflags=subvol=@")
        params.append("rw")
        return params

    def _resume_params(self) -> list[str]:
        if not self.cfg.disk.hibernation:
            return []
        swap = self.disk_plan.volume("swap")
        if swap is not None:
            return [f"resume=/dev/mapper/{swap.mapper}"] if swap.encrypt else [f"resume=UUID={self.uuid(swap.device)}"]
        if self.disk_plan.swapfile_bytes:
            root = self.disk_plan.volume("root")
            assert root is not None
            dev = root.fs_device
            if root.fs == "btrfs":
                offset = self.runner.output(["btrfs", "inspect-internal", "map-swapfile", "-r", f"{self.target}/swap/swapfile"]).strip()
            else:
                out = self.runner.output(["filefrag", "-v", f"{self.target}/swap/swapfile"])
                m = re.search(r"^\s*0:\s+0\.\.\s*\d+:\s+(\d+)", out, re.MULTILINE)
                offset = m.group(1) if m else ""
            target = f"/dev/mapper/{root.mapper}" if root.encrypt else f"UUID={self.uuid(dev)}"
            return [f"resume={target}", f"resume_offset={offset}"] if offset else []
        return []

    def users(self) -> None:
        u = self.cfg.user
        self.chroot(["groupadd", "-f", "i2c"])
        groups = list(USER_GROUPS)
        if self.features.get("containers") == "docker":
            self.chroot(["groupadd", "-f", "docker"])
            groups.append("docker")
        shell = "/usr/bin/fish" if u.shell == "fish" else "/bin/bash"
        cmd = ["useradd", "-m", "-U", "-G", ",".join(groups), "-s", shell]
        if u.fullname:
            cmd += ["-c", u.fullname]
        self.chroot(cmd + [u.username])
        self.chroot(["chpasswd"], input=f"{u.username}:{u.password}\n")
        if u.root_password:
            self.chroot(["chpasswd"], input=f"root:{u.root_password}\n")
        else:
            self.chroot(["passwd", "--lock", "root"])
        if self.features.get("containers") == "podman":
            # Rootless containers need subordinate ID ranges.
            self.chroot(["usermod", "--add-subuids", "100000-165535", "--add-subgids", "100000-165535", u.username],
                        check=False)

    # 5 -----------------------------------------------------------------------
    def drivers(self) -> None:
        gpu_apply.apply(self.gpu_plan, root=self.target, runner=self.runner, branding=self.branding,
                        install_packages=False, remove_conflicts=False, regenerate=False)
        for line in self.gpu_plan.describe():
            self.log(line)

    def surface(self) -> None:
        if not self.online:
            self.warnings.append("The Surface kernel needs the internet; run `{} surface enable` later.".format(self.branding.cli))
            return
        surface.apply(self.surface_plan, root=self.target, runner=self.runner, branding=self.branding, update_boot=False)

    def bootloader_step(self) -> None:
        plan = self.disk_plan
        boot_vol = plan.volume("xbootldr") or plan.volume("boot") or (plan.volume("esp") if plan.esp_mount == "/boot" else None)
        root = plan.volume("root")
        assert root is not None
        if boot_vol is not None:
            boot_uuid, prefix = self.uuid(boot_vol.device), "/"
        else:
            boot_uuid = self.uuid(root.fs_device)
            prefix = "/@/boot/" if root.fs == "btrfs" else "/boot/"
        cfg = boot.BootConfig(
            bootloader=self.bootloader,
            firmware="uefi" if self.uefi else "bios",
            esp=plan.esp_mount if self.uefi else "/boot",
            boot_uuid=boot_uuid,
            boot_dir="/boot",
            kernel_prefix=prefix,
            bios_disk="" if self.uefi else (plan.disk or self._disk_of(root.device)),
            default_kernel="linux-surface" if self.surface_plan.enabled and self.online else "",
        )
        boot.install(self.target, cfg, self.runner, self.branding)
        if self.cfg.secure_boot == "sbctl" and self.uefi:
            self._secure_boot(cfg)

    def _disk_of(self, partition: str) -> str:
        return re.sub(r"p?\d+$", "", partition)

    def _secure_boot(self, cfg: boot.BootConfig) -> None:
        self.chroot(["sbctl", "create-keys"])
        if self.hw.firmware.setup_mode:
            # Keep Microsoft's keys: firmware option ROMs (GPUs) are signed with them.
            self.chroot(["sbctl", "enroll-keys", "--microsoft"])
        else:
            self.warnings.append("Secure Boot keys were created but not enrolled: the firmware is not in Setup Mode. "
                                 "Put it in Setup Mode and run `sudo sbctl enroll-keys --microsoft`.")
        for f in (f"{cfg.esp}/EFI/systemd/systemd-bootx64.efi", f"{cfg.esp}/EFI/BOOT/BOOTX64.EFI"):
            self.chroot(["sbctl", "sign", "-s", f], check=False)
        for k in self.cfg.kernels + (["linux-surface"] if self.surface_plan.enabled else []):
            self.chroot(["sbctl", "sign", "-s", f"/boot/vmlinuz-{k}"], check=False)

    def initramfs(self) -> None:
        self.chroot(["plymouth-set-default-theme", self.branding.id], check=False)
        self.chroot(["mkinitcpio", "-P"])
        if self.runner.dry_run:
            self.log("regenerate boot entries")
            return
        self.log(boot.update(self.target, self.runner, self.branding))

    # 6 -----------------------------------------------------------------------
    def desktop(self) -> None:
        installed = set(self.selection.packages)
        editors = load_editors()
        editor = editors.get(self.branding.get("CODE_EDITOR", "code"))
        settings = desktop_deploy.UserSettings(
            keyboard_layout=self.cfg.keyboard_layout,
            keyboard_variant=self.cfg.keyboard_variant,
            monitors=[{"connector": d.connector, "scale": d.recommended_scale}
                      for d in self.hw.displays if d.recommended_scale != 1.0],
            apps=desktop_deploy.default_apps(installed, editor.command if editor and self.features.get("code_editor") else ""),
        )
        if self.runner.dry_run:
            self.log(f"deploy desktop to {self.home} (keyboard {settings.keyboard_layout}, "
                     f"{len(settings.monitors)} scaled displays)")
            return
        share = self.t(f"/usr/share/{self.branding.id}")
        dep = desktop_deploy.Deployer(
            self.t(self.home), self.branding, dots=share / "desktop" / "dots", overlay=share / "desktop" / "overlay",
            wallpapers=share / "branding" / "generated" / "wallpapers", log=self.log, visible_home=Path(self.home),
        )
        report = dep.deploy(settings, first=True)
        self.log(f"Desktop: {len(report.written)} files")
        self.chroot(["chown", "-R", f"{self.user}:{self.user}", self.home])

    def services(self) -> None:
        units = list(SYSTEM_SERVICES)
        if self.features.get("firewall"):
            units.append("nftables.service")
        if self.features.get("containers") == "docker":
            units.append("docker.socket")
        if self.hw.chassis.portable and self.hw.cpu.vendor == "intel" and not self.hw.virt.is_virtual:
            units.append("thermald.service")
        virt_units = {"kvm": ["qemu-guest-agent.service"], "qemu": ["qemu-guest-agent.service"],
                      "oracle": ["vboxservice.service"], "vmware": ["vmtoolsd.service"],
                      "microsoft": ["hv_kvp_daemon.service", "hv_vss_daemon.service"]}
        units += virt_units.get(self.hw.virt.kind, [])
        if self.bootloader == "grub" and self.cfg.disk.filesystem == "btrfs" and self.features.get("snapshots"):
            units.append("grub-btrfsd.service")
        if self.bootloader == "systemd-boot":
            units.append("systemd-boot-update.service")  # updates the boot manager after systemd upgrades
        for unit in units:
            self.chroot(["systemctl", "enable", unit], check=False)
        # Per-user units every account gets (the dots use ydotool for the OSK).
        self.chroot(["systemctl", "--global", "enable", "pipewire.socket", "pipewire-pulse.socket", "wireplumber.service"],
                    check=False)

    def snapshots(self) -> None:
        self.chroot(["snapper", "--no-dbus", "-c", "root", "create-config", "/"])
        self.chroot(["sed", "-i",
                     "-e", 's/^TIMELINE_LIMIT_HOURLY=.*/TIMELINE_LIMIT_HOURLY="5"/',
                     "-e", 's/^TIMELINE_LIMIT_DAILY=.*/TIMELINE_LIMIT_DAILY="7"/',
                     "-e", 's/^TIMELINE_LIMIT_WEEKLY=.*/TIMELINE_LIMIT_WEEKLY="2"/',
                     "-e", 's/^TIMELINE_LIMIT_MONTHLY=.*/TIMELINE_LIMIT_MONTHLY="1"/',
                     "-e", 's/^TIMELINE_LIMIT_YEARLY=.*/TIMELINE_LIMIT_YEARLY="0"/',
                     "-e", 's/^ALLOW_GROUPS=.*/ALLOW_GROUPS="wheel"/',
                     "/etc/snapper/configs/root"])
        self.chroot(["systemctl", "enable", "snapper-timeline.timer", "snapper-cleanup.timer"], check=False)
        self.chroot(["snapper", "--no-dbus", "-c", "root", "create", "-d", "Fresh installation"], check=False)

    def aur_packages(self) -> None:
        if not self.missing_packages:
            return
        if not self.online:
            self.warnings.append("Offline: not installed: " + ", ".join(self.missing_packages))
            return
        pkg.aur_install(self.missing_packages, self.runner, self.target, self.user)

    def user_setup(self) -> None:
        feats = self.features
        queue = TaskQueue(self.branding, Path(self.home), self.target)
        dots_req = f"/usr/share/{self.branding.id}/desktop/dots/sdata/uv/requirements.txt"
        env = dict(self.backend.env)
        if self.runner.dry_run:
            queue.path = Path(tempfile.mkdtemp()) / "tasks.json"
            queue.root = Path("/")
        tasks = queue_for_install(
            queue,
            assistant=str(feats.get("assistant", "none")),
            hypernix=bool(feats.get("hypernix")),
            claude_code=bool(feats.get("claude_code")),
            backend_torch_index=self.backend.torch_index,
            backend_env=env,
            model=self.cfg.ai.model or None,
            custom_model=self.cfg.ai.custom_model,
            dots_requirements=dots_req,
        )
        if not tasks:
            return
        # A local model file lives on the installation medium: copy it now.
        local = [t.id for t in tasks if t.kind == "custom_model" and t.params["custom"].get("source") == "path"]
        if not self.online or self.cfg.ai.download == "first-boot":
            # Tools are small and quick; downloads wait for first boot when asked.
            only = [t.id for t in tasks if not t.id.startswith("model:")] if self.online else []
            only += local
            if not only:
                self.log("AI tools and models will be installed after the first login.")
                return
        else:
            only = [t.id for t in tasks]
        ctx = tools.UserContext(self.user, Path(self.home), self.target, self.runner, self.branding)
        failed = queue.run(ctx, self.log, lambda tid, done, total: self.emit(
            {"type": "download", "task": tid, "done": done, "total": total}), only=only)
        for t in failed:
            self.warnings.append(f"{t.label} could not be installed ({t.error}); it will be retried after the first login.")
        # Desktop entries for installed tools, visible only when installed.
        self._user_desktop_entries()

    def _user_desktop_entries(self) -> None:
        apps_dir = self.t(f"{self.home}/.local/share/applications")
        src = paths.data("desktop", "overlay", "applications", "user")
        if self.runner.dry_run or not src.is_dir():
            return
        home = self.t(self.home)
        for tmpl in src.glob("*.desktop.in"):
            tool_id = tmpl.name.removesuffix(".desktop.in")
            present = (home / ".local/bin" / ("hypernix" if tool_id == "hypernix" else
                                              {"hermis": "hermes", "openclaw": "openclaw", "claude-code": "claude"}[tool_id])).exists()
            if present:
                apps_dir.mkdir(parents=True, exist_ok=True)
                (apps_dir / f"{self.branding.id}-{tool_id}.desktop").write_text(self.branding.render(tmpl.read_text()))
        self.chroot(["chown", "-R", f"{self.user}:{self.user}", f"{self.home}/.local"], check=False)

    # 7 -----------------------------------------------------------------------
    def finish(self) -> None:
        sp = self.branding.system_paths(self.target)
        record = {
            "distribution": self.branding.pretty_name,
            "installer_version": __version__,
            "installed_at": int(time.time()),
            "config": self.cfg.to_dict(redact=True),
            "profile": self.profile.id,
            "features": self.features,
            "packages": self.packages(),
            "missing_packages": self.missing_packages,
            "gpu": self.gpu_plan.to_dict(),
            "ai_backend": self.backend.to_dict(),
            "surface": self.surface_plan.to_dict(),
            "disk": self.disk_plan.to_dict(),
            "warnings": self.warnings,
            "hardware_summary": self.hw.summary_rows(),
        }
        if self.runner.dry_run:
            self.log("write install record and hardware report")
            return
        util.write_json(sp.install_record, record)
        util.atomic_write(sp.hardware_report, self.hw.to_json() + "\n")
        util.write_json(self.t(f"/etc/{self.branding.id}/firstboot.json"), {"pending": True, "user": self.user})

    def cleanup(self, failed: bool = False) -> None:
        """Unmount everything and close encrypted volumes. On failure after
        creating partitions in free space, remove them again so the disk is
        as it was."""
        for sw in reversed(self.state.get("swap_on", [])):
            self.run(["swapoff", sw], check=False)
        if self.state.get("mounted") or failed:
            self.run(["umount", "-R", str(self.target)], check=False)
        for name in reversed(self.state.get("opened", [])):
            self.run(["cryptsetup", "close", name], check=False)
        if failed and self.disk_plan.mode == "free-space" and self.state.get("created_partitions"):
            nums = [str(n) for n in self.state["created_partitions"]]
            self.log(f"Removing the partitions this installation created ({', '.join(nums)}) to restore the free space.")
            self.run(["sfdisk", "--delete", self.disk_plan.disk, *nums], check=False)
            self.run(["partprobe", self.disk_plan.disk], check=False)
        self.run(["sync"], check=False)

    def install_log_copy(self, log_file: Path) -> None:
        if self.runner.dry_run or not log_file.exists():
            return
        dest = self.branding.system_paths(self.target).logs / "install.log"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(log_file.read_text())
        dest.chmod(0o600)


def summary(inst: Installation) -> dict[str, Any]:
    """What the installer's summary page shows."""
    feats = inst.features
    return {
        "disk": inst.disk_plan.to_dict(),
        "destructive": inst.disk_plan.summary,
        "warnings": inst.warnings,
        "bootloader": inst.bootloader,
        "firmware": "UEFI" if inst.uefi else "BIOS",
        "profile": inst.profile.name,
        "packages": len(inst.packages()),
        "gpu": inst.gpu_plan.describe(),
        "surface": inst.surface_plan.enabled,
        "ai": {
            "assistant": feats.get("assistant"),
            "hypernix": feats.get("hypernix"),
            "backend": inst.backend.description,
            "model": inst.cfg.ai.model,
            "download": inst.cfg.ai.download,
        },
        "user": inst.cfg.user.username,
        "hostname": inst.cfg.hostname,
        "locale": inst.cfg.locale,
        "timezone": inst.cfg.timezone,
        "keyboard": inst.cfg.keyboard_layout + (f" ({inst.cfg.keyboard_variant})" if inst.cfg.keyboard_variant else ""),
        "online": inst.online,
    }


def dry_run_commands(inst: Installation) -> list[str]:
    """Run every step in dry-run mode and return the shell-quoted commands."""
    assert inst.runner.dry_run
    for step in inst.steps():
        step.func()
    return [shlex.join(c) for c in inst.runner.recorded]
