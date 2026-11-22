"""Spire Shell as a login shell: its Zsharpend edition (spire-shell's z#nd branch), packaged with Whetstone."""

import re
from pathlib import Path

from distrokit.branding import load as load_branding
from distrokit.build import iso, packages


def test_the_package_is_pinned_and_tested(tmp_path):
    b = load_branding()
    out = packages.render(tmp_path, b)
    pkgbuild = next(d for d in out if d.name == "spire-shell") / "PKGBUILD"
    text = pkgbuild.read_text()
    assert re.search(r"^_spire=dfaf97d85282484a24100111bfd930f29617d17d$", text, re.M)   # branch z#nd
    assert re.search(r"^_znd=0e76f62f310f94f49c2628dcf978e17cc7c8203b$", text, re.M)     # Whetstone
    assert "spire-shell.git#commit=${_spire}" in text and "z-nd.git#commit=${_znd}" in text
    assert "tests/run.sh" in text.split("check()")[1]
    assert "/usr/bin/spire" in text and "WHETSTONE=/usr/lib/spire/whetstone" in text
    install = (pkgbuild.parent / "spire-shell.install").read_text()
    assert "etc/shells" in install and "pre_remove" in install


def test_the_installer_installs_it_offline_too():
    from distrokit.installer import steps as steps_module

    steps = Path(steps_module.__file__).read_text()
    assert '"spire": ["spire-shell"]' in steps and '"spire": "/usr/bin/spire"' in steps
    assert "git clone --depth 1 https://github.com/trail-b1az3r/spire-shell" not in steps
    assert "requires an internet connection" not in steps
    assert "spire-shell" in Path(iso.__file__).read_text()   # in the offline sets, and in nano's when chosen


def test_an_old_main_branch_spire_is_replaced(tmp_path):
    from distrokit.system import update

    old = tmp_path / "usr/local/bin/spire"
    old.parent.mkdir(parents=True)
    old.write_text("#!/bin/sh\n")
    assert update.old_spire(tmp_path, installed=set())
    assert not update.old_spire(tmp_path, installed={"spire-shell"})
    old.unlink()
    old.symlink_to("/usr/bin/spire")      # already moved over
    assert not update.old_spire(tmp_path, installed=set())


def test_the_install_script_moves_the_old_one_aside(tmp_path):
    import subprocess

    b = load_branding()
    out = packages.render(tmp_path / "out", b)
    script = (next(d for d in out if d.name == "spire-shell") / "spire-shell.install").read_text()
    root = tmp_path / "root"
    (root / "usr/local/bin").mkdir(parents=True)
    (root / "etc").mkdir()
    (root / "usr/local/bin/spire").write_text("old main-branch build\n")
    (root / "etc/passwd").write_text("me:x:1000:1000::/home/me:/usr/local/bin/spire\n")
    (root / "etc/shells").write_text("/bin/bash\n/usr/local/bin/spire\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "usermod").write_text(f"#!/bin/sh\necho \"$@\" >> {tmp_path}/usermod.log\n")
    (bin_ / "usermod").chmod(0o755)
    import os
    env = {"PATH": f"{bin_}:{os.environ['PATH']}"}
    for _ in range(2):   # a second run (an upgrade) changes nothing more
        subprocess.run(["bash", "-c", script + "\npost_install"], cwd=root, env=env, check=True, capture_output=True)
    link = root / "usr/local/bin/spire"
    assert link.is_symlink() and os.readlink(link) == "/usr/bin/spire"
    assert (root / "usr/local/lib/spire-main/spire").read_text() == "old main-branch build\n"
    assert "/usr/bin/spire" in (root / "etc/shells").read_text().splitlines()
    assert "-s /usr/bin/spire me" in (tmp_path / "usermod.log").read_text()
