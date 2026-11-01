"""Verified pre-install rollback snapshots and legacy-system inventory."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

MIN_BACKUP_DISK = 256 * 2**30
CHUNK = 16 * 2**20


class SnapshotError(RuntimeError):
    pass


def _run(args: list[str], *, check: bool = True) -> str:
    proc = subprocess.run(args, text=True, capture_output=True, check=False)
    if check and proc.returncode:
        raise SnapshotError(proc.stderr.strip() or f"{args[0]} failed")
    return proc.stdout


def _tree() -> list[dict[str, Any]]:
    try:
        data = json.loads(_run(["lsblk", "-J", "-p", "-b", "-o", "NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS,PKNAME"]))
    except (ValueError, OSError) as exc:
        raise SnapshotError(f"cannot inspect storage devices: {exc}") from exc
    out: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], parent: str = "") -> None:
        if node.get("type") == "disk":
            parent = node.get("name", "")
        out.append({**node, "_parent_disk": parent})
        for child in node.get("children") or []:
            walk(child, parent)

    for node in data.get("blockdevices", []):
        walk(node)
    return out


def _available_ram() -> int:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _copy_image(source: str, destination: Path, expected: int, log) -> str:
    copied = 0
    digest = hashlib.sha256()
    with open(source, "rb", buffering=0) as src, destination.open("wb", buffering=0) as dst:
        while True:
            block = src.read(CHUNK)
            if not block:
                break
            dst.write(block)
            digest.update(block)
            copied += len(block)
            if copied and copied % (1024**3) < CHUNK:
                log(f"Snapshot copied {copied // (1024**3)} GiB of {expected // (1024**3)} GiB")
        dst.flush()
        os.fsync(dst.fileno())
    if copied != expected:
        destination.unlink(missing_ok=True)
        raise SnapshotError(f"snapshot size mismatch: copied {copied} bytes, expected {expected}")
    return digest.hexdigest()


def _section(path: Path, section: str) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    marker = f"%{section}%"
    try:
        start = lines.index(marker) + 1
    except ValueError:
        return []
    values: list[str] = []
    for line in lines[start:]:
        if line.startswith("%"):
            break
        if line:
            values.append(line)
    return values


def _inventory_from_root(root: Path, destination: Path, log) -> bool:
    db = root / "var/lib/pacman/local"
    if not db.is_dir() or not (root / "etc/os-release").is_file():
        return False

    foreign: set[str] = set()
    pacman_config = Path("/etc/pacman.conf")
    proc = subprocess.run(
        ["pacman", "--config", str(pacman_config), "--dbpath", str(root / "var/lib/pacman"), "-Qm"],
        text=True, capture_output=True, check=False,
    )
    if proc.returncode == 0:
        foreign = {line.split()[0] for line in proc.stdout.splitlines() if line.split()}

    packages = 0
    with destination.open("w", encoding="utf-8") as out:
        out.write(json.dumps({
            "type": "inventory", "scope": "previous_installed_system",
            "root": str(root), "foreign_classification": "pacman sync database; foreign packages may include AUR and locally built packages",
        }) + "\n")
        for entry in sorted(db.iterdir()):
            if not entry.is_dir():
                continue
            names = _section(entry / "desc", "NAME")
            versions = _section(entry / "desc", "VERSION")
            if not names or not versions:
                continue
            name, version = names[0], versions[0]
            source = "aur_or_local" if name in foreign else "repository_or_unknown"
            out.write(json.dumps({"type": "package", "name": name, "version": version, "source": source},
                                 ensure_ascii=False) + "\n")
            for path in _section(entry / "files", "FILES"):
                out.write(json.dumps({"type": "file", "package": name, "path": path},
                                     ensure_ascii=False) + "\n")
            packages += 1
        out.flush()
        os.fsync(out.fileno())
    log(f"Saved previous-system Pacman inventory ({packages} packages)")
    return True


def _copy_visible_home(root: Path, destination: Path, log) -> None:
    """Copy visible files from each regular user's home when backup space permits."""
    passwd = root / "etc/passwd"
    if not passwd.is_file():
        return
    users: list[tuple[str, str]] = []
    for line in passwd.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split(":")
        if len(fields) < 7:
            continue
        username, uid, home = fields[0], fields[2], fields[5]
        try:
            numeric_uid = int(uid)
        except ValueError:
            continue
        if 1000 <= numeric_uid < 65534 and home.startswith("/home/"):
            source = root / home.lstrip("/")
            if source.is_dir():
                users.append((username, str(source)))

    for username, source_text in users:
        source = Path(source_text)
        visible = [item for item in source.iterdir() if not item.name.startswith(".")]
        if not visible:
            continue
        target = destination / "home-data" / username
        estimate = 0
        for item in visible:
            if item.is_symlink():
                continue
            if item.is_file():
                estimate += item.stat().st_size
            elif item.is_dir():
                for base, dirs, files in os.walk(item, followlinks=False):
                    dirs[:] = [name for name in dirs if not name.startswith(".")]
                    for name in files:
                        if not name.startswith("."):
                            try:
                                estimate += (Path(base) / name).stat().st_size
                            except OSError:
                                pass
        if shutil.disk_usage(destination).free < estimate + 128 * 2**20:
            log(f"Skipped optional home-data copy for {username}: not enough free space; full-disk snapshot is retained")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir(parents=True, exist_ok=False)
        for item in visible:
            out = target / item.name
            try:
                if item.is_dir() and not item.is_symlink():
                    shutil.copytree(item, out, symlinks=True, ignore=shutil.ignore_patterns(".*"))
                elif item.is_symlink():
                    out.symlink_to(os.readlink(item))
                elif item.is_file():
                    shutil.copy2(item, out)
            except OSError as exc:
                shutil.rmtree(target, ignore_errors=True)
                log(f"Optional home-data copy for {username} was skipped after an I/O error: {exc}")
                break
        else:
            log(f"Copied visible home files for {username} to {target}")


