"""Bootloader and kernel command line management.

The kernel command line is assembled from fragments in
``/etc/<id>/cmdline.d/*.conf`` (sorted by name):

=====================  ==================================================
``00-root.conf``       root device, subvolume, LUKS mapping (installer)
``10-quiet.conf``      quiet boot and splash
``20-gpu.conf``        GPU driver parameters (GPU manager)
``30-surface.conf``    Surface parameters
``40-resume.conf``     hibernation
``90-local.conf``      yours; never touched by the tools
=====================  ==================================================

``update()`` turns them into systemd-boot entries (one per installed kernel,
plus fallback and diagnostic entries) or into GRUB's configuration. A pacman
hook calls ``update()`` whenever a kernel is installed or removed, so every
kernel, including linux-surface or linux-lts, always has a boot entry.
"""

from __future__ import annotations

import re
import shutil
import shlex
from dataclasses import dataclass
from pathlib import Path

from . import util
from .branding import Branding, load as load_branding

DIAGNOSTIC_PARAMS = ["systemd.unit=multi-user.target", "systemd.show_status=1", "loglevel=6", "plymouth.enable=0"]
QUIET_PARAMS = ["quiet", "splash", "loglevel=3", "rd.udev.log_level=3", "systemd.show_status=auto", "vt.global_cursor_default=0"]
_GRUB_HANDLES = ("root=", "rootflags=")


@dataclass
class BootConfig:
    bootloader: str  # systemd-boot | grub
    firmware: str  # uefi | bios
    esp: str = "/boot"  # mount point of the EFI system partition
    boot_uuid: str = ""  # filesystem UUID of the partition holding kernels (/boot)
    boot_dir: str = "/boot"  # where kernels and boot entries live (ESP or XBOOTLDR)
    # Path of the kernels inside the filesystem with boot_uuid: "/" when /boot
    # is a partition, "/boot/" (or "/@/boot/" on Btrfs) when it is a directory.
    kernel_prefix: str = "/"
    bios_disk: str = ""  # BIOS/GRUB: disk grub is installed to
    default_kernel: str = ""  # kernel booted by default (e.g. linux-surface)

    def to_conf(self) -> str:
        return (
            f'BOOTLOADER="{self.bootloader}"\n'
            f'FIRMWARE="{self.firmware}"\n'
            f'ESP="{self.esp}"\n'
            f'BOOT_DIR="{self.boot_dir}"\n'
            f'KERNEL_PREFIX="{self.kernel_prefix}"\n'
            f'BOOT_UUID="{self.boot_uuid}"\n'
            f'BIOS_DISK="{self.bios_disk}"\n'
            f'DEFAULT_KERNEL="{self.default_kernel}"\n'
        )


def _sysconf(root: Path, branding: Branding) -> Path:
    return branding.system_paths(root).sysconf


def load_config(root: Path | str = "/", branding: Branding | None = None) -> BootConfig | None:
    branding = branding or load_branding()
    path = _sysconf(Path(root), branding) / "boot.conf"
    if not path.is_file():
        return None
    values = {}
    for line in path.read_text().splitlines():
        m = re.match(r'^([A-Z_]+)="(.*)"$', line.strip())
        if m:
            values[m.group(1)] = m.group(2)
    return BootConfig(
        bootloader=values.get("BOOTLOADER", "systemd-boot"),
        firmware=values.get("FIRMWARE", "uefi"),
        esp=values.get("ESP", "/boot"),
        boot_dir=values.get("BOOT_DIR", "/boot"),
        kernel_prefix=values.get("KERNEL_PREFIX", "/"),
        boot_uuid=values.get("BOOT_UUID", ""),
        bios_disk=values.get("BIOS_DISK", ""),
        default_kernel=values.get("DEFAULT_KERNEL", ""),
    )


def save_config(cfg: BootConfig, root: Path | str = "/", branding: Branding | None = None) -> None:
    branding = branding or load_branding()
    util.atomic_write(_sysconf(Path(root), branding) / "boot.conf", cfg.to_conf())


# ---------------------------------------------------------------------------
# Command line fragments
# ---------------------------------------------------------------------------


def cmdline_dir(root: Path | str = "/", branding: Branding | None = None) -> Path:
    branding = branding or load_branding()
    return _sysconf(Path(root), branding) / "cmdline.d"


