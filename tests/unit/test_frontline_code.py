"""Frontline Code: the built-in editor (VSCodium, rebranded, themed, following Halcyon's colours)."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "packages/pkgbuild/frontline-code"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, PKG / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_it_is_the_default_editor():
    from distrokit.branding import load
    from distrokit.profiles import load_editors
    b = load()
    editor = load_editors()[b.get("CODE_EDITOR")]
    assert editor.package == f"{b.id}-code" and editor.redistributable and editor.command == f"{b.id}-code"
    assert '"frontline-code"' in (ROOT / "packages/repo.toml").read_text()


def test_rebrand(tmp_path):
    product = tmp_path / "product.json"
    product.write_text(json.dumps({"nameShort": "VSCodium", "nameLong": "VSCodium", "applicationName": "codium",
                                   "dataFolderName": ".vscode-oss", "updateUrl": "x", "extensionsGallery": {"a": 1}}))
    subprocess.run([sys.executable, str(PKG / "rebrand.py"), str(product), "Frontline Code", "frontline-code"], check=True)
    p = json.loads(product.read_text())
    assert p["nameShort"] == p["nameLong"] == "Frontline Code" and p["dataFolderName"] == ".frontline-code"
    assert p["applicationName"] == "codium" and "updateUrl" not in p and p["extensionsGallery"] == {"a": 1}


def test_themes_and_the_halcyon_map(tmp_path):
    subprocess.run([sys.executable, str(PKG / "make-themes.py"), str(tmp_path), "#0B0E1A", "#151A2C", "#E8ECF8",
                    "#8A93B2", "#7C6CFF", "#23D5C4", "#FFB547", "#FF5C7A"], check=True)
    dark = json.loads((tmp_path / "dark.json").read_text())
    light = json.loads((tmp_path / "light.json").read_text())
    assert dark["type"] == "dark" and light["type"] == "light"
    assert dark["colors"]["editor.background"] == "#0B0E1A" and dark["colors"]["activityBar.foreground"] == "#7C6CFF"
    assert light["colors"]["editor.background"].upper() == "#FBFAFF"
    for theme in (dark, light):
        assert all(len(v) in (7, 9) and v.startswith("#") for v in theme["colors"].values())
    # The extension maps Halcyon's Material roles with the same table; every role it uses is one Halcyon writes.
    m = json.loads((tmp_path / "map.json").read_text())
    halcyon = {"background", "surface", "surface_container_lowest", "surface_container_low", "surface_container",
               "surface_container_high", "surface_container_highest", "on_surface", "on_surface_variant", "outline",
               "outline_variant", "primary", "on_primary", "primary_container", "on_primary_container",
               "secondary_container", "on_secondary_container", "tertiary", "on_tertiary", "on_tertiary_container",
               "error", "shadow"}
    used = {e[0] for e in m["colors"].values()} | {t[1] for t in m["tokens"]}
    assert used - halcyon <= {"warning"} and "warning" in m["fallback"]


def test_extension_manifest():
    manifest = (PKG / "extension-package.json.in").read_text()
    assert '"workbench.colorTheme": "@DISTRO_NAME@ Material"' in manifest
    assert '"telemetry.telemetryLevel": "off"' in manifest and '"main": "./extension.js"' in manifest
    ext = (PKG / "extension.js").read_text()
    assert "generated" in ext and "colors.json" in ext and "workbench.colorCustomizations" in ext
    build = (PKG / "PKGBUILD.in").read_text()
    assert "sha256sums=('ca1895aa040bd91a09c709d79eac7862d8c1aa0237fdc25b503deeb8bcd87efd'" in build


def _launch(tmp_path, *, signed_in=True, gitconfig=""):
    """Runs the launcher with a fake gh and a fake editor that prints the git environment it was given."""
    launcher = (PKG / "@DISTRO_ID@-code.in").read_text().replace("@DISTRO_ID@", "frontline").replace("@DISTRO_NAME@", "Frontline")
    editor = tmp_path / "codium"
    editor.write_text("#!/bin/sh\ngit config --get user.name\ngit config --get user.email\n"
                      "git config --get-urlmatch credential.helper https://github.com\n")
    editor.chmod(0o755)
    script = tmp_path / "frontline-code"
    script.write_text(launcher.replace("/usr/lib/frontline-code/bin/codium", str(editor)))
    script.chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text("#!/bin/sh\n"
                  f'if [ "$1 $2" = "auth status" ]; then exit {0 if signed_in else 1}; fi\n'
                  'if [ "$1" = api ]; then printf "Mason Example\\t42+mason@users.noreply.github.com\\n"; fi\n')
    gh.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / ".gitconfig").write_text(gitconfig)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(home)}
    return subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=30).stdout.splitlines()


def test_git_in_the_editor_uses_the_gh_login_and_github_identity(tmp_path):
    name, email, helper = _launch(tmp_path)
    assert (name, email, helper) == ("Mason Example", "42+mason@users.noreply.github.com", "!gh auth git-credential")
    assert not (tmp_path / "home/.gitconfig").read_text(), "the user's git config is not changed"


def test_your_own_git_config_wins(tmp_path):
    out = _launch(tmp_path, gitconfig="[user]\n\tname = Me\n\temail = me@example.org\n[credential]\n\thelper = store\n")
    assert out == ["Me", "me@example.org", "store"]


def test_nothing_without_a_gh_login(tmp_path):
    assert _launch(tmp_path, signed_in=False) == []
