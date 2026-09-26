"""The installer: configuration, validation and the complete installation
plan on fixture machines (dry run), plus the configuration files it writes."""

import shlex
import shutil
import stat
from pathlib import Path

import pytest

from distrokit import hardware, util
from distrokit.branding import load as load_branding
from distrokit.installer import config as cfgmod
from distrokit.installer.steps import Installation, dry_run_commands, summary
from distrokit.profiles import load_features, load_profiles

GiB = 2**30


def make_cfg(**over) -> cfgmod.InstallConfig:
    data = {
        "hostname": "box",
        "timezone": "Europe/Berlin",
        "user": {"username": "alex", "fullname": "Alex Doe", "password": "correct horse", "shell": "fish"},
        "disk": {"mode": "erase", "disk": "/dev/nvme0n1", "filesystem": "btrfs", "swap": "zram"},
    }
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    return cfgmod.InstallConfig.from_dict(data)


def issues(cfg, uefi=True):
    found = cfgmod.validate(cfg, uefi=uefi, profiles=set(load_profiles()), features=load_features(),
                            disks={"/dev/nvme0n1": 1024 * GiB, "/dev/vda": 64 * GiB}, check_system=False)
    return {i.field for i in cfgmod.errors(found)}


def test_roundtrip_and_redaction():
    cfg = make_cfg(disk={"encrypt": True, "passphrase": "sesame-sesame"}, kernel_params=["console=ttyS0,115200"])
    again = cfgmod.InstallConfig.from_dict(cfg.to_dict())
    assert again == cfg
    red = cfg.to_dict(redact=True)
    assert red["user"]["password"] == "<redacted>" and red["disk"]["passphrase"] == "<redacted>"
    assert red["user"]["root_password"] == ""


def test_unknown_fields_are_rejected():
    with pytest.raises(ValueError, match="unknown DiskConfig fields: size"):
        cfgmod.InstallConfig.from_dict({"disk": {"size": 1}})


@pytest.mark.parametrize("over, field", [
    ({"user": {"username": "Alex"}}, "user.username"),
    ({"user": {"username": "root"}}, "user.username"),
    ({"user": {"password": ""}}, "user.password"),
    ({"hostname": "-bad-"}, "hostname"),
    ({"disk": {"encrypt": True, "passphrase": "short"}}, "disk.passphrase"),
    ({"disk": {"swap": "zram", "hibernation": True}}, "disk.hibernation"),
    ({"bootloader": "grub", "secure_boot": "sbctl"}, "secure_boot"),
    ({"kernel_params": ["root=/dev/sda1"]}, "kernel_params"),
    ({"kernel_params": ["a b"]}, "kernel_params"),
    ({"profile": "gaming"}, "profile"),
    ({"kernels": ["windows"]}, "kernels"),
])
def test_validation_catches(over, field):
    assert field in issues(make_cfg(**over))


def test_bios_rules():
    assert "bootloader" in issues(make_cfg(bootloader="systemd-boot"), uefi=False)
    assert "secure_boot" in issues(make_cfg(secure_boot="sbctl"), uefi=False)
    assert not issues(make_cfg(bootloader="grub"), uefi=False)


def plan(machine, name, cfg, online=True):
    _root, report = machine(name)
    runner = util.Runner(dry_run=True)
    inst = Installation(cfg, report, runner=runner, branding=load_branding(), online=online)
    return inst, dry_run_commands(inst)


def find(cmds, *words):
    return [c for c in cmds if all(w in c for w in words)]