def set_fragment(name: str, params: list[str], root: Path | str = "/", branding: Branding | None = None,
                 comment: str = "") -> Path:
    d = cmdline_dir(root, branding)
    path = d / f"{name}.conf"
    if not params:
        if path.exists():
            path.unlink()
        return path
    header = f"# {comment}\n" if comment else ""
    util.atomic_write(path, header + " ".join(params) + "\n")
    return path


def read_cmdline(root: Path | str = "/", branding: Branding | None = None) -> list[str]:
    d = cmdline_dir(root, branding)
    params: list[str] = []
    if not d.is_dir():
        return params
    for frag in sorted(d.glob("*.conf")):
        for line in frag.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                params.extend(shlex.split(line))
    # Later fragments override earlier key=value parameters with the same key.
    result: list[str] = []
    index: dict[str, int] = {}
    for p in params:
        key = p.split("=", 1)[0] if "=" in p else p
        if key in index and "=" in p:
            result[index[key]] = p
        elif p not in result:
            index[key] = len(result)
            result.append(p)
    return result


def diagnostic_cmdline(params: list[str]) -> list[str]:
    quiet_keys = {q.split("=")[0] for q in QUIET_PARAMS}
    kept = [p for p in params if p.split("=")[0] not in quiet_keys]
    return kept + DIAGNOSTIC_PARAMS


# ---------------------------------------------------------------------------
# Kernels
# ---------------------------------------------------------------------------


@dataclass
class Kernel:
    pkgbase: str
    version: str

    @property
    def image(self) -> str:
        return f"vmlinuz-{self.pkgbase}"

    @property
    def initramfs(self) -> str:
        return f"initramfs-{self.pkgbase}.img"

    @property
    def fallback_initramfs(self) -> str:
        return f"initramfs-{self.pkgbase}-fallback.img"


def installed_kernels(root: Path | str = "/") -> list[Kernel]:
    modules = Path(root) / "usr" / "lib" / "modules"
    kernels = []
    if modules.is_dir():
        for d in sorted(modules.iterdir()):
            pkgbase = d / "pkgbase"
            if pkgbase.is_file() and (d / "vmlinuz").is_file():
                kernels.append(Kernel(pkgbase.read_text().strip(), d.name))
    # "linux" first, then alphabetical: the default entry is the stock kernel
    # unless it is not installed.
    kernels.sort(key=lambda k: (k.pkgbase != "linux", k.pkgbase))
    return kernels


def default_kernel(kernels: list[Kernel], preferred: str = "") -> Kernel | None:
    if preferred:
        for k in kernels:
            if k.pkgbase == preferred:
                return k
    return kernels[0] if kernels else None


# ---------------------------------------------------------------------------
# systemd-boot
# ---------------------------------------------------------------------------


def _kernel_title(branding: Branding, kernel: Kernel) -> str:
    names = {
        "linux": "",
        "linux-lts": "LTS kernel",
        "linux-zen": "Zen kernel",
        "linux-surface": "Surface kernel",
        "linux-hardened": "hardened kernel",
    }
    extra = names.get(kernel.pkgbase, kernel.pkgbase)
    return f"{branding.pretty_name}" + (f" ({extra})" if extra else "")


def systemd_boot_entries(branding: Branding, kernels: list[Kernel], params: list[str], esp_root: Path,
                         default: str = "") -> dict[str, str]:
    """Entries to write, as {filename: content}."""
    entries: dict[str, str] = {}
    cmd = " ".join(params)
    diag = " ".join(diagnostic_cmdline(params))
    for i, k in enumerate(kernels):
        title = _kernel_title(branding, k)
        base = f"{branding.id}-{k.pkgbase}"
        entries[f"{base}.conf"] = (
            f"title   {title}\nsort-key {branding.id}-{i:02d}\nversion {k.version}\n"
            f"linux   /{k.image}\ninitrd  /{k.initramfs}\noptions {cmd}\n"
        )
        if (esp_root / k.fallback_initramfs).exists():
            entries[f"{base}-fallback.conf"] = (
                f"title   {title} — fallback initramfs\nsort-key {branding.id}-{i:02d}-fallback\nversion {k.version}\n"
                f"linux   /{k.image}\ninitrd  /{k.fallback_initramfs}\noptions {cmd}\n"
            )
        entries[f"{base}-diagnostic.conf"] = (
            f"title   {title} — diagnostic mode\nsort-key {branding.id}-{i:02d}-zdiag\nversion {k.version}\n"
            f"linux   /{k.image}\ninitrd  /{k.initramfs}\noptions {diag}\n"
        )
    return entries


