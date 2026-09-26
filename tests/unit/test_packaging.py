"""Packaging: .SRCINFO parsing, dependency resolution, the source tarball,
PKGBUILD rendering, the per-package file layout and the pacman hook helpers."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from distrokit import hooks, paths, util
from distrokit.branding import load as load_branding
from distrokit.build import completions, packages, stage
from distrokit.build.packages import Node, SrcInfo, dep_name, parse_srcinfo, resolve

SRCINFO = """\
pkgbase = illogical-impulse-quickshell-git
\tpkgdesc = Quickshell pinned for illogical-impulse
\tpkgver = 0.1.0.r1
\tpkgrel = 3
\tepoch = 1
\tarch = x86_64
\tmakedepends = cmake
\tmakedepends = ninja
\tmakedepends_x86_64 = cli11
\tdepends = qt6-declarative
\tdepends = cpptrace
\tprovides = quickshell=0.1.0
\tconflicts = quickshell

pkgname = illogical-impulse-quickshell-git
\tdepends = qt6-declarative
\tdepends = jemalloc
"""


def test_parse_srcinfo_merges_split_and_arch_fields():
    info = parse_srcinfo(SRCINFO)
    assert info.pkgbase == "illogical-impulse-quickshell-git"
    assert info.version == "1:0.1.0.r1-3"
    assert info.makedepends == ["cmake", "ninja", "cli11"]
    assert info.depends == ["qt6-declarative", "cpptrace", "jemalloc"]
    assert info.provides == ["quickshell=0.1.0"]
    assert info.pkgnames == ["illogical-impulse-quickshell-git"]


def test_dep_name():
    assert dep_name("python>=3.11") == "python"
    assert dep_name("quickshell=0.1.0") == "quickshell"
    assert dep_name("vulkan-tools: Vulkan checks") == "vulkan-tools"


def _node(base, origin="aur", depends=(), makedepends=(), provides=(), names=None):
    info = SrcInfo(base, list(names or [base]), "1.0", "1", depends=list(depends), makedepends=list(makedepends),
                   provides=list(provides))
    return Node(base, origin, info, path=f"/src/{base}")


class FakeWorld:
    """Binary repositories and an AUR, for the resolver."""

    def __init__(self, repo, aur):
        self.repo = set(repo)
        self.aur = {n.pkgbase: n for n in aur}
        self.repo_queries = []
        self.aur_queries = []

    def in_repos(self, names):
        self.repo_queries.append(list(names))
        return {n for n in names if n in self.repo}

    def lookup(self, names):
        self.aur_queries.append(list(names))
        out = {}
        for name in names:
            for node in self.aur.values():
                if name in node.names():
                    out[name] = node
                    break
        return out


def test_resolver_orders_builds_and_prefers_local_then_repo():
    local = [
        _node("nexora", "local", depends=["python", "illogical-impulse-widgets"], names=["nexora-core", "nexora-desktop"]),
        _node("illogical-impulse-widgets", "local", depends=["fuzzel", "songrec", "hyprland"]),
        _node("illogical-impulse-quickshell-git", "local", depends=["cpptrace", "qt6-base"], provides=["quickshell"]),
    ]
    world = FakeWorld(
        repo={"python", "fuzzel", "hyprland", "qt6-base", "cmake", "rust", "git", "fish"},
        aur=[
            _node("songrec", makedepends=["rust", "libfoo-git"]),
            _node("libfoo-git", provides=["libfoo"]),
            _node("cpptrace", makedepends=["cmake"]),
            _node("quickshell", depends=["qt6-base"]),  # shadowed by the local provider
            _node("visual-studio-code-bin"),
        ],
    )
    plan = resolve(["fish", "nexora-core", "quickshell", "visual-studio-code-bin"], local, world.in_repos,
                   world.lookup, exclude=["visual-studio-code-bin"])
    assert set(plan.nodes) == {"nexora", "illogical-impulse-widgets", "illogical-impulse-quickshell-git",
                               "songrec", "libfoo-git", "cpptrace"}
    order = plan.order
    assert order.index("libfoo-git") < order.index("songrec") < order.index("illogical-impulse-widgets") < order.index("nexora")
    assert order.index("cpptrace") < order.index("illogical-impulse-quickshell-git")
    assert plan.excluded == ["visual-studio-code-bin"]
    assert plan.unresolved == {}
    # Repository packages were never looked up on the AUR.
    assert not any("fish" in q or "python" in q for q in world.aur_queries)
    assert "songrec" in plan.describe()


def test_resolver_reports_missing_and_cycles():
    world = FakeWorld(repo={"glibc"}, aur=[_node("a", depends=["b"]), _node("b", makedepends=["a"])])
    with pytest.raises(packages.CycleError, match="a, b"):
        resolve(["a"], [], world.in_repos, world.lookup)
    world = FakeWorld(repo=set(), aur=[_node("a", depends=["ghost>=2"])])
    plan = resolve(["a"], [], world.in_repos, world.lookup)
    assert plan.unresolved == {"ghost": ["a"]}


def test_wanted_packages_cover_lists_gpu_and_llama():
    b = load_branding()
    wanted = packages.wanted_packages(b)
    assert f"{b.id}-core" in wanted and "illogical-impulse-widgets" in wanted
    assert "nvidia-580xx-dkms" in wanted and "lib32-nvidia-580xx-utils" in wanted
    assert "llama.cpp-vulkan" in wanted and "llama.cpp-cuda" not in wanted
    assert "visual-studio-code-bin" not in wanted


def test_source_tarball_is_reproducible(tmp_path):
    src = paths.DATA_ROOT
    a = packages.source_tarball(src, tmp_path / "a.tar.gz", "x-1", 1700000000)
    b = packages.source_tarball(src, tmp_path / "b.tar.gz", "x-1", 1700000000)
    assert hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()
    import tarfile

    with tarfile.open(a) as tar:
        names = tar.getnames()
        assert "x-1/distro.conf" in names and "x-1/desktop/VERSION" in names
        assert any(n.startswith("x-1/desktop/dots/dots/.config/hypr/") for n in names)
        assert all(m.mtime == 1700000000 and m.uid == 0 for m in tar.getmembers())


def test_render_pkgbuilds(tmp_path):
    b = load_branding()
    out = packages.render(tmp_path, b)
    distro = (tmp_path / "distro" / "PKGBUILD").read_text()
    assert f"pkgbase={b.id}" in distro and f"package_{b.id}-installer()" in distro
    assert "@DISTRO" not in distro and "@PKGVER@" not in distro
    tarball = next((tmp_path / "distro").glob("*.tar.gz"))
    assert hashlib.sha256(tarball.read_bytes()).hexdigest() in distro
    fonts = (tmp_path / "fonts-google-sans-flex" / "PKGBUILD").read_text()
    assert f"pkgname={b.id}-fonts-google-sans-flex" in fonts
    for d in out:
        subprocess.run(["bash", "-n", str(d / "PKGBUILD")], check=True)
    # Every package function in the PKGBUILD stages a known component.
    for comp in stage.COMPONENTS:
        assert f"package_{b.id}-{comp}()" in distro and f"_stage {comp}" in distro


def test_stage_core_layout_and_entry_point(tmp_path):
    b = load_branding()
    stage.Stage(tmp_path, b).run("core")
    cli = tmp_path / "usr" / "bin" / b.cli
    assert cli.read_text().startswith("#!/usr/bin/python3 -I\n")
    assert os.access(cli, os.X_OK)
    assert os.readlink(tmp_path / "usr" / "bin" / f"{b.id}-gpu") == b.cli
    assert (tmp_path / f"usr/lib/{b.id}/distrokit/cli.py").is_file()
    assert not list((tmp_path / f"usr/lib/{b.id}").rglob("__pycache__"))
    assert (tmp_path / f"usr/share/{b.id}/profiles/standard.toml").is_file()
    hook = (tmp_path / f"usr/share/libalpm/hooks/95-{b.id}-boot.hook").read_text()
    assert "Target = usr/lib/modules/*/vmlinuz" in hook and f"Exec = /usr/lib/{b.id}/bin/{b.id}-update-boot" in hook
    policy = (tmp_path / f"usr/share/polkit-1/actions/org.{b.id}.privileged.policy").read_text()
    assert f"/usr/lib/{b.id}/bin/{b.id}-privileged" in policy and "auth_admin_keep" in policy
    assert (tmp_path / f"usr/lib/systemd/user/{b.id}-llm.service").is_file()

    # The staged CLI runs from the installed layout (code in /usr/lib/<id>,
    # data in /usr/share/<id>).
    code = f"import sys; sys.path.insert(0, {str(tmp_path / 'usr/lib' / b.id)!r}); from distrokit.cli import main; sys.exit(main())"
    env = dict(os.environ, DISTROKIT_DATA=str(tmp_path / "usr/share" / b.id))
    res = subprocess.run([sys.executable, "-c", code, "--version"], capture_output=True, text=True, env=env)
    assert res.returncode == 0 and b.pretty_name in res.stdout


def test_stage_desktop_and_apps(tmp_path):
    b = load_branding()
    s = stage.Stage(tmp_path, b)
    for comp in ("desktop", "welcome", "installer", "ai"):
        s.run(comp)
    share = tmp_path / f"usr/share/{b.id}"
    assert (share / "desktop/dots/dots/.config/hypr/hyprland.lua").is_file()
    assert not (share / "desktop/dots/.git").exists()
    version = (share / "desktop/VERSION").read_text().strip()
    assert len(version.split("+")[0]) == 40
    fish = (tmp_path / f"usr/share/fish/vendor_conf.d/{b.id}.fish").read_text()
    assert "@DISTRO" not in fish
    assert os.access(tmp_path / f"usr/lib/{b.id}/bin/{b.id}-session-start", os.X_OK)
    for app in ("welcome", "update", "installer", "ai"):
        assert (tmp_path / f"usr/bin/{b.id}-{app}").is_file()
    entry = (tmp_path / f"usr/share/applications/{b.id}-installer.desktop").read_text()
    assert "@" not in entry and b.name in entry


def test_completions_cover_every_command():
    from distrokit.cli import build_parser

    b = load_branding()
    parser = build_parser()
    bash = completions.bash(b, parser)
    fish = completions.fish(b, parser)
    for cmd in ("gpu", "doctor", "repair-gpu", "reset-desktop", "model", "iso"):
        assert cmd in bash and f"-a {cmd} " in fish
    assert "detect plan configure status" in bash
    subprocess.run(["bash", "-n"], input=bash, text=True, check=True)


def test_os_release_hook(tmp_path):
    b = load_branding()
    (tmp_path / "usr/lib").mkdir(parents=True)
    (tmp_path / "etc").mkdir()
    (tmp_path / "usr/lib/os-release").write_text('NAME="Arch Linux"\nID=arch\n')
    (tmp_path / "etc/issue").write_text("Arch Linux \\r (\\l)\n")
    (tmp_path / "etc/os-release").symlink_to("../usr/lib/os-release")
    changed = hooks.write_os_release(tmp_path, b)
    assert changed == ["/usr/lib/os-release", "/etc/issue"]
    text = (tmp_path / "etc/os-release").read_text()
    assert f'ID="{b.id}"' in text and 'ID_LIKE="endeavouros arch"' in text
    assert hooks.write_os_release(tmp_path, b) == []  # idempotent
    assert not (tmp_path / "etc/lsb-release").exists()  # only rewritten when installed


def test_update_boot_hook_without_config(tmp_path, capsys):
    assert hooks.update_boot_main([str(tmp_path)]) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_lock_pins_only_aur_packages(tmp_path):
    local = [_node("nexora", "local", depends=["songrec"], names=["nexora-core"])]
    world = FakeWorld(repo={"rust"}, aur=[_node("songrec", makedepends=["rust", "libfoo"]),
                                          _node("libfoo-git", provides=["libfoo"])])
    plan = resolve(["nexora-core"], local, world.in_repos, world.lookup)
    lock = packages.write_lock(plan, tmp_path / "aur.lock.json", head=lambda base: f"c0ffee-{base}")
    assert lock["packages"] == {
        "libfoo-git": {"version": "1.0-1", "commit": "c0ffee-libfoo-git", "for": ["libfoo"]},
        "songrec": {"version": "1.0-1", "commit": "c0ffee-songrec"},
    }
    import json

    assert json.loads((tmp_path / "aur.lock.json").read_text()) == lock


def test_committed_manifests_are_current():
    from distrokit.build import manifests

    out = paths.DATA_ROOT / "packages" / "manifests"
    for name, text in manifests.manifests().items():
        assert (out / name).read_text() == text, \
            f"packages/manifests/{name} is stale: python3 -m distrokit.build.manifests"
    assert "uv" in (out / "ai.txt").read_text().split()  # AI tools are installed with uv
    assert "illogical-impulse-hyprland" in (out / "minimal.txt").read_text()


FAKE_MAKEPKG = """#!/bin/sh
# Stand-in for makepkg --printsrcinfo: like the real one, it refuses a
# directory it cannot write to (E_FS_PERMISSIONS = 11).
echo "$PWD" >> "$MAKEPKG_CALLS"
[ -w . ] || { echo "==> ERROR: You do not have write permission for the directory \\$BUILDDIR ($PWD)." >&2; exit 11; }
name=$(sed -n 's/^pkgname=//p' PKGBUILD)
printf 'pkgbase = %s\\n\\tpkgver = 1.0\\n\\tpkgrel = 1\\n\\tdepends = glibc\\n\\npkgname = %s\\n' "$name" "$name"
"""


def test_printsrcinfo_uses_a_private_copy(tmp_path, monkeypatch):
    """makepkg never runs inside the checkout (which the build user may not
    be able to write to) and its error message is reported."""
    import os

    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "makepkg").write_text(FAKE_MAKEPKG)
    (bindir / "makepkg").chmod(0o755)
    calls = tmp_path / "calls"
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("MAKEPKG_CALLS", str(calls))
    pkgdir = tmp_path / "checkout" / "illogical-impulse-foo"
    pkgdir.mkdir(parents=True)
    (pkgdir / "PKGBUILD").write_text("pkgname=illogical-impulse-foo\n")
    pkgdir.chmod(0o555)
    try:
        info = packages.printsrcinfo(pkgdir)
    finally:
        pkgdir.chmod(0o755)
    assert info.pkgbase == "illogical-impulse-foo" and info.depends == ["glibc"]
    ran_in = calls.read_text().split()
    assert ran_in and all(d != str(pkgdir) for d in ran_in)
    assert [p.name for p in pkgdir.iterdir()] == ["PKGBUILD"]  # nothing written into the checkout

    (bindir / "makepkg").write_text("#!/bin/sh\necho '==> ERROR: PKGBUILD does not exist.' >&2\nexit 6\n")
    with pytest.raises(Exception, match="PKGBUILD does not exist"):
        packages.printsrcinfo(pkgdir)


def test_build_repository_section_matches_its_database(tmp_path):
    """pacman looks for <section>.db at the Server URL; repo-add writes
    <repo_name>.db. The build configuration must use the same name."""
    import re

    b = load_branding()
    repo = tmp_path / "repo"
    conf = packages.build_conf(b, repo, tmp_path / "work").read_text()
    sections = re.findall(r"^\[([^\]]+)\]\nSigLevel = [^\n]*\nServer = file://(.+)$", conf, re.M)
    local = [name for name, server in sections if server == str(repo.resolve())]
    builder = packages.Builder(b, repo, tmp_path / "work", tmp_path / "work/pacman-build.conf", "", util.Runner(dry_run=True))
    assert local == [builder.db.name.removesuffix(".db.tar.gz")]
    assert conf.index(f"[{local[0]}]") < conf.index("[core]")  # searched first


def _git(*args, cwd=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org", "GIT_CONFIG_GLOBAL": os.devnull}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def aur_git(tmp_path, monkeypatch):
    """An AUR package ``demo`` with two commits, served as the AUR serves it
    (one repository per package) and as its mirror does (one branch per
    package, same commits)."""
    work = tmp_path / "demo"
    work.mkdir()
    _git("init", "--quiet", cwd=work)
    commits = []
    for rel in ("1", "2"):
        (work / "PKGBUILD").write_text(f"pkgname=demo\npkgver=1.0\npkgrel={rel}\n")
        (work / ".SRCINFO").write_text(f"pkgbase = demo\n\tpkgver = 1.0\n\tpkgrel = {rel}\n\npkgname = demo\n")
        _git("add", "-A", cwd=work)
        _git("commit", "--quiet", "-m", rel, cwd=work)
        commits.append(_git("rev-parse", "HEAD", cwd=work))
    (tmp_path / "aur").mkdir()
    _git("clone", "--quiet", "--bare", str(work), str(tmp_path / "aur" / "demo.git"))
    _git("init", "--quiet", "--bare", str(tmp_path / "mirror.git"))
    _git("push", "--quiet", str(tmp_path / "mirror.git"), "HEAD:refs/heads/demo", cwd=work)
    monkeypatch.setattr(packages, "AUR", f"file://{tmp_path / 'aur'}")
    monkeypatch.setattr(packages, "AUR_MIRROR", f"file://{tmp_path / 'mirror.git'}")
    monkeypatch.setattr(packages, "RETRY_DELAY", 0)
    monkeypatch.setattr(packages, "_failing_hosts", set())
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    return tmp_path, commits


def test_aur_git_from_the_aur(aur_git):
    tmp, (first, head) = aur_git
    assert packages.aur_head("demo") == head
    d = packages.clone_aur("demo", first, tmp / "work")
    assert parse_srcinfo((d / ".SRCINFO").read_text()).version == "1.0-1"
    (d / "stray").write_text("left over from a build")
    d = packages.clone_aur("demo", head, tmp / "work")
    assert parse_srcinfo((d / ".SRCINFO").read_text()).version == "1.0-2"
    assert not (d / "stray").exists()


def test_aur_git_falls_back_to_the_mirror(aur_git, monkeypatch):
    """When the AUR's git service fails, the same commits come from the
    mirror, and a commit already fetched needs no network at all."""
    tmp, (first, head) = aur_git
    monkeypatch.setattr(packages, "AUR", f"file://{tmp / 'down'}")
    assert packages.aur_head("demo") == head
    d = packages.clone_aur("demo", first, tmp / "work")
    assert parse_srcinfo((d / ".SRCINFO").read_text()).version == "1.0-1"
    monkeypatch.setattr(packages, "AUR_MIRROR", f"file://{tmp / 'down.git'}")
    assert packages.clone_aur("demo", head, tmp / "work") == d
    assert parse_srcinfo((d / ".SRCINFO").read_text()).version == "1.0-2"


def test_aur_git_failures_explain_themselves(aur_git, monkeypatch):
    tmp, _ = aur_git
    with pytest.raises(packages.FetchError, match="--update-lock") as missing:
        packages.clone_aur("demo", "0" * 40, tmp / "work")
    assert "has no commit" in str(missing.value)
    with pytest.raises(packages.FetchError, match="not on the AUR"):
        packages.aur_head("absent")
    monkeypatch.setattr(packages, "AUR", f"file://{tmp / 'down'}")
    monkeypatch.setattr(packages, "AUR_MIRROR", f"file://{tmp / 'down.git'}")
    with pytest.raises(packages.FetchError) as down:
        packages.aur_head("demo")
    message = str(down.value)
    assert f"{tmp / 'down'}/demo.git" in message and "down.git (refs/heads/demo)" in message
    assert "network" in message and "Traceback" not in message
    monkeypatch.setattr(packages, "AUR_MIRROR", "")
    assert packages.aur_git_sources("demo") == [(f"file://{tmp / 'down'}/demo.git", "HEAD")]


def test_iso_build_reports_fetch_errors_without_a_traceback(monkeypatch, capsys):
    from distrokit.build import iso

    def fail(*a, **k):
        raise packages.FetchError("could not fetch the AUR package demo")

    monkeypatch.setattr(iso, "preflight", lambda opts: [])
    monkeypatch.setattr(iso, "build", fail)
    assert iso.main(["build"]) == 1
    assert "error: could not fetch the AUR package demo" in capsys.readouterr().err
    with pytest.raises(packages.FetchError):
        iso.main(["build", "--debug"])


def _builder(tmp_path, runner, sign=""):
    b = load_branding()
    conf = packages.build_conf(b, tmp_path / "repo", tmp_path / "work")
    return packages.Builder(b, tmp_path / "repo", tmp_path / "work", conf, "", runner, sign)


def test_builder_pacman_wrapper_uses_an_absolute_config(tmp_path, monkeypatch):
    """makepkg calls $PACMAN from the package's own directory."""
    monkeypatch.chdir(tmp_path)
    b = load_branding()
    conf = packages.build_conf(b, Path("build/repo"), Path("build/packages"))
    assert conf.is_absolute() and conf.is_file()
    builder = packages.Builder(b, Path("build/repo"), Path("build/packages"), Path("build/packages/pacman-build.conf"), "",
                               util.Runner(dry_run=True))
    builder.prepare()
    wrapper = builder.pacman_wrapper.read_text()
    assert f'--config "{tmp_path}/build/packages/pacman-build.conf"' in wrapper
    assert ["pacman", "--config", str(conf), "-Sy"] in builder.runner.recorded


