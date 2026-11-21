"""The rename from Nexora (DISTRO_LEGACY_IDS): packages replace the old ones, and a system installed under the old
name is moved over (system/legacy.py) without losing anything."""

import os
import re

from distrokit.branding import load as load_branding
from distrokit.build import branding as build_branding
from distrokit.build import packages, stage
from distrokit.system import legacy
from distrokit import util

B = load_branding()


def test_the_new_name_and_its_former_one():
    assert (B.name, B.pretty_name, B.id, B.cli) == ("Frontline", "Frontline Linux", "frontline", "frontline")
    assert legacy.legacy_ids(B) == ["nexora"]


def test_renamed_packages_replace_the_old_ones():
    single = packages.legacy_replaces("pkgname=frontline-msg\nconflicts=(other)\npackage() {\n}\n", B)
    assert single.rstrip().endswith("replaces+=(nexora-msg)\nconflicts+=(nexora-msg)")
    split = packages.legacy_replaces(
        "pkgname=(frontline-core halcyon-desktop)\npackage_frontline-core() {\n  conflicts=(nano)\n}\n"
        "package_halcyon-desktop() { :; }\n", B)
    body = split.split("package_frontline-core() {")[1].split("}")[0]
    # After the function's own conflicts=, so they are added to, not overwritten.
    assert body.index("conflicts=(nano)") < body.index("conflicts+=(nexora-core)")
    assert "replaces+=(nexora-core)" in body
    assert "nexora-desktop" not in split  # halcyon-desktop never had the old name


def test_the_old_command_still_works(tmp_path):
    st = stage.Stage(tmp_path, B)
    st.core()
    assert os.readlink(tmp_path / "usr/bin/nexora") == "frontline"
    hook = (tmp_path / "usr/share/libalpm/hooks/80-frontline-migrate-legacy.hook").read_text()
    assert "When = PostTransaction" in hook and "frontline-migrate-legacy" in hook


def fake_nexora_system(root):
    (root / "etc").mkdir(parents=True)
    (root / "etc/pacman.conf").write_text(
        "[options]\nHoldPkg = pacman\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n\n"
        "[nexora]\nSigLevel = Optional TrustAll\nServer = https://github.com/trail-b1az3r/distro/releases/download/repo\n\n"
        "[nexora-surface]\nSigLevel = Optional TrustAll\n"
        "Server = https://github.com/trail-b1az3r/distro/releases/download/nexora-surface\n\n"
        "[nexora-experiments]\nServer = https://github.com/trail-b1az3r/distro/releases/download/nexora-experiments\n")
    (root / "etc/nexora").mkdir()
    (root / "etc/nexora/desktop.conf").write_text("x\n")
    (root / "var/lib/nexora/session-previews").mkdir(parents=True)
    (root / "etc/sddm.conf.d").mkdir()
    (root / "etc/sddm.conf.d/10-nexora.conf").write_text("[Theme]\nCurrent=nexora\n")
    wants = root / "etc/systemd/system/timers.target.wants"
    wants.mkdir(parents=True)
    os.symlink("/usr/lib/systemd/system/nexora-auto-update.timer", wants / "nexora-auto-update.timer")
    (root / "usr/lib/systemd/system").mkdir(parents=True)
    (root / "usr/lib/systemd/system/frontline-auto-update.timer").write_text("[Timer]\n")
    home = root / "home/alex"
    (home / ".config/nexora-write").mkdir(parents=True)
    (home / ".config/nexora-write/write.conf").write_text("spelling=true\n")
    (home / ".local/share/nexora-msg").mkdir(parents=True)
    (home / "nexora").mkdir()       # a folder of the user's own: not touched
    (home / ".config/nexoraish").mkdir()  # not the old name
    return home


def test_a_nexora_system_is_moved_over(tmp_path):
    root = tmp_path / "root"
    home = fake_nexora_system(root)
    log = legacy.migrate(root, B, util.Runner(dry_run=True))
    conf = (root / "etc/pacman.conf").read_text()
    assert "[frontline]\n" in conf and "[frontline-surface]\n" in conf and "[frontline-experiments]\n" in conf
    assert "[nexora" not in conf
    assert "releases/download/frontline-surface" in conf and "releases/download/frontline-experiments" in conf
    assert conf.count("releases/download/repo") == 1   # the main repository's release keeps its address
    assert (root / "etc/pacman.conf.nexora").read_text().count("[nexora") == 3  # the old file is kept
    assert (root / "etc/frontline/desktop.conf").read_text() == "x\n"
    assert (root / "etc/nexora").is_symlink() and (root / "etc/nexora/desktop.conf").exists()
    assert (root / "var/lib/frontline/session-previews").is_dir()
    assert not (root / "etc/sddm.conf.d/10-nexora.conf").exists()
    assert "Current=frontline" in (root / "etc/sddm.conf.d/10-frontline.conf").read_text()
    wants = root / "etc/systemd/system/timers.target.wants"
    assert os.readlink(wants / "frontline-auto-update.timer") == "/usr/lib/systemd/system/frontline-auto-update.timer"
    assert not (wants / "nexora-auto-update.timer").is_symlink()
    assert (home / ".config/frontline-write/write.conf").read_text() == "spelling=true\n"
    assert os.readlink(home / ".config/nexora-write") == "frontline-write"
    assert (home / ".local/share/frontline-msg").is_dir()
    assert (home / "nexora").is_dir() and not (home / "frontline").exists()
    assert (home / ".config/nexoraish").is_dir() and not (home / ".config/frontlineish").exists()
    assert log
    # A second run changes nothing.
    before = (root / "etc/pacman.conf").read_text()
    assert legacy.migrate(root, B, util.Runner(dry_run=True)) == []
    assert (root / "etc/pacman.conf").read_text() == before


def test_both_names_existing_keeps_the_new_and_leaves_the_old(tmp_path):
    root = tmp_path / "root"
    (root / "etc/nexora").mkdir(parents=True)
    (root / "etc/frontline").mkdir()
    (root / "etc/nexora/old.conf").write_text("old\n")
    legacy.migrate(root, B, util.Runner(dry_run=True))
    assert (root / "etc/nexora/old.conf").read_text() == "old\n" and not (root / "etc/nexora").is_symlink()


def test_fastfetch_logo_is_braille_line_art(tmp_path):
    from PIL import Image, ImageDraw

    png = tmp_path / "mark.png"
    img = Image.new("RGBA", (576, 576), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(288, 60), (540, 288), (288, 516), (36, 288)], fill=(143, 143, 143, 255))
    d.line([(100, 400), (288, 120), (470, 400)], fill=(20, 20, 20, 255), width=6)
    d.polygon([(288, 120), (320, 170), (256, 170)], fill=(250, 250, 250, 255))
    img.save(png)
    art = build_branding.braille_logo(png, cols=36)
    lines = art.splitlines()
    assert len(lines) == 18 and max(len(re.sub(r"\x1b\[[0-9;]*m", "", ln)) for ln in lines) <= 36
    colours = set(re.findall(r"38;2;(\d+;\d+;\d+)", art))
    assert 1 <= len(colours) <= 3 and "48;2;" not in art   # light on the terminal's own background
    assert any(0x2800 < ord(ch) <= 0x28FF for ch in art)
    assert '"width": 36' in (build_branding.paths.data("branding", "fastfetch", "config.jsonc.in")).read_text()