def loader_conf(branding: Branding, default_entry: str, timeout: int = 3) -> str:
    return f"default {default_entry}\ntimeout {timeout}\nconsole-mode max\neditor no\n"


def write_systemd_boot(root: Path, branding: Branding, cfg: BootConfig, preferred_kernel: str = "") -> list[str]:
    esp_root = root / cfg.esp.lstrip("/")
    boot_root = root / cfg.boot_dir.lstrip("/")
    # Entries live next to the kernels: on the ESP, or on an XBOOTLDR
    # partition when the ESP is too small (dual boot). loader.conf is always
    # read from the ESP.
    entries_dir = boot_root / "loader" / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)
    kernels = installed_kernels(root)
    params = read_cmdline(root, branding)
    entries = systemd_boot_entries(branding, kernels, params, boot_root)
    # Remove our stale entries (kernels that were uninstalled); leave others alone.
    for old in entries_dir.glob(f"{branding.id}-*.conf"):
        if old.name not in entries:
            old.unlink()
    for name, content in entries.items():
        util.atomic_write(entries_dir / name, content, 0o644)
    kernel = default_kernel(kernels, preferred_kernel)
    if kernel:
        util.atomic_write(esp_root / "loader" / "loader.conf",
                          loader_conf(branding, f"{branding.id}-{kernel.pkgbase}.conf"))
    return sorted(entries)


# ---------------------------------------------------------------------------
# GRUB
# ---------------------------------------------------------------------------


