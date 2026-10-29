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


def test_unpublished_distro_repo_is_switched_off_and_back_on(tmp_path):
    """pacman syncs nothing while one repository's database is missing, so the
    distribution repository is off until it is published, and the repair
    plan switches it to match."""
    b = load_branding()
    name = b.repo_name
    on = pacmanconf.render("target", b)
    off = pacmanconf.render("target", b, distro_repo=False)
    assert pacmanconf.distro_repo_enabled(on, b) and not pacmanconf.distro_repo_enabled(off, b)
    assert f"#[{name}]" in off and "repair packages" in off
    # Toggling rewrites only that section, in both directions and repeatedly.
    assert pacmanconf.set_distro_repo(on, False, b) == off
    assert pacmanconf.set_distro_repo(off, True, b) == on
    assert pacmanconf.set_distro_repo(pacmanconf.set_distro_repo(off, False, b), False, b) == off
    # A pacman.conf from before this, without the section, gets it before [endeavouros].
    bare = on.replace(pacmanconf.distro_repo_block(b), "")
    assert f"[{name}]" not in bare
    assert pacmanconf.set_distro_repo(bare, True, b) == on

    conf = tmp_path / "etc/pacman.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text(on)
    runner = util.Runner(dry_run=True)
    assert repair.distro_repo_action(tmp_path, b, None) is None  # unknown (offline): left alone
    assert repair.distro_repo_action(tmp_path, b, True) is None  # already right
    plan = repair.packages_plan(tmp_path, runner, branding=b, distro_repo=False)
    assert f"Turn off the {name} repository" in plan.describe()
    plan.actions[0].run()
    assert conf.read_text() == off
    plan = repair.packages_plan(tmp_path, runner, branding=b, distro_repo=True)
    assert f"Turn on the {name} repository" in plan.describe()
    plan.actions[0].run()
    assert conf.read_text() == on


def test_repo_command_switches_the_section(tmp_path, monkeypatch, capsys):
    from distrokit import cli

    b = load_branding()
    conf = tmp_path / "etc/pacman.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text(pacmanconf.render("target", b))
    monkeypatch.setattr(util, "escalate", lambda reason, argv=None: None)
    published = {"now": False}
    monkeypatch.setattr(pacmanconf, "distro_repo_published", lambda branding=None, timeout=8.0: published["now"])

    def repo(*args):
        return cli.main(["repo", *args, "--root", str(tmp_path)])

    assert repo() == 0 and "not published" in capsys.readouterr().out
    assert repo("auto") == 0 and not pacmanconf.distro_repo_enabled(conf.read_text(), b)
    assert repo("on") == 1 and not pacmanconf.distro_repo_enabled(conf.read_text(), b)  # would break pacman
    assert repo("on", "--force") == 0 and pacmanconf.distro_repo_enabled(conf.read_text(), b)
    assert repo("off") == 0 and not pacmanconf.distro_repo_enabled(conf.read_text(), b)
    published["now"] = None  # unreachable: left as it is
    assert repo("auto") == 1 and not pacmanconf.distro_repo_enabled(conf.read_text(), b)
    published["now"] = True
    assert repo("auto") == 0 and conf.read_text() == pacmanconf.render("target", b)


def test_interactive_updates_get_the_terminal(monkeypatch):
    """pacman's and yay's questions read the terminal: run without it, they
    read end-of-file and give up ("Packages to exclude: -> EOF")."""
    calls = []
    monkeypatch.setattr(util.shutil, "which", lambda exe, path=None: "/usr/bin/" + exe)

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def no_pipes(*a, **kw):
        raise AssertionError("an interactive update must not run behind pipes")

    monkeypatch.setattr(util.subprocess, "run", fake_run)
    monkeypatch.setattr(util.subprocess, "Popen", no_pipes)
    update.apply_aur(util.Runner(), interactive=True)
    cmd, kw = calls[-1]
    assert cmd == ["yay", "-Sua"] and not {"stdin", "stdout", "capture_output"} & set(kw)


def test_logs_stay_local_unless_sharing_is_on(tmp_path, monkeypatch):
    import io
    import tarfile

    from distrokit.system import logs

    b = type(load_branding())(dict(load_branding().values))  # a copy: the loaded branding is shared
    assert not logs.sharing_enabled(b, tmp_path)  # off by default
    logs.set_sharing(True, b, tmp_path)
    assert logs.sharing_enabled(b, tmp_path)
    logs.set_sharing(False, b, tmp_path)
    assert not logs.sharing_enabled(b, tmp_path)

    bundle = tmp_path / "x-report.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        data = b'[{"name": "Kernel", "status": "ok"}]'
        ti = tarfile.TarInfo("x-report/doctor.json")
        ti.size = len(data)
        tar.addfile(ti, io.BytesIO(data))
    assert "### doctor.json" in logs.summary(bundle) and '"Kernel"' in logs.summary(bundle)

    opened = []
    b.values["DISTRO_LOG_REPO"] = "someone/logs"
    monkeypatch.setattr(logs, "sharing_enabled", lambda branding=None, root="/": False)
    with pytest.raises(RuntimeError, match="sharing is off"):
        logs.send(bundle, b, open_browser=opened.append)
    assert not opened  # nothing leaves the computer while sharing is off
    monkeypatch.setattr(logs, "sharing_enabled", lambda branding=None, root="/": True)
    monkeypatch.setattr(logs.util, "which", lambda name: None)  # no GitHub CLI: the browser
    url = logs.send(bundle, b, open_browser=opened.append)
    assert url.startswith("https://github.com/someone/logs/issues/new?") and opened == [url]
    b.values["DISTRO_LOG_REPO"] = ""
    with pytest.raises(RuntimeError, match="no log repository"):
        logs.send(bundle, b, open_browser=opened.append)


def test_distro_repo_published_reads_the_database_url(monkeypatch):
    import urllib.error

    b = load_branding()
    seen = []

    def fake(code):
        def urlopen(req, timeout):
            seen.append((req.get_method(), req.full_url))
            if code == 200:
                class R:
                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        return False
                return R()
            if code is None:
                raise urllib.error.URLError("offline")
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
        return urlopen

    for code, want in ((200, True), (404, False), (503, None), (None, None)):
        monkeypatch.setattr(pacmanconf.urllib.request, "urlopen", fake(code))
        assert pacmanconf.distro_repo_published(b) is want
    server = b.get("DISTRO_REPO_SERVER").rstrip("/")
    assert seen[0] == ("HEAD", f"{server}/{b.repo_name}.db")


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
