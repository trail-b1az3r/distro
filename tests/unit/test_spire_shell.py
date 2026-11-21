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
