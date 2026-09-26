"""The desktop: deploying the dots with the distribution layer, and keeping
the layer's keybinds off chords upstream already uses."""

import re
from pathlib import Path

import pytest

from distrokit.branding import load as load_branding
from distrokit.desktop import deploy

REPO = Path(__file__).resolve().parents[2]
HYPR = REPO / "desktop/dots/dots/.config/hypr"

pytestmark = pytest.mark.skipif(not HYPR.is_dir(), reason="the dots submodule is not checked out")

BIND = re.compile(r'hl\.bind\(\s*"([^"]+)"\s*,')
LOOP = re.compile(r'hl\.bind\(\s*"([^"]+)"\s*\.\.\s*(\(i % 10\)|arrowkey\[i\]|keys\[i\]|keydirs\[i\])')
LOOP_VALUES = {
    "(i % 10)": [str(i) for i in range(10)],
    "arrowkey[i]": ["Left", "Right", "Up", "Down", "BracketLeft", "BracketRight"],
    "keys[i]": ["Left", "Right"],
    "keydirs[i]": ["Up", "Down"],
}
TABLE = re.compile(r"local (\w+) = \{([^}]*)\}")


def normalise(chord: str) -> str:
    parts = [p.strip() for p in chord.split("+") if p.strip()]
    *mods, key = parts
    return " + ".join(sorted(m.upper() for m in mods) + [key.lower()])


def lua_tables(block: str, env: dict[str, list[str]]) -> dict[str, list[str]]:
    """Evaluate `local x = { "a", y[1] .. "b" }` string tables in a loop body."""
    out = dict(env)
    for name, body in TABLE.findall(block):
        values = []
        for item in body.split(","):
            item = item.strip()
            if not item:
                continue
            text = ""
            for term in item.split(".."):
                term = term.strip()
                if term.startswith('"'):
                    text += term.strip('"')
                elif m := re.match(r"(\w+)\[(\d+)\]", term):
                    text += out.get(m.group(1), [""] * 9)[int(m.group(2)) - 1]
            values.append(text)
        out[name] = values
    return out


def chords(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"hl\.define_submap\(.*?\nend\)", "", text, flags=re.S)  # submap chords only apply there
    found = {normalise(c) for c in BIND.findall(text) if not c.endswith(" ")}
    for prefix, var in LOOP.findall(text):
        found |= {normalise(prefix + v) for v in LOOP_VALUES[var]}
    # for i = 1, n do ... local keycombos = {...} ... hl.bind(keycombos[i], ...) end
    for block in re.findall(r"\nfor i = .*?\nend", text, flags=re.S):
        if "hl.bind(keycombos[i]" in block:
            found |= {normalise(c) for c in lua_tables(block, {}).get("keycombos", [])}
    return found


def upstream_chords() -> set[str]:
    files = [HYPR / "hyprland/keybinds.lua", *sorted((HYPR / "hyprland/halcyon").glob("*.lua")),
             HYPR / "custom/keybinds.lua"]
    return set().union(*(chords(f) for f in files if f.is_file()))


def layer_chords(b) -> set[str]:
    text = b.render((REPO / "desktop/overlay/hypr/init.lua.in").read_text())
    return {normalise(c) for c in BIND.findall(text)}


def test_keybind_parser_sees_upstream_binds():
    up = upstream_chords()
    # Literal binds, digit loops and keycombos tables are all found.
    assert {"SUPER + a", "SUPER + 1", "SUPER + 0", "SUPER + tab"} <= up
    assert "CTRL + SUPER + mouse_up" in up
    assert len(up) > 100


def test_layer_binds_do_not_collide_with_upstream():
    b = load_branding()
    ours = layer_chords(b)
    assert ours == {"CTRL + SUPER + a", "SHIFT + SUPER + u", "SUPER + f1"}
    clashes = ours & upstream_chords()
    assert not clashes, f"already bound upstream: {sorted(clashes)} (Hyprland would run both actions)"


