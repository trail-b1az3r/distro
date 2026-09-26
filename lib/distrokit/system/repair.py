"""Repairs: packages, boot, GPU drivers, the desktop, and rescuing an
installed system from the live ISO.

Every repair is a :class:`Plan`: a list of actions described in plain
language that the user sees (and confirms) before anything changes.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .. import boot, pkg, util
from ..branding import Branding, load as load_branding


@dataclass
class Action:
    description: str
    run: Callable[[], object]
    destructive: bool = False


@dataclass
class Plan:
    title: str
    actions: list[Action] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def describe(self) -> str:
        lines = [self.title]
        for i, a in enumerate(self.actions, 1):
            lines.append(f"  {i}. {a.description}" + ("  [changes files]" if a.destructive else ""))
        lines += [f"  note: {n}" for n in self.notes]
        return "\n".join(lines)

    def execute(self, log: Callable[[str], None] = print) -> list[str]:
        errors = []
        for a in self.actions:
            log(f"→ {a.description}")
            try:
                a.run()
            except Exception as exc:  # noqa: BLE001 - keep going, report at the end
                errors.append(f"{a.description}: {exc}")
                log(f"  failed: {exc}")
        return errors


def _pacman_running() -> bool:
    rc, _ = util.run_quiet(["pgrep", "-x", "pacman"])
    return rc == 0


def packages_plan(root: Path = Path("/"), runner: util.Runner | None = None, refresh: bool = True) -> Plan:
    runner = runner or util.Runner()
    plan = Plan("Repair the package manager")
    lock = root / "var/lib/pacman/db.lck"
    if lock.exists():
        if _pacman_running():
            plan.notes.append("pacman is running right now; the lock is in use and is left alone.")
        else:
            plan.actions.append(Action("Remove the stale pacman lock (no pacman process is running)", lock.unlink, True))
    plan.actions.append(Action(
        "Re-initialise the package signing keys (Arch, EndeavourOS)",
        lambda: [boot.in_root(runner, root, ["pacman-key", "--init"]),
                 boot.in_root(runner, root, ["pacman-key", "--populate", "archlinux", "endeavouros"])],
    ))
    if refresh:
        plan.actions.append(Action(
            "Update the keyrings first, then the whole system (pacman -Sy keyrings, then pacman -Su)",
            lambda: [boot.in_root(runner, root, ["pacman", "-Sy", "--needed", "--noconfirm", "archlinux-keyring", "endeavouros-keyring"]),
                     boot.in_root(runner, root, ["pacman", "-Su", "--noconfirm"])],
            True,
        ))

    def reinstall_broken() -> None:
        res = runner.run(["pacman", "--root", str(root), "-Qkq"], check=False, capture=True, mutating=False)
        broken = sorted({line.split()[0] for line in res.stdout.splitlines() if line.strip()})
        foreign = set(runner.run(["pacman", "--root", str(root), "-Qmq"], check=False, capture=True,
                                 mutating=False).stdout.split())
        repo_broken = [p for p in broken if p not in foreign]
        if repo_broken:
            boot.in_root(runner, root, ["pacman", "-S", "--noconfirm", *repo_broken])
        if broken and foreign & set(broken):
            runner._emit("AUR packages with missing files (reinstall with yay): " + " ".join(sorted(foreign & set(broken))))

    plan.actions.append(Action("Reinstall packages whose files are missing or damaged (pacman -Qk)", reinstall_broken, True))
    plan.actions.append(Action("Check dependencies between installed packages (pacman -Dk)",
                               lambda: boot.in_root(runner, root, ["pacman", "-Dk"], check=False)))
    return plan


def boot_plan(root: Path = Path("/"), runner: util.Runner | None = None, branding: Branding | None = None) -> Plan:
    runner = runner or util.Runner()
    branding = branding or load_branding()
    cfg = boot.load_config(root, branding)
    plan = Plan("Repair booting")
    if cfg is None:
        plan.notes.append(f"No /etc/{branding.id}/boot.conf: this system was not set up by the installer. "
                          "Only the initramfs will be rebuilt.")
    else:
        plan.actions.append(Action(f"Reinstall the {cfg.bootloader} boot loader to {cfg.esp}",
                                   lambda: boot.install(root, cfg, runner, branding), True))
    plan.actions.append(Action("Rebuild the initramfs for every kernel (mkinitcpio -P)",
                               lambda: boot.in_root(runner, root, ["mkinitcpio", "-P"]), True))
    if cfg is not None:
        plan.actions.append(Action("Regenerate boot menu entries for every installed kernel",
                                   lambda: runner._emit(boot.update(root, runner, branding)), True))
    return plan


def gpu_plan(root: Path = Path("/"), runner: util.Runner | None = None, branding: Branding | None = None,
             safe: bool = False, keep_overrides: bool = True, user: str | None = None) -> Plan:
    from ..gpu import apply as gpu_apply
    from ..gpu.plan import build_plan
    from ..hardware import detect

    runner = runner or util.Runner()
    branding = branding or load_branding()
    report = detect(root if str(root) != "/" else "/")
    state = gpu_apply.load_state(root, branding) or {}
    previous = {c["slot"]: c["stack"] for c in state.get("plan", {}).get("choices", [])}
    overrides = {s: st for s, st in previous.items() if keep_overrides and report.gpu(s)}
    if safe:
        # Fallback: open-source drivers everywhere (nouveau for NVIDIA).
        overrides = {g.slot: "nouveau" for g in report.gpus if g.vendor == "nvidia"}
    kernels = [k.pkgbase for k in boot.installed_kernels(root)] or ["linux"]
    compute = bool(state.get("plan", {}).get("compute_packages"))
    plan_obj = build_plan(report, kernels=kernels, compute=compute, overrides=overrides, branding=branding)
    title = "Reconfigure graphics drivers" + (" (safe mode: open-source drivers)" if safe else "")
    plan = Plan(title)
    for line in plan_obj.describe():
        plan.notes.append(line)
    installed = pkg.installed_packages(root)
    remove = [p for p in plan_obj.conflicts if p in installed]
    add = [p for p in plan_obj.all_packages if p not in installed]
    desc = []
    if add:
        desc.append("install " + ", ".join(add))
    if remove:
        desc.append("remove " + ", ".join(remove))
    plan.actions.append(Action(
        ("Packages: " + "; ".join(desc)) if desc else "Packages are already correct",
        lambda: gpu_apply.apply(plan_obj, root=root, runner=runner, branding=branding, user=user),
        True,
    ))
    return plan


def desktop_plan(home: Path | None = None, branding: Branding | None = None) -> Plan:
    from ..desktop.deploy import Deployer, UserSettings

    home = home or Path.home()
    branding = branding or load_branding()
    dep = Deployer(home, branding)
    plan = Plan("Reset the desktop to its defaults")
    plan.notes.append("Every file you changed, and your ~/.config/hypr/custom folder, is copied to "
                      f"~/.local/state/{branding.id}/desktop-backups/<date>/ first.")
    settings = UserSettings()
    record = util.read_json(branding.system_paths().install_record, {}) or {}
    cfg = record.get("config", {})
    if cfg:
        settings.keyboard_layout = cfg.get("keyboard_layout", "us")
        settings.keyboard_variant = cfg.get("keyboard_variant", "")
    plan.actions.append(Action("Restore Hyprland, the shell, terminal and app settings from the distribution defaults",
                               lambda: dep.reset(settings), True))
    return plan


# ---------------------------------------------------------------------------
# Rescue from the live ISO
# ---------------------------------------------------------------------------


@dataclass
class Found:
    root_device: str
    fstype: str
    encrypted_parent: str = ""


def find_installed(branding: Branding | None = None) -> list[dict]:
    """Candidate root partitions of installed systems (live ISO)."""
    res = util.run_quiet(["lsblk", "-J", "-p", "-o", "NAME,FSTYPE,LABEL,PARTTYPE,SIZE,MOUNTPOINTS"], timeout=15)[1]
    data = json.loads(res or "{}")
    found = []

    def walk(nodes, parent=None):
        for n in nodes:
            pt = (n.get("parttype") or "").lower()
            if n.get("fstype") in ("btrfs", "ext4", "xfs") and (pt == "4f68bce3-e8cd-4db1-96e7-fbcaf984b709" or n.get("label") == "ROOT"):
                found.append({"device": n["name"], "fstype": n["fstype"], "size": n.get("size"), "encrypted": False})
            if n.get("fstype") == "crypto_LUKS":
                found.append({"device": n["name"], "fstype": "crypto_LUKS", "size": n.get("size"), "encrypted": True})
            walk(n.get("children") or [], n)

    walk(data.get("blockdevices", []))
    return found


def mount_installed(device: str, target: Path, runner: util.Runner, passphrase: str = "") -> Path:
    """Unlock (if needed) and mount an installed system with its own fstab."""
    target.mkdir(parents=True, exist_ok=True)
    dev = device
    rc, fstype = util.run_quiet(["blkid", "-s", "TYPE", "-o", "value", device])
    if fstype.strip() == "crypto_LUKS":
        if not passphrase:
            raise ValueError("this partition is encrypted: a passphrase is needed")
        runner.run(["cryptsetup", "open", "--key-file=-", device, "cryptroot"], input=passphrase)
        dev = "/dev/mapper/cryptroot"
        rc, fstype = util.run_quiet(["blkid", "-s", "TYPE", "-o", "value", dev])
    opts = ["-o", "subvol=@"] if fstype.strip() == "btrfs" else []
    runner.run(["mount", *opts, dev, str(target)])
    fstab = target / "etc/fstab"
    if fstab.exists():
        runner.run(["mount", "--all", "--fstab", str(fstab), "--target-prefix", str(target)], check=False)
    return target


def unmount_installed(target: Path, runner: util.Runner) -> None:
    runner.run(["umount", "-R", str(target)], check=False)
    if Path("/dev/mapper/cryptroot").exists():
        runner.run(["cryptsetup", "close", "cryptroot"], check=False)


def sanitize_device(value: str) -> str:
    if not re.match(r"^/dev/[\w./-]+$", value):
        raise ValueError(f"not a device path: {value}")
    return value


def is_live_system(branding: Branding | None = None) -> bool:
    branding = branding or load_branding()
    return os.path.isdir("/run/archiso") or Path(f"/etc/{branding.id}/live").exists()
