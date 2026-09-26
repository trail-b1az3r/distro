import pytest

from distrokit import branding, profiles, surface, util


def test_surface_detected_and_recommended(machine):
    _, r = machine("surface_pro7")
    info = surface.detect(r)
    assert info.detected and info.recommended and not info.needs_marvell_firmware
    sp = surface.plan(info, enabled=True)
    assert {"linux-surface", "linux-surface-headers", "iptsd"} <= set(sp.packages)
    assert sp.default_kernel == "linux-surface"
    assert "[linux-surface]" in sp.repo_block


def test_surface_not_forced_but_manual_choice_respected(machine):
    _, r = machine("rtx4080_desktop")
    info = surface.detect(r)
    assert not info.detected and not info.recommended
    assert surface.plan(info, enabled=False).packages == []
    manual = surface.plan(info, enabled=True)
    assert "linux-surface" in manual.packages
    assert any("manually" in n for n in manual.notes)


def test_surface_key_fingerprint():
    if not util.which("gpg"):
        pytest.skip("gpg not available")
    assert surface.verify_key() == "87DEFA4AB94A99A4C8C3112556C464BAAC421453"


def test_surface_repo_added_once(tmp_path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/pacman.conf").write_text("[options]\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n")
    runner = util.Runner(dry_run=False)
    # pacman-key calls go through arch-chroot; record them instead of running.
    runner.dry_run = True
    surface.ensure_repo(tmp_path, runner)
    runner.dry_run = False
    text = (tmp_path / "etc/pacman.conf").read_text()
    assert text.count("[linux-surface]") == 0  # dry run leaves the file alone
    runner2 = util.Runner(dry_run=False)
    runner2.run = lambda cmd, **kw: util.Result(list(cmd), 0)  # type: ignore[method-assign]
    if util.which("gpg"):
        surface.ensure_repo(tmp_path, runner2)
        surface.ensure_repo(tmp_path, runner2)
        assert (tmp_path / "etc/pacman.conf").read_text().count("[linux-surface]") == 1


def test_profiles_inherit():
    ps = profiles.load_profiles()
    assert list(ps) == ["minimal", "standard", "developer", "ai"]
    assert profiles.default_profile(ps).id == "standard"
    assert ps["developer"].features["office"] is True  # inherited from standard
    assert ps["developer"].features["claude_code"] is True
    assert ps["ai"].features["hypernix"] is True and ps["ai"].features["assistant"] == "hermis"
    assert ps["minimal"].features["browser"] is False


def test_select_packages_contents():
    ps = profiles.load_profiles()
    minimal = profiles.select_packages(ps["minimal"])
    assert {"git", "fish", "yay", "konsole", "dolphin", "networkmanager", "pipewire"} <= set(minimal.packages)
    assert "firefox" not in minimal.packages and "onlyoffice-bin" not in minimal.packages
    standard = profiles.select_packages(ps["standard"])
    assert {"firefox", "onlyoffice-bin", "ark", "okular"} <= set(standard.packages)
    dev = profiles.select_packages(ps["developer"])
    assert {"gcc", "clang", "rust", "cmake", "podman", "code"} <= set(dev.packages)
    ai = profiles.select_packages(ps["ai"])
    assert "nexora-ai" in ai.packages
    # Feature overrides customise a profile.
    custom = profiles.select_packages(ps["developer"], {"containers": "docker", "office": False})
    assert "docker" in custom.packages and "podman" not in custom.packages
    assert "onlyoffice-bin" not in custom.packages
    # Snapshots only make sense on Btrfs.
    assert "snapper" in profiles.select_packages(ps["standard"], filesystem="btrfs").packages
    assert "snapper" not in profiles.select_packages(ps["standard"], filesystem="ext4").packages


def test_select_packages_rejects_bad_feature():
    ps = profiles.load_profiles()
    with pytest.raises(profiles.ProfileError):
        profiles.select_packages(ps["standard"], {"nope": True})
    with pytest.raises(profiles.ProfileError):
        profiles.select_packages(ps["standard"], {"containers": "lxc"})


def test_every_list_parses_and_has_no_duplicates():
    b = branding.load()
    for name in profiles.available_lists():
        pkgs = profiles.read_list(name, b)
        assert pkgs, name
        assert len(pkgs) == len(set(pkgs)), f"duplicate package in {name}.list"


def test_branding_values_and_render():
    b = branding.load()
    assert b.name == "Nexora" and b.id == "nexora" and b.cli == "nexora"
    assert b.render("@DISTRO_NAME@ @DISTRO_ID@") == "Nexora nexora"
    with pytest.raises(branding.BrandingError):
        b.render("@NOT_A_KEY@")
    assert 'ID="nexora"' in b.os_release("2026.09")
    assert 'ID_LIKE="endeavouros arch"' in b.os_release("2026.09")


def test_branding_rename(tmp_path):
    conf = (branding.paths.data("distro.conf")).read_text()
    renamed = conf.replace('DISTRO_NAME="Nexora"', 'DISTRO_NAME="Aurora"').replace('DISTRO_ID="nexora"', 'DISTRO_ID="aurora"')
    p = tmp_path / "distro.conf"
    p.write_text(renamed)
    b = branding.load_file(p)
    assert b.package("core") == "aurora-core"
    assert str(b.system_paths("/mnt").sysconf) == "/mnt/etc/aurora"


@pytest.mark.parametrize("bad", ['DISTRO_ID="Bad ID"', 'DISTRO_NAME="$(rm -rf /)"', "BRAND_BG=\"red\""])
def test_branding_rejects_bad_values(tmp_path, bad):
    conf = branding.paths.data("distro.conf").read_text()
    key = bad.split("=")[0]
    lines = [bad if line.startswith(key + "=") else line for line in conf.splitlines()]
    p = tmp_path / "distro.conf"
    p.write_text("\n".join(lines))
    with pytest.raises(branding.BrandingError):
        branding.load_file(p)