@pytest.fixture
def deployer(tmp_path):
    b = load_branding()
    walls = tmp_path / "walls"
    walls.mkdir()
    (walls / f"{b.id}-default.png").write_bytes(b"\x89PNG default")
    home = tmp_path / "home"
    home.mkdir()

    def make():
        return deploy.Deployer(home, b, dots=REPO / "desktop/dots", overlay=REPO / "desktop/overlay", wallpapers=walls)

    return b, home, make


def test_first_deploy(deployer):
    b, home, make = deployer
    settings = deploy.UserSettings(keyboard_layout="de", keyboard_variant="nodeadkeys",
                                   monitors=[{"connector": "eDP-1", "scale": 1.5}],
                                   apps=deploy.default_apps({"firefox", "kate"}, "code"))
    report = make().deploy(settings, first=True)
    assert len(report.written) > 300 and not report.backed_up
    entry = (home / ".config/hypr/hyprland.lua").read_text()
    assert f"{b.id}/init.lua" in entry or f'"{b.id}' in entry
    layer = (home / f".config/hypr/{b.id}/init.lua").read_text()
    assert "@DISTRO" not in layer and f"/usr/lib/{b.id}/bin/{b.id}-session-start" in layer
    general = (home / ".config/hypr/custom/general.lua").read_text()
    assert 'kb_layout = "de"' in general and 'kb_variant = "nodeadkeys"' in general
    assert 'hl.monitor({ output = "eDP-1", mode = "preferred", position = "auto", scale = 1.5 })' in general
    variables = (home / ".config/hypr/custom/variables.lua").read_text()
    assert 'terminal = "konsole"' in variables and 'browser = "firefox"' in variables
    assert 'codeEditor = "code"' in variables
    assert (home / ".config/quickshell/ii/shell.qml").is_file()
    assert (home / "Pictures/Wallpapers" / f"{b.id}-default.png").is_file()
    greeting = (home / ".config/quickshell/ii/services/FirstRunExperience.qml").read_text()
    assert f"Welcome to {b.pretty_name}" in greeting
    wants = home / ".config/systemd/user/default.target.wants/ydotool.service"
    assert wants.is_symlink()
    assert (home / f".local/state/{b.id}/desktop-manifest.json").is_file()


def test_redeploy_is_idempotent_and_keeps_user_changes(deployer):
    b, home, make = deployer
    make().deploy(deploy.UserSettings(), first=True)
    report = make().deploy()
    assert report.written == [] and report.backed_up == []

    # The user edits a deployed file and their own custom/ file.
    kitty = home / ".config/kitty/kitty.conf"
    kitty.write_text(kitty.read_text() + "\nfont_size 14\n")
    mine = home / ".config/hypr/custom/keybinds.lua"
    mine.write_text('hl.bind("SUPER + F12", hl.dsp.exec_cmd("true"))\n')
    report = make().deploy()
    # An update restores the managed file but keeps a copy; custom/ is never touched.
    assert ".config/kitty/kitty.conf" in report.backed_up
    backup = Path(report.backup_dir.replace(str(home), str(home), 1))
    assert (backup / ".config/kitty/kitty.conf").read_text().endswith("font_size 14\n")
    assert mine.read_text().startswith('hl.bind("SUPER + F12"')


def test_reset_backs_up_custom_and_restores_defaults(deployer):
    b, home, make = deployer
    make().deploy(deploy.UserSettings(keyboard_layout="fr"), first=True)
    custom = home / ".config/hypr/custom/general.lua"
    custom.write_text(custom.read_text() + "\n-- mine\n")
    report = make().reset(deploy.UserSettings(keyboard_layout="us"))
    assert ".config/hypr/custom/general.lua" in report.backed_up
    assert 'kb_layout = "us"' in custom.read_text() and "-- mine" not in custom.read_text()
    assert (Path(report.backup_dir) / ".config/hypr/custom/general.lua").read_text().endswith("-- mine\n")


def test_default_apps_only_lists_installed_software():
    apps = deploy.default_apps({"kate"})
    assert apps == {"terminal": "konsole", "fileManager": "dolphin", "textEditor": "kate"}