def _mount_separate_home(root: Path, mounted: list[Path], log) -> None:
    """Mount a separate /home filesystem from the old installation's fstab."""
    fstab = root / "etc/fstab"
    if not fstab.is_file():
        return
    for line in fstab.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) < 3 or fields[1] != "/home" or fields[0].startswith("#"):
            continue
        source = fields[0]
        if source.startswith("UUID="):
            proc = subprocess.run(["blkid", "-U", source[5:]], text=True, capture_output=True, check=False)
            source = proc.stdout.strip()
        elif source.startswith("PARTUUID="):
            proc = subprocess.run(["blkid", "-t", source, "-o", "device"], text=True, capture_output=True, check=False)
            source = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
        if not source or not Path(source).exists():
            log("Separate /home partition from the old fstab could not be resolved; the raw snapshot remains available")
            return
        target = root / "home"
        target.mkdir(exist_ok=True)
        fs = fields[2]
        options = {"ext4": "ro,noload", "btrfs": "ro,nologreplay", "xfs": "ro,norecovery"}.get(fs, "ro")
        proc = subprocess.run(["mount", "-o", options, source, str(target)],
                              text=True, capture_output=True, check=False)
        if proc.returncode == 0:
            mounted.append(target)
        else:
            log(f"Could not mount separate /home read-only: {proc.stderr.strip()}")
        return


