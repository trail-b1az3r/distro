"""The command-line tool, doctor, repair plans, updater parsing and the
pacman configurations."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from distrokit import pacmanconf, util
from distrokit.branding import load as load_branding
from distrokit.system import doctor, repair, update

REPO = Path(__file__).resolve().parents[2]


def cli(*args, argv0=None, root_env=None):
    env = dict(os.environ, PYTHONPATH=str(REPO / "lib"), NO_COLOR="1")
    code = "import sys; from distrokit.cli import main; sys.exit(main())"
    cmd = [sys.executable, "-c", code, *args]
    if argv0:
        code = f"import sys; sys.argv[0] = {argv0!r}; from distrokit.cli import main; sys.exit(main())"
        cmd = [sys.executable, "-c", code, *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)


def test_version_and_help():
    b = load_branding()
    res = cli("--version")
    assert res.returncode == 0 and f"{b.cli} " in res.stdout and b.pretty_name in res.stdout
    res = cli("--help")
    for cmd in ("system", "gpu", "update", "install", "ai", "model", "doctor", "hardware", "installer", "iso",
                "repair", "reset-desktop", "repair-gpu"):
        assert cmd in res.stdout, cmd


def test_gpu_detect_output_format(machine):
    root, _report = machine("hybrid_gtx1080_laptop")
    res = cli("gpu", "detect", "--root", str(root))
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert out.startswith("GPU Detection")
    for line in ("Vendor        NVIDIA", "Model         GeForce GTX 1080 Mobile", "Type          discrete",
                 "Architecture  pascal", "Vendor        Intel", "Type          integrated"):
        assert line in out, line
    assert "Plan (hybrid)" in out and "prime-run" in out
    # `<id>-gpu detect` and `distro-gpu detect` are the same command.
    b = load_branding()
    for exe in (f"/usr/bin/{b.id}-gpu", "/usr/bin/distro-gpu"):
        alias = cli("detect", "--root", str(root), argv0=exe)
        assert alias.returncode == 0 and alias.stdout == out


def test_gpu_detect_json(machine):
    root, _report = machine("rtx4080_desktop")
    res = cli("gpu", "detect", "--json", "--root", str(root))
    data = json.loads(res.stdout)
    text = json.dumps(data)
    assert "nvidia-open" in text and "RTX 4080" in text


def test_hardware_json(machine):
    root, _report = machine("surface_pro7")
    data = json.loads(cli("hardware", "--json", "--root", str(root)).stdout)
    assert data["chassis"]["sys_vendor"] == "Microsoft Corporation"
    assert any(d["name"] == "nvme0n1" for d in data["disks"])


def test_doctor_reports_problems_with_fixes(machine):
    root, _report = machine("rtx4080_desktop")
    res = cli("doctor", "--json", "--root", str(root))
    results = json.loads(res.stdout)
    by_name = {r["name"]: r for r in results}
    assert by_name["Kernel"]["status"] == "fail" and by_name["Kernel"]["fix"]
    assert res.returncode == 1  # critical problems
    text = cli("doctor", "--root", str(root)).stdout
    assert text.startswith("System Doctor") and "fix: " in text


def test_doctor_healthy_system(tmp_path):
    """A minimal but complete installed-system tree passes the core checks."""
    b = load_branding()
    root = tmp_path
    (root / "usr/lib/modules/6.16.1-arch1-1").mkdir(parents=True)
    (root / "usr/lib/modules/6.16.1-arch1-1/vmlinuz").write_bytes(b"k")
    (root / "usr/lib/modules/6.16.1-arch1-1/pkgbase").write_text("linux\n")
    results = {r.name: r for r in doctor.Doctor(root, b, user_home=tmp_path / "home").run()}
    assert results["Kernel"].status != "fail"


def test_model_list_and_iso_info():
    res = cli("model", "list")
    assert res.returncode == 0 and "qwen3-8b" in res.stdout
    res = cli("iso", "info")
    assert res.returncode == 1 and "Not running from the live ISO" in res.stdout


def test_repair_plans_describe_before_acting(tmp_path):
    b = load_branding()
    runner = util.Runner(dry_run=True)
    (tmp_path / "var/lib/pacman").mkdir(parents=True)
    (tmp_path / "var/lib/pacman/db.lck").write_text("")
    plan = repair.packages_plan(tmp_path, runner)
    text = plan.describe()
    assert "stale pacman lock" in text and "keyrings" in text
    assert runner.recorded == []  # describing changes nothing
    boot_plan = repair.boot_plan(tmp_path, runner, b)
    assert "was not set up by the installer" in boot_plan.describe()
    with pytest.raises(ValueError):
        repair.sanitize_device("/dev/sda1; rm -rf /")
    assert repair.sanitize_device("/dev/mapper/root") == "/dev/mapper/root"


def test_update_parsers(tmp_path):
    items = update._parse_updates("linux 6.16.1.arch1-1 -> 6.16.2.arch1-1\nnot an update\nmesa 1:25.1-1 -> 1:25.2-1\n")
    assert [(i.name, i.current, i.new) for i in items] == [("linux", "6.16.1.arch1-1", "6.16.2.arch1-1"),
                                                            ("mesa", "1:25.1-1", "1:25.2-1")]
    log = tmp_path / "var/log/pacman.log"
    log.parent.mkdir(parents=True)
    log.write_text("[2026-09-01T10:00:00+0200] [PACMAN] starting full system upgrade\n"
                   "[2026-09-20T08:30:00+0200] [PACMAN] starting full system upgrade\n"
                   "[2026-09-21T08:30:00+0200] [ALPM] upgraded linux\n")
    assert update.last_update_time(tmp_path) > update.last_update_time(tmp_path.parent / "none")


def test_desktop_update_detection(tmp_path, monkeypatch):
    b = load_branding()
    monkeypatch.setattr(update, "desktop_version", lambda: "abc123def4567890+ffff")
    src = update.check_desktop(tmp_path, b)
    assert src.count == 1 and src.items[0].current == "(first deployment)"
    state = tmp_path / f".local/state/{b.id}"
    state.mkdir(parents=True)
    (state / "desktop-version").write_text("abc123def4567890+ffff\n")
    assert update.check_desktop(tmp_path, b).count == 0


@pytest.mark.parametrize("kind", ["target", "live", "offline", "build"])
def test_pacman_configs(kind):
    b = load_branding()
    text = pacmanconf.render(kind, b, offline_repo="/var/cache/x/repo", archive_date="2026/09/01")
    assert "[options]" in text and "SigLevel    = Required DatabaseOptional" in text
    has = {repo: f"[{repo}]" in text for repo in ("core", "extra", "multilib", "endeavouros", b.repo_name,
                                                   f"{b.repo_name}-offline")}
    if kind == "offline":
        assert has == {"core": False, "extra": False, "multilib": False, "endeavouros": False,
                       b.repo_name: False, f"{b.repo_name}-offline": True}
    else:
        assert has["core"] and has["extra"] and has["multilib"] and has["endeavouros"]
        # Only installed systems use the published repository; the ISO carries its packages.
        assert has[b.repo_name] == (kind == "target")
        assert has[f"{b.repo_name}-offline"] == (kind in ("live", "build"))
    if kind == "build":
        assert "archive.archlinux.org/repos/2026/09/01/$repo/os/$arch" in text
    assert "[multilib]" not in pacmanconf.render(kind, b, multilib=False)
    # The offline repository is searched first when present.
    if f"[{b.repo_name}-offline]" in text and kind != "offline":
        assert text.index(f"[{b.repo_name}-offline]") < text.index("[core]")


def test_doctor_boot_directory_needs_mounting_only_when_it_is_a_partition(tmp_path):
    """BIOS + GRUB on ext4 keeps /boot on the root file system: not a mount
    point, and not a problem. An ESP or XBOOTLDR at /boot must be mounted."""
    from distrokit import boot

    b = load_branding()
    root = tmp_path
    (root / "usr/lib/modules/6.16.1-arch1-1").mkdir(parents=True)
    (root / "usr/lib/modules/6.16.1-arch1-1/vmlinuz").write_bytes(b"k")
    (root / "usr/lib/modules/6.16.1-arch1-1/pkgbase").write_text("linux\n")
    (root / "boot/grub").mkdir(parents=True)
    for name in ("vmlinuz-linux", "initramfs-linux.img", "grub/grub.cfg"):
        (root / "boot" / name).write_text("x")
    doc = doctor.Doctor(root, b, user_home=tmp_path / "home")
    doc.live = True  # as on the running system, where mount points are checked

    boot.save_config(boot.BootConfig("grub", "bios", kernel_prefix="/boot/", bios_disk="/dev/vda"), root, b)
    assert doc.bootloader().status == "ok"
    boot.save_config(boot.BootConfig("systemd-boot", "uefi", kernel_prefix="/"), root, b)
    check = doc.bootloader()
    assert check.status == "fail" and "not mounted" in check.summary
