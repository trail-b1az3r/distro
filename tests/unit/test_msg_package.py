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
    assert "AUR_SSH_PRIVATE_KEY" in (ROOT / ".github/workflows/aur.yml").read_text()
