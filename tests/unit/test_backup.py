import json
import subprocess

from distrokit.installer import backup
from distrokit.installer.disks import DiskPlan, Volume


def test_copy_image_returns_sha256_and_rejects_short_reads(tmp_path):
    source = tmp_path / "source.img"
    source.write_bytes(b"nexora rollback image")
    destination = tmp_path / "snapshot.img"

    digest = backup._copy_image(str(source), destination, source.stat().st_size, lambda _line: None)

    import hashlib
    assert digest == hashlib.sha256(source.read_bytes()).hexdigest()
    assert destination.read_bytes() == source.read_bytes()


def test_inventory_reads_previous_pacman_local_database(tmp_path, monkeypatch):
    root = tmp_path / "old-root"
    db = root / "var/lib/pacman/local/hello-1.2-1"
    db.mkdir(parents=True)
    (root / "etc").mkdir()
    (root / "etc/os-release").write_text("ID=oldlinux\n")
    (db / "desc").write_text("%NAME%\nhello\n\n%VERSION%\n1.2-1\n\n")
    (db / "files").write_text("%FILES%\nusr/bin/hello\nusr/share/hello/data\n\n")

    def fake_run(args, **kwargs):
        assert "pacman" in args[0]
        return subprocess.CompletedProcess(args, 0, stdout="hello\n", stderr="")

    monkeypatch.setattr(backup.subprocess, "run", fake_run)
    manifest = tmp_path / "packages.jsonl"
    messages = []

    assert backup._inventory_from_root(root, manifest, messages.append)
    records = [json.loads(line) for line in manifest.read_text().splitlines()]
    assert records[0]["scope"] == "previous_installed_system"
    assert records[1] == {"type": "package", "name": "hello", "version": "1.2-1", "source": "aur_or_local"}
    assert records[2]["path"] == "usr/bin/hello"
    assert records[3]["path"] == "usr/share/hello/data"


def test_home_copy_excludes_hidden_files_and_directories(tmp_path):
    root = tmp_path / "old-root"
    (root / "etc").mkdir(parents=True)
    (root / "etc/passwd").write_text("rayla:x:1000:1000:Rayla:/home/rayla:/bin/bash\n")
    home = root / "home/rayla"
    (home / "Downloads").mkdir(parents=True)
    (home / ".config").mkdir()
    (home / "Documents").mkdir()
    (home / "Downloads/file.zip").write_bytes(b"archive")
    (home / "Documents/notes.txt").write_text("notes")
    (home / ".hidden").write_text("private")
    (home / ".config/settings").write_text("private")

    destination = tmp_path / "backup"
    destination.mkdir()
    backup._copy_visible_home(root, destination, lambda _line: None)

    copied = destination / "home-data/rayla"
    assert (copied / "Downloads/file.zip").read_bytes() == b"archive"
    assert (copied / "Documents/notes.txt").read_text() == "notes"
    assert not (copied / ".hidden").exists()
    assert not (copied / ".config").exists()


def test_manual_plan_is_destructive_even_when_root_is_not_formatted():
    plan = DiskPlan(
        mode="manual", disk="", firmware="uefi", bootloader="systemd-boot", new_table=False,
        volumes=[Volume("root", "/", "ext4", device="/dev/sda2", format=False, existing=True)],
    )
    assert plan.destructive