def test_builder_installs_dependencies_itself_and_checks_signatures(tmp_path):
    """Build dependencies are installed by the (root) build, so makepkg never
    needs sudo; source signatures are checked with the build's own keyring."""
    runner = util.Runner(dry_run=True)
    builder = _builder(tmp_path, runner)
    pkgdir = tmp_path / "aur" / "wlogout"
    pkgdir.mkdir(parents=True)
    (pkgdir / "PKGBUILD").write_text("pkgname=wlogout\n")
    info = SrcInfo("wlogout", ["wlogout"], "1.2.2", "0", depends=["gtk3", "gtk-layer-shell"],
                   makedepends=["meson", "scdoc"], checkdepends=["xorg-server-xvfb"],
                   validpgpkeys=["F4FDB18A9937358364B276E9E25D679AF73C6D2F"])
    builder.build(Node("wlogout", "aur", info, path=str(pkgdir)))
    cmds = runner.recorded
    install = next(c for c in cmds if "-S" in c and "--asdeps" in c)
    assert install[:3] == ["pacman", "--config", str(builder.conf)]
    assert install[-4:] == ["gtk3", "gtk-layer-shell", "meson", "scdoc"]  # no checkdepends: AUR checks are skipped
    recv = next(c for c in cmds if "--recv-keys" in c)
    assert recv[:2] == ["env", f"GNUPGHOME={tmp_path / 'work' / 'gnupg'}"] and recv[-1] == info.validpgpkeys[0]
    makepkg = next(c for c in cmds if "makepkg" in c)
    assert f"GNUPGHOME={tmp_path / 'work' / 'gnupg'}" in makepkg and "--nocheck" in makepkg
    assert cmds.index(install) < cmds.index(recv) < cmds.index(makepkg)
    assert not any(c[0] == "sudo" for c in cmds)

    local = SrcInfo("demo", ["demo"], depends=["python"], checkdepends=["python-pytest"])
    (tmp_path / "demo").mkdir()
    runner.recorded.clear()
    builder.build(Node("demo", "local", local, path=str(tmp_path / "demo")))
    install = next(c for c in runner.recorded if "--asdeps" in c)
    assert install[-2:] == ["python", "python-pytest"]
    assert not any("--recv-keys" in c for c in runner.recorded)

    signing = _builder(tmp_path, util.Runner(dry_run=True), sign="ABCDEF")
    assert signing.gnupg is None  # signing uses the user's keyring