def _export_previous_system(target_disk: str, base: Path, manifest: Path, log, *, copy_home: bool) -> None:
    """Mount candidate target partitions read-only to inventory the old OS."""
    nodes = _tree()
    disk_real = os.path.realpath(target_disk)
    partitions = [
        node for node in nodes
        if node.get("_parent_disk") and os.path.realpath(node["_parent_disk"]) == disk_real
        and node.get("type") in ("part", "crypt")
        and node.get("fstype") in ("ext4", "btrfs", "xfs")
    ]
    temp_root = Path(tempfile.mkdtemp(prefix="nexora-inspect-", dir="/run"))
    mounted: list[Path] = []
    found = False
    try:
        for index, node in enumerate(partitions):
            mountpoint = temp_root / str(index)
            mountpoint.mkdir()
            fs = node["fstype"]
            options = {"ext4": "ro,noload", "btrfs": "ro,nologreplay", "xfs": "ro,norecovery"}[fs]
            proc = subprocess.run(["mount", "-o", options, node["name"], str(mountpoint)],
                                  text=True, capture_output=True, check=False)
            if proc.returncode:
                continue
            mounted.append(mountpoint)
            if _inventory_from_root(mountpoint, manifest, log):
                found = True
                _mount_separate_home(mountpoint, mounted, log)
                if copy_home:
                    _copy_visible_home(mountpoint, base, log)
                break
        if not found:
            with manifest.open("w", encoding="utf-8") as out:
                out.write(json.dumps({"type": "inventory", "scope": "no_unencrypted_previous_system_found",
                                      "note": "The full raw-disk snapshot is the authoritative rollback copy. "
                                              "Encrypted or nonstandard installations may need manual inspection."}) + "\n")
                out.flush()
                os.fsync(out.fileno())
            log("No readable existing Pacman installation was found for a separate inventory")
    finally:
        for mountpoint in reversed(mounted):
            subprocess.run(["umount", str(mountpoint)], text=True, capture_output=True, check=False)
        shutil.rmtree(temp_root, ignore_errors=True)


def create(target_disk: str, branding_id: str, log, *, exclude_disks: list[str] | None = None,
           copy_home: bool = True) -> dict[str, Any]:
    """Create and verify a raw-disk rollback image before partitioning."""
    target = Path(target_disk)
    if not target.exists():
        raise SnapshotError(f"target disk disappeared: {target_disk}")
    try:
        size = int(_run(["blockdev", "--getsize64", target_disk]).strip())
    except ValueError as exc:
        raise SnapshotError("could not determine the target disk size") from exc
    if size <= 0:
        raise SnapshotError("could not determine the target disk size")

    nodes = _tree()
    excluded = {os.path.realpath(path) for path in (exclude_disks or [])}
    excluded.add(os.path.realpath(target_disk))
    candidates: list[tuple[int, str]] = []
    for node in nodes:
        if node.get("type") != "disk" or int(node.get("size") or 0) < MIN_BACKUP_DISK:
            continue
        if os.path.realpath(node.get("name", "")) in excluded:
            continue
        parent = node.get("name", "")
        for part in nodes:
            if part.get("_parent_disk") != parent:
                continue
            for mount in part.get("mountpoints") or []:
                if not mount or mount in ("/", "/run", "/tmp"):
                    continue
                try:
                    free = shutil.disk_usage(mount).free
                except OSError:
                    continue
                if free >= size + 128 * 2**20:
                    candidates.append((free, mount))

    stamp = time.time_ns()
    disk_label = target.name.replace("/", "_")
    if candidates:
        _, mount = max(candidates)
        base = Path(mount) / f"{branding_id}-rollback-{disk_label}-{stamp}"
        mode = "external"
    else:
        required = size + 128 * 2**20
        run_free = shutil.disk_usage("/run").free
        ram_free = _available_ram()
        if run_free < required or ram_free < required:
            raise SnapshotError(
                f"no separate backup disk with at least 256 GiB and {size // (1024**3)} GiB free was found; "
                f"RAM fallback needs {required // (1024**3)} GiB available but only "
                f"{min(run_free, ram_free) // (1024**3)} GiB is available"
            )
        base = Path("/run") / f"{branding_id}-rollback-{disk_label}-{os.getpid()}-{stamp}"
        mode = "ram"

    base.mkdir(parents=True, exist_ok=False)
    image = base / "disk.img"
    manifest = base / "packages.jsonl"
    metadata = base / "snapshot.json"
    try:
        log(f"Creating {mode} rollback snapshot ({size // (1024**3)} GiB)")
        image_sha256 = _copy_image(target_disk, image, size, log)
        _export_previous_system(target_disk, base, manifest, log, copy_home=copy_home and mode == "external")
        meta = {"version": 2, "disk": target_disk, "size_bytes": size, "mode": mode,
                "created_at": int(time.time()), "image": str(image), "manifest": str(manifest),
                "image_sha256": image_sha256}
        metadata.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        with metadata.open("rb+") as fh:
            os.fsync(fh.fileno())
        verify = hashlib.sha256()
        with image.open("rb", buffering=0) as fh:
            while True:
                block = fh.read(CHUNK)
                if not block:
                    break
                verify.update(block)
        if verify.hexdigest() != image_sha256:
            raise SnapshotError("rollback image checksum verification failed")
        log(f"Verified rollback snapshot at {base}")
        return meta
    except Exception:
        shutil.rmtree(base, ignore_errors=True)
        raise