def test_encrypted_btrfs_uefi_plan_on_hybrid_laptop(machine):
    b = load_branding()
    cfg = make_cfg(profile="ai", disk={"encrypt": True, "passphrase": "disk-secret-123"},
                   user={"root_password": ""}, kernel_params=["mem_sleep_default=deep"])
    inst, cmds = plan(machine, "hybrid_gtx1080_laptop", cfg)
    assert inst.bootloader == "systemd-boot" and inst.uefi
    # Disk: wiped, partitioned, LUKS2, Btrfs with subvolumes.
    assert find(cmds, "wipefs --all --force /dev/nvme0n1")
    assert find(cmds, "sfdisk --wipe always", "/dev/nvme0n1")
    assert find(cmds, "cryptsetup", "luksFormat")
    assert find(cmds, "mkfs.btrfs")
    assert len(find(cmds, "btrfs subvolume create")) >= 4
    # Secrets never appear on a command line.
    assert not any("disk-secret-123" in c or "correct horse" in c for c in cmds)
    # Packages: GTX 1080 (Pascal) gets the 580 legacy branch, Intel microcode,
    # laptop tools, the Vulkan llama.cpp build for the AI profile.
    pac = find(cmds, "pacstrap -K -C")[0]
    for pkg in ("base", "linux", "intel-ucode", f"{b.id}-core", f"{b.id}-desktop", "nvidia-580xx-dkms",
                "nvidia-prime", "linux-headers", "llama.cpp-vulkan", "zram-generator"):
        assert f" {pkg} " in f" {pac} ", pkg
    assert " nvidia-open " not in f" {pac} "
    # Boot: systemd-boot, initramfs with plymouth, entries.
    assert find(cmds, "arch-chroot", "bootctl", "install")
    assert find(cmds, "plymouth-set-default-theme", b.id)
    assert find(cmds, "arch-chroot", "mkinitcpio -P")
    # User: fish shell, groups, root locked because no root password was given.
    useradd = find(cmds, "useradd -m")[0]
    assert "-s /usr/bin/fish" in useradd and "wheel" in useradd and useradd.endswith("alex")
    assert find(cmds, "passwd --lock root")
    for unit in ("NetworkManager.service", "sddm.service", "systemd-boot-update.service", "bluetooth.service"):
        assert find(cmds, "systemctl enable", unit), unit
    s = summary(inst)
    assert s["bootloader"] == "systemd-boot" and s["ai"]["hypernix"] is True
    assert any(line.startswith("ERASE") for line in s["destructive"])


def test_bios_ext4_grub_plan_in_vm(machine):
    cfg = make_cfg(disk={"disk": "/dev/vda", "filesystem": "ext4", "swap": "partition", "separate_home": True},
                   bootloader="grub", profile="minimal", user={"root_password": "toor-toor", "shell": "bash"})
    root, _report = machine("qemu_vm")
    shutil.rmtree(root / "sys/firmware/efi")  # the same VM booted with SeaBIOS
    report = hardware.detect(root)
    inst = Installation(cfg, report, runner=util.Runner(dry_run=True), branding=load_branding(), online=True)
    cmds = dry_run_commands(inst)
    assert inst.bootloader == "grub" and not inst.uefi
    assert find(cmds, "grub-install --target=i386-pc", "/dev/vda")
    assert not [c for c in cmds if c.startswith("cryptsetup")]
    assert find(cmds, "mkfs.ext4") and find(cmds, "mkswap")
    pac = find(cmds, "pacstrap")[0]
    assert "qemu-guest-agent" in pac and "grub" in pac and "nvidia" not in pac
    assert find(cmds, "systemctl enable qemu-guest-agent.service")
    assert not find(cmds, "passwd --lock root")
    assert "-s /bin/bash" in find(cmds, "useradd -m")[0]


def test_offline_install_queues_downloads_but_copies_local_model(machine, tmp_path):
    model = tmp_path / "tiny-model-Q4_K_M.gguf"
    model.write_bytes(b"GGUF" + b"\0" * 64)
    cfg = make_cfg(profile="ai", ai={"custom_model": {"source": "path", "path": str(model)}, "download": "now"})
    _root, report = machine("rtx4080_desktop")
    lines = []
    runner = util.Runner(dry_run=True, log=lines.append)
    inst = Installation(cfg, report, runner=runner, online=False)
    inst.user_setup()
    assert any("install custom model tiny-model-q4-k-m from path" in line for line in lines)
    assert not any("uv tool install" in line for line in lines)  # tools wait for the network