def test_builder_removes_the_dependencies_it_installed(tmp_path, monkeypatch):
    runner = util.Runner(dry_run=True)
    builder = _builder(tmp_path, runner)
    states = iter([{"base", "git"}, {"base", "git", "meson", "scdoc"}])
    monkeypatch.setattr(packages, "installed_packages", lambda: next(states))
    builder.installed_before = packages.installed_packages()
    builder.cleanup()
    assert runner.recorded[-1] == ["pacman", "-R", "--noconfirm", "meson", "scdoc"]
    builder.cleanup()  # once only
    assert len(runner.recorded) == 1


def test_native_builds_refuse_partial_upgrades(tmp_path, monkeypatch):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "checkupdates").write_text("#!/bin/sh\nprintf 'linux 6.1 -> 6.2\\nmesa 1 -> 2\\n'\n")
    (fake / "checkupdates").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:{os.environ['PATH']}")
    monkeypatch.setenv("ARCHIVE_DATE", "2026/09/01")
    monkeypatch.setattr(packages, "in_container", lambda: False)
    packages.host_problems.cache_clear()
    problems = packages.host_problems()
    assert len(problems) == 2
    assert "downgrade" in problems[0] and "2 pending updates" in problems[1]
    (fake / "checkupdates").write_text("#!/bin/sh\nexit 2\n")
    monkeypatch.delenv("ARCHIVE_DATE")
    packages.host_problems.cache_clear()
    assert packages.host_problems() == ()
    monkeypatch.setattr(packages, "in_container", lambda: True)
    monkeypatch.setenv("ARCHIVE_DATE", "2026/09/01")
    packages.host_problems.cache_clear()
    assert packages.host_problems() == ()
    packages.host_problems.cache_clear()