def _set_grub_var(text: str, key: str, value: str) -> str:
    line = f'{key}="{value}"'
    pattern = re.compile(rf"^#?\s*{key}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(line, text, count=1)
    return text.rstrip("\n") + "\n" + line + "\n"


def grub_defaults(text: str, branding: Branding, params: list[str], theme: str = "") -> str:
    cmd = " ".join(p for p in params if not p.startswith(_GRUB_HANDLES) and p != "rw")
    # GRUB's 10_linux titles entries "<GRUB_DISTRIBUTOR> Linux".
    text = _set_grub_var(text, "GRUB_DISTRIBUTOR", branding.name)
    text = _set_grub_var(text, "GRUB_CMDLINE_LINUX_DEFAULT", cmd)
    text = _set_grub_var(text, "GRUB_TIMEOUT", "3")
    text = _set_grub_var(text, "GRUB_DISABLE_OS_PROBER", "false")
    text = _set_grub_var(text, "GRUB_GFXMODE", "auto")
    text = _set_grub_var(text, "GRUB_GFXPAYLOAD_LINUX", "keep")
    if theme:
        text = _set_grub_var(text, "GRUB_THEME", theme)
    return text


def grub_custom_cfg(branding: Branding, kernels: list[Kernel], params: list[str], boot_uuid: str,
                    kernel_prefix: str = "/") -> str:
    """Diagnostic-mode entries, sourced by GRUB's 41_custom script."""
    diag = " ".join(diagnostic_cmdline(params))
    blocks = [f"# Generated by {branding.cli}; regenerated when kernels change.\n"]
    for k in kernels:
        blocks.append(
            f"menuentry '{_kernel_title(branding, k)} — diagnostic mode' --class {branding.id} --class gnu-linux {{\n"
            f"    insmod part_gpt\n    insmod part_msdos\n    insmod fat\n    insmod ext2\n    insmod btrfs\n"
            f"    search --no-floppy --fs-uuid --set=root {boot_uuid}\n"
            f"    linux {kernel_prefix}{k.image} {diag}\n"
            f"    initrd {kernel_prefix}{k.initramfs}\n}}\n"
        )
    return "\n".join(blocks)


def _sync_grub_theme(root: Path, branding: Branding, cfg: BootConfig) -> str:
    """Copy the theme next to grub.cfg: GRUB reads it before the root file
    system is unlocked, and /boot is readable in every layout the installer
    creates. Returns the GRUB_THEME value ("" without a theme)."""
    src = root / "usr" / "share" / "grub" / "themes" / branding.id
    if not (src / "theme.txt").is_file():
        return ""
    rel = f"{cfg.boot_dir.rstrip('/')}/grub/themes/{branding.id}"
    dest = root / rel.lstrip("/")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    return f"{rel}/theme.txt"


def write_grub(root: Path, branding: Branding, cfg: BootConfig, runner: util.Runner, preferred_kernel: str = "") -> None:
    defaults = root / "etc" / "default" / "grub"
    params = read_cmdline(root, branding)
    theme_arg = _sync_grub_theme(root, branding, cfg)
    text = defaults.read_text() if defaults.is_file() else ""
    text = grub_defaults(text, branding, params, theme_arg)
    # GRUB sorts kernels by version; pin the preferred one with its menu id.
    kernel = default_kernel(installed_kernels(root), preferred_kernel)
    if kernel and preferred_kernel and kernel.pkgbase == preferred_kernel:
        text = _set_grub_var(text, "GRUB_DEFAULT", "saved")
        text = _set_grub_var(text, "GRUB_SAVEDEFAULT", "false")
    util.atomic_write(defaults, text)
    kernels = installed_kernels(root)
    grub_dir = root / cfg.boot_dir.lstrip("/") / "grub"
    grub_dir.mkdir(parents=True, exist_ok=True)
    if cfg.boot_uuid:
        util.atomic_write(grub_dir / "custom.cfg",
                          grub_custom_cfg(branding, kernels, params, cfg.boot_uuid, cfg.kernel_prefix))
    in_root(runner, root, ["grub-mkconfig", "-o", f"{cfg.boot_dir.rstrip('/')}/grub/grub.cfg"])
    if kernel and preferred_kernel and kernel.pkgbase == preferred_kernel:
        # grub-set-default takes the menu title; GRUB's 10_linux names entries
        # "Advanced options for <distro>><distro>, with Linux <pkgbase>".
        os_name = f"{branding.name} Linux"
        title = f"Advanced options for {os_name}>{os_name}, with Linux {kernel.pkgbase}"
        in_root(runner, root, ["grub-set-default", title], check=False)


# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------


def in_root(runner: util.Runner, root: Path | str, cmd: list[str], **kw) -> util.Result:
    """Run a command inside ``root`` (arch-chroot) or directly when root is /."""
    if str(root) in ("/", ""):
        return runner.run(cmd, **kw)
    return runner.run(["arch-chroot", str(root), *cmd], **kw)


def update(root: Path | str = "/", runner: util.Runner | None = None, branding: Branding | None = None,
           preferred_kernel: str = "") -> str:
    """Regenerate boot entries for all installed kernels. Returns what was done."""
    root = Path(root)
    branding = branding or load_branding()
    runner = runner or util.Runner()
    cfg = load_config(root, branding)
    if cfg is None:
        return "no boot configuration (/etc/{}/boot.conf); nothing to do".format(branding.id)
    preferred_kernel = preferred_kernel or cfg.default_kernel
    if cfg.bootloader == "systemd-boot":
        names = write_systemd_boot(root, branding, cfg, preferred_kernel)
        return f"systemd-boot: {len(names)} entries written"
    if cfg.bootloader == "grub":
        write_grub(root, branding, cfg, runner, preferred_kernel)
        return "grub: configuration regenerated"
    return f"unknown bootloader {cfg.bootloader!r}"


def install(root: Path, cfg: BootConfig, runner: util.Runner, branding: Branding) -> None:
    """Install the bootloader itself (installer and boot repair)."""
    if cfg.bootloader == "systemd-boot":
        if cfg.firmware != "uefi":
            raise ValueError("systemd-boot requires UEFI")
        cmd = ["bootctl", f"--esp-path={cfg.esp}"]
        if cfg.boot_dir != cfg.esp:
            cmd.append(f"--boot-path={cfg.boot_dir}")
        in_root(runner, root, [*cmd, "install"])
    elif cfg.bootloader == "grub":
        if cfg.firmware == "uefi":
            in_root(runner, root, [
                "grub-install", "--target=x86_64-efi", f"--efi-directory={cfg.esp}",
                f"--boot-directory={cfg.boot_dir}", f"--bootloader-id={branding.name}", "--recheck",
            ])
            # Also install to the fallback path so firmware that ignores
            # NVRAM boot entries (common on laptops) still finds it.
            in_root(runner, root, [
                "grub-install", "--target=x86_64-efi", f"--efi-directory={cfg.esp}",
                f"--boot-directory={cfg.boot_dir}", "--removable", "--recheck",
            ])
        else:
            if not cfg.bios_disk:
                raise ValueError("BIOS GRUB installation needs the target disk")
            in_root(runner, root, ["grub-install", "--target=i386-pc", "--recheck", cfg.bios_disk])
    else:
        raise ValueError(f"unknown bootloader {cfg.bootloader!r}")
    if runner.dry_run:
        runner._emit(f"write {_sysconf(Path(root), branding) / 'boot.conf'}")
    else:
        save_config(cfg, root, branding)