def test_configuration_files_written_to_target(machine, tmp_path, monkeypatch):
    """configure_system for real, into a scratch target (chroot commands stubbed)."""
    b = load_branding()
    cfg = make_cfg(keyboard_layout="de", keyboard_variant="nodeadkeys", locale="de_DE.UTF-8",
                   user={"autologin": True}, disk={"encrypt": True, "passphrase": "disk-secret-123"},
                   kernel_params=["console=ttyS0,115200"])
    _root, report = machine("rtx4080_desktop")
    target = tmp_path / "target"
    (target / "etc").mkdir(parents=True)
    (target / "etc/locale.gen").write_text("#de_DE.UTF-8 UTF-8\n#en_US.UTF-8 UTF-8\n#fr_FR.UTF-8 UTF-8\n")
    chrooted = []
    inst = Installation(cfg, report, runner=util.Runner(), branding=b, target=target, online=True)
    monkeypatch.setattr(inst, "chroot", lambda cmd, **kw: chrooted.append(cmd) or util.Result(cmd, 0, "", ""))
    monkeypatch.setattr(inst, "uuid", lambda dev: f"UUID-{Path(dev).name}")
    for v in inst.disk_plan.volumes:
        v.device = v.device or f"/dev/fake-{v.role}"
    inst.configure_system()

    etc = target / "etc"
    assert (etc / "locale.gen").read_text().splitlines()[:2] == ["de_DE.UTF-8 UTF-8", "en_US.UTF-8 UTF-8"]
    assert (etc / "locale.conf").read_text() == "LANG=de_DE.UTF-8\n"
    assert "KEYMAP=de-latin1-nodeadkeys" in (etc / "vconsole.conf").read_text() or "KEYMAP=de" in (etc / "vconsole.conf").read_text()
    assert 'Option "XkbVariant" "nodeadkeys"' in (etc / "X11/xorg.conf.d/00-keyboard.conf").read_text()
    assert (etc / "hostname").read_text() == "box\n"
    assert f"[{b.repo_name}]" in (etc / "pacman.conf").read_text()
    assert "sd-encrypt" in (etc / f"mkinitcpio.conf.d/10-{b.id}.conf").read_text()
    sudoers = etc / f"sudoers.d/10-{b.id}-wheel"
    assert stat.S_IMODE(sudoers.stat().st_mode) == 0o440
    assert "User=alex" in (etc / f"sddm.conf.d/20-{b.id}-autologin.conf").read_text()
    frags = etc / b.id / "cmdline.d"
    root = (frags / "00-root.conf").read_text()
    assert "rd.luks.name=UUID-" in root and "rootflags=subvol=@" in root
    assert (frags / "50-install.conf").read_text().strip().endswith("console=ttyS0,115200")
    assert ["locale-gen"] in chrooted
    assert ["ln", "-sf", "/usr/share/zoneinfo/Europe/Berlin", "/etc/localtime"] in chrooted


def test_missing_packages_come_from_aur_after_install(machine, monkeypatch):
    cfg = make_cfg()
    _root, report = machine("rtx4080_desktop")
    inst = Installation(cfg, report, runner=util.Runner(dry_run=True), online=True)
    monkeypatch.setattr(inst, "split_available", lambda pk, conf: ([p for p in pk if p != "some-aur-pkg"], ["some-aur-pkg"]))
    inst.cfg.extra_packages = ["some-aur-pkg"]
    inst.pacstrap()
    assert "some-aur-pkg" in inst.missing_packages
    monkeypatch.setattr(inst, "split_available", lambda pk, conf: ([], ["linux"]))
    with pytest.raises(Exception, match="essential packages are unavailable: linux"):
        inst.pacstrap()


def test_dry_run_commands_are_valid_shell(machine):
    _inst, cmds = plan(machine, "surface_pro7", make_cfg(disk={"mode": "free-space"}, surface_kernel=True))
    for c in cmds:
        shlex.split(c)
    assert find(cmds, "sfdisk --append")  # Windows is kept
    assert not find(cmds, "wipefs")
