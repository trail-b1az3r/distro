"""nexora-msg is packaged, installed with the desktop, and its iPhone app is built by CI."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/msg"


def test_package_is_built_and_installed_with_the_desktop():
    assert '"msg"' in (ROOT / "packages/repo.toml").read_text()
    assert "@DISTRO_ID@-msg" in (ROOT / "packages/lists/desktop.list").read_text().splitlines()
    pkgbuild = (ROOT / "packages/pkgbuild/msg/PKGBUILD.in").read_text()
    for need in ("pyside6", "python-cryptography", "python-dbus-next", "cargo"):
        assert need in pkgbuild
    for file in ("nexora_msg/qml/*.qml", "nexora_msg/qml/icons/*.svg", "core/target/release/nexora-msg-core"):
        assert file in pkgbuild


def test_every_qml_file_and_icon_ships():
    qml = {p.name for p in (APP / "nexora_msg/qml").glob("*.qml")}
    assert {"Main.qml", "Conversation.qml", "Bubble.qml", "DevicesDialog.qml"} <= qml
    for p in (APP / "nexora_msg/qml").glob("*.qml"):
        for icon in __import__("re").findall(r'"icons/([\w-]+\.svg)"', p.read_text()):
            assert (APP / "nexora_msg/qml/icons" / icon).is_file(), icon


def test_ios_app_and_ci():
    project = (APP / "ios/project.yml").read_text()
    assert "UIBackgroundModes: [audio]" in project and "_nexoramsg._tcp" in project
    sources = {p.name for p in (APP / "ios/NexoraMessages").glob("*.swift")}
    assert {"KeepAlive.swift", "Server.swift", "Crypto.swift", "Composer.swift", "ContactsExport.swift"} <= sources
    workflow = (ROOT / ".github/workflows/msg.yml").read_text()
    assert '"3.14", "3.15"' in workflow and "macos-" in workflow and "build-ipa.sh" in workflow
    # The two sides speak the same protocol.
    swift = (APP / "ios/NexoraMessages/Crypto.swift").read_text()
    py = (APP / "nexora_msg/companion.py").read_text()
    for token in ("nexora-msg v1 code", "nexora-msg v1 key"):
        assert token in swift and token in py
    assert "47800" in py and "47800" in (APP / "ios/NexoraMessages/Server.swift").read_text()


def test_aur_package():
    aur = (ROOT / "aur/nexora-msg/PKGBUILD").read_text()
    srcinfo = (ROOT / "aur/nexora-msg/.SRCINFO").read_text()
    assert "options=(!lto)" in aur and "options=(!lto)" in (ROOT / "packages/pkgbuild/msg/PKGBUILD.in").read_text()
    commit = aur.split("_commit=")[1].split("\n")[0]
    assert len(commit) == 40 and commit in srcinfo, "the .SRCINFO matches the PKGBUILD"
    workflow = (ROOT / ".github/workflows/aur.yml").read_text()
    assert "AUR_SSH_PRIVATE_KEY" in workflow and "nexora-rdp-express" in workflow
    rdp = (ROOT / "aur/nexora-rdp-express/PKGBUILD").read_text()
    assert rdp.split("_commit=")[1].split("\n")[0] in (ROOT / "aur/nexora-rdp-express/.SRCINFO").read_text()


def test_remote_desktop_server_is_its_own_package():
    assert '"rdp-express"' in (ROOT / "packages/repo.toml").read_text()
    pkg = (ROOT / "packages/pkgbuild/rdp-express/PKGBUILD.in").read_text()
    assert "pkgname=@DISTRO_ID@-rdp-express" in pkg and "rdp-express.service" in pkg
    # Installed where a desktop should be shared, not with every desktop.
    assert "rdp-express" not in (ROOT / "packages/lists/desktop.list").read_text()
    assert "@DISTRO_ID@-rdp-express" in (ROOT / "packages/pkgbuild/msg/PKGBUILD.in").read_text()
    # The viewer and the server agree on the port and the key derivation.
    rust = (ROOT / "apps/rdp-express/src/link.rs").read_text()
    py = (APP / "nexora_msg/rdp.py").read_text()
    for token in ("rdp-express v1 key", "rdp-express v1 pair", "C2S", "S2C"):
        assert token in rust and token in py
    assert "47801" in (ROOT / "apps/rdp-express/src/main.rs").read_text() and "PORT = 47801" in py
