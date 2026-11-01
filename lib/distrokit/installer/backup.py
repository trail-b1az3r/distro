"""Verified pre-install rollback snapshots.

The snapshot is a raw image of the target disk, not a filesystem-level
approximation. It is written only to a different physical disk with enough
free space, or to /run when the live tmpfs and MemAvailable can hold it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

MIN_BACKUP_DISK = 256 * 2**30
CHUNK = 16 * 2**20


class SnapshotError(RuntimeError):
    pass


def _run(args: list[str]) -> str:
    proc = subprocess.run(args, text=True, capture_output=True, check=False)
    if proc.returncode:
        raise SnapshotError(proc.stderr.strip() or f"{args[0]} failed")
    return proc.stdout


def _tree() -> list[dict[str, Any]]:
    try:
        data = json.loads(_run(["lsblk", "-J", "-b", "-o", "NAME,TYPE,SIZE,MOUNTPOINTS,PKNAME"]))
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


def _copy_image(source: str, destination: Path, expected: int, log) -> None:
    copied = 0
    with open(source, "rb", buffering=0) as src, destination.open("wb", buffering=0) as dst:
        while True:
            block = src.read(CHUNK)
            if not block:
                break
            dst.write(block)
            copied += len(block)
            if copied and copied % (1024**3) < CHUNK:
                log(f"Snapshot copied {copied // (1024**3)} GiB of {expected // (1024**3)} GiB")
        dst.flush()
        os.fsync(dst.fileno())
    if copied != expected:
        destination.unlink(missing_ok=True)
        raise SnapshotError(f"snapshot size mismatch: copied {copied} bytes, expected {expected}")


def _manifest(destination: Path, log) -> None:
    packages = _run(["pacman", "-Q"]).splitlines()
    foreign = set()
    proc = subprocess.run(["pacman", "-Qm"], text=True, capture_output=True, check=False)
    if proc.returncode == 0:
        foreign = {line.split()[0] for line in proc.stdout.splitlines() if line.split()}
    files_proc = subprocess.run(["pacman", "-Ql"], text=True, capture_output=True, check=False)
    if files_proc.returncode:
        raise SnapshotError("could not export Pacman package file ownership")
    paths: dict[str, list[str]] = {}
    for line in files_proc.stdout.splitlines():
        name, sep, path = line.partition(" ")
        if sep:
            paths.setdefault(name, []).append(path)
    with destination.open("w", encoding="utf-8") as out:
        out.write(json.dumps({"type": "inventory", "scope": "installer_live_environment", "note": "The raw disk image is the authoritative backup of the pre-install OS."}) + "\n")
        for line in packages:
            fields = line.split()
            if len(fields) < 2:
                continue
            name, version = fields[0], fields[1]
            out.write(json.dumps({"type": "package", "name": name, "version": version,
                                  "source": "aur" if name in foreign else "repository"},
                                 ensure_ascii=False) + "\n")
            for path in paths.get(name, []):
                out.write(json.dumps({"type": "file", "package": name, "path": path},
                                     ensure_ascii=False) + "\n")
        out.flush()
        os.fsync(out.fileno())
    log(f"Saved package and owned-file inventory ({len(packages)} packages)")


def create(target_disk: str, branding_id: str, log) -> dict[str, Any]:
    """Create and verify a raw-disk rollback image before partitioning."""
    target = Path(target_disk)
    if not target.exists():
        raise SnapshotError(f"target disk disappeared: {target_disk}")
    size_text = _run(["blockdev", "--getsize64", target_disk]).strip()
    size = int(size_text)
    if size <= 0:
        raise SnapshotError("could not determine the target disk size")
    nodes = _tree()
    target_real = os.path.realpath(target_disk)
    candidates: list[tuple[int, str]] = []
    for node in nodes:
        if node.get("type") != "disk" or int(node.get("size") or 0) < MIN_BACKUP_DISK:
            continue
        if os.path.realpath(node.get("name", "")) == target_real:
            continue
        parent = node.get("name", "")
        for part in nodes:
            if part.get("_parent_disk") != parent:
                continue
            mounts = part.get("mountpoints") or []
            for mount in mounts:
                if not mount or mount in ("/", "/run", "/tmp"):
                    continue
                try:
                    free = shutil.disk_usage(mount).free
                except OSError:
                    continue
                if free >= size + 128 * 2**20:
                    candidates.append((free, mount))
    base: Path
    mode: str
    if candidates:
        _, mount = max(candidates)
        base = Path(mount) / f"{branding_id}-rollback-{int(time.time())}"
        mode = "external"
    else:
        run_free = shutil.disk_usage("/run").free
        ram_free = _available_ram()
        required = size + 128 * 2**20
        if run_free < required or ram_free < required:
            raise SnapshotError(
                f"no separate backup disk with at least 256 GiB and {size // (1024**3)} GiB free was found; "
                f"RAM fallback needs {required // (1024**3)} GiB available but only "
                f"{min(run_free, ram_free) // (1024**3)} GiB is available"
            )
        base = Path("/run") / f"{branding_id}-rollback-{os.getpid()}"
        mode = "ram"
    base.mkdir(parents=True, exist_ok=False)
    image = base / "disk.img"
    manifest = base / "packages.jsonl"
    metadata = base / "snapshot.json"
    try:
        log(f"Creating {mode} rollback snapshot ({size // (1024**3)} GiB)")
        _copy_image(target_disk, image, size, log)
        _manifest(manifest, log)
        meta = {"version": 1, "disk": target_disk, "size_bytes": size, "mode": mode,
                "created_at": int(time.time()), "image": str(image), "manifest": str(manifest)}
        metadata.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        with metadata.open("rb+") as fh:
            os.fsync(fh.fileno())
        # Read the complete image back to ensure it is accessible and the
        # expected number of bytes can be read before any destructive action.
        if image.stat().st_size != size:
            raise SnapshotError("rollback image verification failed")
        with image.open("rb", buffering=0) as fh:
            first = fh.read(min(CHUNK, size))
            fh.seek(max(0, size - min(CHUNK, size)))
            last = fh.read(min(CHUNK, size))
        if not first or not last:
            raise SnapshotError("rollback image verification failed")
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
    current = int(_run(["blockdev", "--getsize64", disk]).strip())
    if current != expected:
        raise SnapshotError("target disk size changed; refusing to restore to a different-sized disk")
    tree = _tree()
    mounted = []
    for node in tree:
        if node.get("_parent_disk") == disk or node.get("name") == disk:
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
    parent = _run(["lsblk", "-n", "-o", "PKNAME", device]).strip().splitlines()
    if parent and parent[-1].strip():
        return str(Path("/dev") / parent[-1].strip())
    return os.path.realpath(device)


def create_many(target_disks: list[str], branding_id: str, log) -> list[dict[str, Any]]:
    """Snapshot every physical disk that the install plan may format."""
    targets = list(dict.fromkeys(os.path.realpath(d) for d in target_disks if d))
    if not targets:
        raise SnapshotError("the destructive plan does not identify any physical target disk")
    snapshots: list[dict[str, Any]] = []
    try:
        for disk in targets:
            snapshots.append(create(disk, branding_id, log, exclude_disks=targets))
        return snapshots
    except Exception:
        for snapshot in snapshots:
            if snapshot.get("mode") == "ram":
                shutil.rmtree(Path(snapshot["image"]).parent, ignore_errors=True)
        raise
