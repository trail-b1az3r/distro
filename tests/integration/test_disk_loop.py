"""Real partitioning on loop devices.

Runs the installer's own partition/format/mount/cleanup steps against sparse
image files attached as loop devices. Needs root, losetup, sfdisk and ext4
support; skipped otherwise. (Btrfs, FAT and LUKS need kernel modules that
minimal CI containers lack; the QEMU tests in tests/qemu cover them.)
"""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from distrokit import util
from distrokit.hardware.storage import Disk, Partition
from distrokit.installer import disks
from distrokit.installer.config import InstallConfig
from distrokit.installer.steps import Installation

GiB = 2**30


def _can_loop() -> bool:
    if os.geteuid() != 0 or not all(shutil.which(t) for t in ("losetup", "sfdisk", "mkfs.ext4", "partprobe")):
        return False
    return "ext4" in Path("/proc/filesystems").read_text()


pytestmark = pytest.mark.skipif(not _can_loop(), reason="needs root, loop devices, sfdisk and ext4")


@pytest.fixture
def loopdisk(tmp_path):
    img = tmp_path / "disk.img"
    subprocess.run(["truncate", "-s", "64G", str(img)], check=True)
    dev = subprocess.run(["losetup", "-fP", "--show", str(img)], check=True, capture_output=True, text=True).stdout.strip()
    yield dev
    subprocess.run(["umount", "-R", str(tmp_path / "target")], capture_output=True)
    subprocess.run(["losetup", "-d", dev], check=False)


def table(dev: str) -> list[dict]:
    out = subprocess.run(["sfdisk", "--json", dev], check=True, capture_output=True, text=True).stdout
    return json.loads(out)["partitiontable"]["partitions"]


def as_disk(dev: str, partitions: list[Partition] | None = None) -> Disk:
    size = int(subprocess.run(["blockdev", "--getsize64", dev], check=True, capture_output=True, text=True).stdout)
    return Disk(name=Path(dev).name, path=dev, size_bytes=size, model="Loop test disk", vendor="", transport="other",
                rotational=False, removable=False, read_only=False, logical_sector=512, partition_table="gpt",
                partitions=partitions or [])


def base_cfg(**disk) -> InstallConfig:
    return InstallConfig.from_dict({
        "hostname": "t", "user": {"username": "t", "password": "password"},
        "disk": {"filesystem": "ext4", "swap": "none", **disk},
    })


def make_installation(machine, cfg, disk, uefi, target) -> Installation:
    _, report = machine("qemu_vm")
    report.firmware.uefi = uefi
    report.disks = [disk]
    inst = Installation(cfg, report, runner=util.Runner(dry_run=False), target=target, online=False)
    return inst


@pytest.mark.parametrize("uefi,swap,home", [(True, "partition", True), (False, "none", False), (True, "none", False)])
def test_erase_scripts_are_accepted_by_sfdisk(loopdisk, uefi, swap, home):
    disk = as_disk(loopdisk)
    cfg = base_cfg(mode="erase", disk=loopdisk, swap=swap, separate_home=home, swap_size_gib=2)
    plan = disks.plan_disks(cfg, disk, uefi=uefi, ram_bytes=8 * GiB)
    subprocess.run(["sfdisk", "--wipe", "always", loopdisk], input=plan.sfdisk_script, text=True, check=True,
                   capture_output=True)
    parts = table(loopdisk)
    assert len(parts) == len(plan.volumes)
    for v, p in zip(plan.volumes, parts):
        assert p["node"] == v.device
        assert p["type"].upper() == v.type_guid
        if v.size_bytes:
            assert p["size"] * 512 == v.size_bytes
    # The last partition fills the disk (minus the backup GPT).
    last = parts[-1]
    assert (last["start"] + last["size"]) * 512 > disk.size_bytes - 2 * 2**20


def test_bios_ext4_install_disk_stage(loopdisk, machine, tmp_path):
    disk = as_disk(loopdisk)
    target = tmp_path / "target"
    cfg = base_cfg(mode="erase", disk=loopdisk)
    inst = make_installation(machine, cfg, disk, uefi=False, target=target)
    inst.partition()
    inst.format()
    inst.mount()
    try:
        out = subprocess.run(["findmnt", "-n", "-o", "SOURCE,FSTYPE", str(target)], capture_output=True, text=True).stdout
        assert f"{loopdisk}p2" in out and "ext4" in out
        (target / "hello").write_text("installed")
        params = inst._root_params()
        assert params[0].startswith("root=UUID=") and "rw" in params
    finally:
        inst.cleanup()
    assert not os.path.ismount(target)
    parts = table(loopdisk)
    assert parts[0]["type"].upper() == disks.BIOS_BOOT_TYPE


def test_free_space_keeps_existing_data_and_rolls_back(loopdisk, machine, tmp_path):
    # An existing 8 GiB "other OS" partition with data on it.
    subprocess.run(["sfdisk", loopdisk], input="label: gpt\nsize=8GiB, type=L\n", text=True, check=True,
                   capture_output=True)
    subprocess.run(["partprobe", loopdisk], check=False)
    existing = f"{loopdisk}p1"
    subprocess.run(["mkfs.ext4", "-q", "-F", "-L", "OTHER", existing], check=True)
    mnt = tmp_path / "other"
    mnt.mkdir()
    subprocess.run(["mount", existing, str(mnt)], check=True)
    (mnt / "precious.txt").write_text("do not lose me\n" * 1000)
    subprocess.run(["umount", str(mnt)], check=True)
    before = hashlib.sha256(Path(existing).read_bytes()[: 64 * 2**20]).hexdigest()

    p1 = table(loopdisk)[0]
    disk = as_disk(loopdisk, [Partition("p1", existing, 1, p1["start"] * 512, p1["size"] * 512, fstype="ext4",
                                        parttype=disks.LINUX_FS_TYPE.lower())])
    target = tmp_path / "target"
    cfg = base_cfg(mode="free-space", disk=loopdisk)
    inst = make_installation(machine, cfg, disk, uefi=False, target=target)
    assert "Existing partitions are not changed" in inst.disk_plan.summary[0]
    inst.partition()
    inst.format()
    parts = table(loopdisk)
    assert len(parts) == 3  # existing + BIOS boot + root
    assert parts[0]["start"] == p1["start"] and parts[0]["size"] == p1["size"]
    after = hashlib.sha256(Path(existing).read_bytes()[: 64 * 2**20]).hexdigest()
    assert before == after, "the existing partition was modified"

    # A failure now must remove what the installer created.
    inst.cleanup(failed=True)
    subprocess.run(["partprobe", loopdisk], check=False)
    assert len(table(loopdisk)) == 1
    subprocess.run(["mount", existing, str(mnt)], check=True)
    try:
        assert (mnt / "precious.txt").read_text().startswith("do not lose me")
    finally:
        subprocess.run(["umount", str(mnt)], check=True)
