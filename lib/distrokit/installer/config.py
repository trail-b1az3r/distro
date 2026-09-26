"""The installation configuration: everything the user chose, in one
JSON-serialisable structure shared by the graphical installer and unattended
installs (``<id>-install --config install.json``)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

RESERVED_USERS = {
    "root", "bin", "daemon", "mail", "ftp", "http", "nobody", "dbus", "systemd-journal-remote", "systemd-network",
    "systemd-oom", "systemd-resolve", "systemd-timesync", "systemd-coredump", "uuidd", "polkitd", "avahi", "git",
    "rtkit", "sddm", "colord", "geoclue", "usbmux", "nvidia-persistenced", "alpm", "tss", "flatpak", "docker",
    "wheel", "users", "video", "audio", "input", "adm", "sys", "tty", "disk", "storage", "network",
}
USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
HOSTNAME_RE = re.compile(r"^(?=.{1,63}$)[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$")
MIN_PASSPHRASE = 8


@dataclass
class MountSpec:
    """Manual partitioning: use an existing partition."""

    device: str
    mountpoint: str  # / /home /boot /efi swap
    format: bool = False
    filesystem: str = ""  # btrfs | ext4 | xfs | vfat | swap (when formatting)
    encrypt: bool = False


@dataclass
class DiskConfig:
    mode: str = "erase"  # erase | free-space | manual
    disk: str = ""  # /dev/nvme0n1 (erase, free-space)
    disk_size_bytes: int = 0  # recorded when chosen; re-checked before writing
    filesystem: str = "btrfs"  # btrfs | ext4
    encrypt: bool = False
    passphrase: str = ""
    swap: str = "zram"  # zram | partition | file | none
    swap_size_gib: int = 0  # 0 = automatic
    hibernation: bool = False
    separate_home: bool = False
    home_size_gib: int = 0  # 0 = automatic
    region_start_bytes: int = 0  # free-space: which gap (0 = largest)
    mounts: list[MountSpec] = field(default_factory=list)


@dataclass
class UserConfig:
    username: str = ""
    fullname: str = ""
    password: str = ""
    root_password: str = ""  # empty: root login disabled (sudo only)
    shell: str = "bash"  # login shell: bash | fish (terminals open Fish either way)
    autologin: bool = False


@dataclass
class AiConfig:
    model: str = ""  # catalogue id, or "" for none
    custom_model: dict[str, Any] | None = None  # CustomModel fields
    download: str = "now"  # now | first-boot
    backend: str = ""  # override (cuda, rocm, vulkan, xpu, cpu); "" = detected


@dataclass
class InstallConfig:
    locale: str = "en_US.UTF-8"
    timezone: str = "UTC"
    keyboard_layout: str = "us"
    keyboard_variant: str = ""
    hostname: str = ""
    user: UserConfig = field(default_factory=UserConfig)
    disk: DiskConfig = field(default_factory=DiskConfig)
    bootloader: str = "auto"  # auto | systemd-boot | grub
    secure_boot: str = "off"  # off | sbctl
    kernels: list[str] = field(default_factory=lambda: ["linux"])
    surface_kernel: bool = False
    profile: str = "standard"
    features: dict[str, Any] = field(default_factory=dict)  # overrides of the profile
    gpu_overrides: dict[str, str] = field(default_factory=dict)  # PCI slot -> driver stack
    multilib: bool = True
    ai: AiConfig = field(default_factory=AiConfig)
    extra_packages: list[str] = field(default_factory=list)
    rank_mirrors: bool = True
    offline: bool = False  # never touch the network (offline repository only)

    # -- (de)serialisation ---------------------------------------------------
    def to_dict(self, redact: bool = False) -> dict[str, Any]:
        d = asdict(self)
        if redact:
            d["user"]["password"] = "<redacted>" if self.user.password else ""
            d["user"]["root_password"] = "<redacted>" if self.user.root_password else ""
            d["disk"]["passphrase"] = "<redacted>" if self.disk.passphrase else ""
        return d

    def to_json(self, redact: bool = False) -> str:
        return json.dumps(self.to_dict(redact), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InstallConfig":
        def build(klass, raw):
            if not isinstance(raw, dict):
                raise ValueError(f"expected an object for {klass.__name__}")
            names = {f.name for f in fields(klass)}
            unknown = set(raw) - names
            if unknown:
                raise ValueError(f"unknown {klass.__name__} fields: {', '.join(sorted(unknown))}")
            kwargs = {}
            for f in fields(klass):
                if f.name not in raw:
                    continue
                value = raw[f.name]
                nested = NESTED.get((klass, f.name))
                if nested is MountSpec:
                    value = [build(MountSpec, m) for m in value]
                elif nested is not None:
                    value = build(nested, value)
                kwargs[f.name] = value
            return klass(**kwargs)

        return build(cls, data)

    @classmethod
    def load(cls, path: Path) -> "InstallConfig":
        return cls.from_dict(json.loads(Path(path).read_text()))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    field: str
    message: str
    severity: str = "error"  # error | warning

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


def available_timezones(root: Path = Path("/")) -> set[str]:
    base = root / "usr" / "share" / "zoneinfo"
    tzlist = base / "tzdata.zi"
    zones: set[str] = set()
    if (base / "zone1970.tab").is_file():
        for line in (base / "zone1970.tab").read_text().splitlines():
            if line and not line.startswith("#"):
                parts = line.split("\t")
                if len(parts) >= 3:
                    zones.add(parts[2])
    if tzlist.is_file():
        for line in tzlist.read_text().splitlines():
            if line.startswith(("Z ", "L ")):
                parts = line.split()
                zones.add(parts[1] if line.startswith("Z ") else parts[2])
    zones.add("UTC")
    return zones


def supported_locales(root: Path = Path("/")) -> set[str]:
    path = root / "usr" / "share" / "i18n" / "SUPPORTED"
    if not path.is_file():
        return set()
    return {line.split()[0] for line in path.read_text().splitlines() if line.strip() and "UTF-8" in line}


def validate(cfg: InstallConfig, *, uefi: bool, profiles: set[str], features: dict[str, Any] | None = None,
             disks: dict[str, int] | None = None, root: Path = Path("/"), check_system: bool = True) -> list[Issue]:
    """Check a configuration. ``disks`` maps installable disk paths to sizes."""
    issues: list[Issue] = []

    def err(f: str, m: str) -> None:
        issues.append(Issue(f, m))

    def warn(f: str, m: str) -> None:
        issues.append(Issue(f, m, "warning"))

    u = cfg.user
    if not USERNAME_RE.match(u.username):
        err("user.username", "Use lowercase letters, digits, '-' or '_', starting with a letter (max 32).")
    elif u.username in RESERVED_USERS:
        err("user.username", f"'{u.username}' is reserved by the system.")
    if not u.password:
        err("user.password", "A password is required.")
    elif len(u.password) < 6:
        warn("user.password", "This password is short.")
    if u.shell not in ("fish", "bash"):
        err("user.shell", "Choose fish or bash.")
    if ":" in u.fullname or "\n" in u.fullname:
        err("user.fullname", "The name cannot contain ':' or line breaks.")
    if not HOSTNAME_RE.match(cfg.hostname or ""):
        err("hostname", "Use letters, digits and '-' (max 63), not starting or ending with '-'.")

    if check_system:
        zones = available_timezones(root)
        if len(zones) > 1 and cfg.timezone not in zones:
            err("timezone", f"Unknown time zone '{cfg.timezone}'.")
        locales = supported_locales(root)
        if locales and cfg.locale not in locales:
            err("locale", f"Unsupported locale '{cfg.locale}'.")
    if not re.match(r"^[a-z]{2,3}(\([\w-]+\))?$|^[a-z]{2,3}(,[a-z]{2,3})*$", cfg.keyboard_layout):
        err("keyboard_layout", "Unknown keyboard layout.")

    if cfg.profile not in profiles:
        err("profile", f"Unknown profile '{cfg.profile}'.")
    for fid, value in cfg.features.items():
        if features is not None and fid not in features:
            err(f"features.{fid}", "Unknown feature.")

    bl = resolve_bootloader(cfg, uefi)
    if bl == "systemd-boot" and not uefi:
        err("bootloader", "systemd-boot needs UEFI firmware; use GRUB on BIOS systems.")
    if cfg.secure_boot == "sbctl" and not uefi:
        err("secure_boot", "Secure Boot is a UEFI feature.")
    if not cfg.kernels or any(not re.match(r"^linux(-[a-z0-9]+)?$", k) for k in cfg.kernels):
        err("kernels", "Choose at least one kernel (linux, linux-lts, linux-zen...).")

    d = cfg.disk
    if d.mode not in ("erase", "free-space", "manual"):
        err("disk.mode", "Choose erase, free-space or manual.")
    if d.filesystem not in ("btrfs", "ext4"):
        err("disk.filesystem", "Choose btrfs or ext4.")
    if d.encrypt and len(d.passphrase) < MIN_PASSPHRASE:
        err("disk.passphrase", f"The encryption passphrase must have at least {MIN_PASSPHRASE} characters.")
    if d.swap not in ("zram", "partition", "file", "none"):
        err("disk.swap", "Choose zram, partition, file or none.")
    if d.hibernation and d.swap in ("zram", "none"):
        err("disk.hibernation", "Hibernation needs a swap partition or swap file.")
    if d.mode in ("erase", "free-space"):
        if not d.disk:
            err("disk.disk", "Choose a disk.")
        elif disks is not None and d.disk not in disks:
            err("disk.disk", f"{d.disk} is not available for installation.")
        if d.separate_home and d.mode == "free-space":
            err("disk.separate_home", "A separate /home partition is only available when erasing a disk.")
    if d.mode == "manual":
        mps = [m.mountpoint for m in d.mounts]
        if "/" not in mps:
            err("disk.mounts", "Assign a partition to / (root).")
        if uefi and not ({"/boot", "/efi"} & set(mps)):
            err("disk.mounts", "UEFI systems need the EFI system partition mounted at /boot or /efi.")
        if len(set(mps)) != len(mps) and mps.count("swap") <= 1:
            err("disk.mounts", "Each mount point can be used once.")
        for m in d.mounts:
            if m.format and m.filesystem not in ("btrfs", "ext4", "xfs", "vfat", "swap"):
                err("disk.mounts", f"{m.device}: unsupported filesystem '{m.filesystem}'.")
            if m.encrypt and m.mountpoint not in ("/", "/home"):
                err("disk.mounts", f"{m.device}: only / and /home can be encrypted.")
            if m.encrypt and not m.format:
                err("disk.mounts", f"{m.device}: encrypting means formatting; enable 'format'.")
        root_enc = any(m.encrypt for m in d.mounts if m.mountpoint == "/")
        if root_enc and "/boot" not in mps:
            err("disk.mounts", "An encrypted root needs an unencrypted /boot (the EFI partition or a separate one).")
        if root_enc and d.passphrase == "":
            err("disk.passphrase", "Set the encryption passphrase.")
    if cfg.ai.download not in ("now", "first-boot"):
        err("ai.download", "Choose 'now' or 'first-boot'.")
    if cfg.offline and cfg.ai.download == "now" and (cfg.ai.model or cfg.ai.custom_model):
        warn("ai.download", "Offline installation: the model will be downloaded after first boot.")
    return issues


def resolve_bootloader(cfg: InstallConfig, uefi: bool) -> str:
    if cfg.bootloader != "auto":
        return cfg.bootloader
    return "systemd-boot" if uefi else "grub"


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]


NESTED = {
    (InstallConfig, "user"): UserConfig,
    (InstallConfig, "disk"): DiskConfig,
    (InstallConfig, "ai"): AiConfig,
    (DiskConfig, "mounts"): MountSpec,
}