def restore(snapshot: dict[str, Any], log) -> None:
    """Restore the exact disk image after the installer has unmounted it."""
    image = Path(snapshot["image"])
    disk = snapshot["disk"]
    expected = int(snapshot["size_bytes"])
    if not image.is_file() or image.stat().st_size != expected:
        raise SnapshotError("rollback image is missing or incomplete; refusing an unsafe restore")
    digest = hashlib.sha256()
    with image.open("rb", buffering=0) as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            digest.update(block)
    if digest.hexdigest() != snapshot.get("image_sha256"):
        raise SnapshotError("rollback image checksum mismatch; refusing an unsafe restore")
    current = int(_run(["blockdev", "--getsize64", disk]).strip())
    if current != expected:
        raise SnapshotError("target disk size changed; refusing to restore to a different-sized disk")
    disk_real = os.path.realpath(disk)
    mounted: list[str] = []
    for node in _tree():
        if os.path.realpath(node.get("_parent_disk", "")) == disk_real or os.path.realpath(node.get("name", "")) == disk_real:
            mounted.extend(m for m in (node.get("mountpoints") or []) if m)
    if mounted:
        raise SnapshotError("cannot restore while target partitions are mounted: " + ", ".join(mounted))
    log(f"Restoring original disk image to {disk}")
    copied = 0
    with image.open("rb", buffering=0) as src, open(disk, "wb", buffering=0) as dst:
        while True:
            block = src.read(CHUNK)
            if not block:
                break
            dst.write(block)
            copied += len(block)
        dst.flush()
        os.fsync(dst.fileno())
    if copied != expected:
        raise SnapshotError(f"restore was incomplete: wrote {copied} of {expected} bytes")
    subprocess.run(["partprobe", disk], check=False, capture_output=True)
    subprocess.run(["udevadm", "settle"], check=False, capture_output=True)
    log("Original partition table and installation restored")


def discard_ram_snapshot(snapshot: dict[str, Any]) -> None:
    """Release a RAM-backed image after successful installation."""
    if snapshot.get("mode") == "ram":
        shutil.rmtree(Path(snapshot["image"]).parent, ignore_errors=True)


def physical_disk(device: str) -> str:
    """Resolve a partition or mapper device to its parent physical disk."""
    rows = _run(["lsblk", "-s", "-n", "-p", "-o", "NAME,TYPE", device]).splitlines()
    for row in reversed(rows):
        fields = row.split()
        if len(fields) >= 2 and fields[1] == "disk":
            return fields[0]
    raise SnapshotError(f"cannot resolve a physical disk for {device}")


def create_many(target_disks: list[str], branding_id: str, log) -> list[dict[str, Any]]:
    """Snapshot every physical disk that the install plan may format."""
    targets = list(dict.fromkeys(os.path.realpath(d) for d in target_disks if d))
    if not targets:
        raise SnapshotError("the destructive plan does not identify any physical target disk")
    snapshots: list[dict[str, Any]] = []
    try:
        for index, disk in enumerate(targets):
            snapshots.append(create(disk, branding_id, log, exclude_disks=targets, copy_home=index == 0))
        return snapshots
    except Exception:
        for snapshot in snapshots:
            if snapshot.get("mode") == "ram":
                shutil.rmtree(Path(snapshot["image"]).parent, ignore_errors=True)
        raise
