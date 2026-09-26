"""Hardware detection against fixture machines (tests/hwfixtures.py)."""

import pytest

from distrokit.hardware import display, ids
from hwfixtures import make_edid


def test_parse_ids_subsystems():
    db = ids.parse_ids("10de  NVIDIA Corporation\n\t2702  AD103 [GeForce RTX 4080 SUPER]\n\t\t1043 8888  TUF RTX 4080 SUPER\nC 00  x\n")
    assert db.device(0x10DE, 0x2702) == "AD103 [GeForce RTX 4080 SUPER]"
    assert db.subsystem(0x10DE, 0x2702, 0x1043, 0x8888) == "TUF RTX 4080 SUPER"
    assert ids.marketing_name("AD103 [GeForce RTX 4080 SUPER]") == "GeForce RTX 4080 SUPER"
    assert ids.codename("AD103 [GeForce RTX 4080 SUPER]") == "AD103"


def test_edid_roundtrip():
    edid = display.parse_edid(make_edid("DELL U2723QE", 3840, 2160, 597, 336, "DEL"))
    assert edid is not None
    assert (edid.manufacturer, edid.name) == ("DEL", "DELL U2723QE")
    assert (edid.preferred_width, edid.preferred_height) == (3840, 2160)
    assert (edid.width_mm, edid.height_mm) == (597, 336)
    assert display.parse_edid(b"garbage") is None


@pytest.mark.parametrize(
    "w,h,mm,internal,expected",
    [
        (1920, 1080, 531, False, 1.0),  # 24" 1080p desktop
        (3840, 2160, 597, False, 1.666667),  # 27" 4K
        (1920, 1200, 301, True, 1.5),  # 14" laptop
        (2560, 1600, 302, True, 2.0),  # 14" 2.5K laptop
        (1280, 800, 0, False, 1.0),  # unknown physical size
    ],
)
def test_recommend_scale(w, h, mm, internal, expected):
    scale = display.recommend_scale(w, h, mm, internal)
    assert scale == pytest.approx(expected)
    # Hyprland needs whole logical pixels.
    assert abs(w / scale - round(w / scale)) < 1e-3


def test_rtx4080_desktop(machine):
    _, r = machine("rtx4080_desktop")
    assert r.cpu.vendor == "amd" and r.cpu.model == "AMD Ryzen 9 7950X"
    assert r.cpu.microcode_package == "amd-ucode"
    assert r.memory.marketing_gb() == 64
    assert r.chassis.kind == "desktop" and not r.chassis.portable
    assert len(r.gpus) == 1
    gpu = r.gpus[0]
    assert (gpu.vendor, gpu.model, gpu.architecture, gpu.driver_branch) == ("nvidia", "GeForce RTX 4080 SUPER", "ada", "open")
    assert gpu.vram_gib == 16 and gpu.vram_source == "estimate"
    assert gpu.connectors == ["DP-1"]
    assert r.topology.mode == "single"
    assert r.external_displays and not any(d.internal for d in r.displays)
    assert r.wifi[0].vendor == "MediaTek"
    assert r.bluetooth and r.bluetooth[0].present_as_hci
    assert r.firmware.uefi and r.firmware.secure_boot is False


def test_hybrid_laptop_matches_brief_example(machine):
    _, r = machine("hybrid_gtx1080_laptop")
    rows = dict(r.summary_rows())
    assert rows["CPU"].startswith("Intel Core i7-7700HQ")
    assert rows["RAM"] == "32 GB"
    assert "1 TB NVMe SSD" in rows["Storage"]
    assert "1920 × 1080" in rows["Display"]
    assert "Intel" in rows["Wi-Fi"]
    assert r.chassis.kind == "laptop" and r.has_touchpad
    kinds = {g.vendor: g.kind for g in r.gpus}
    assert kinds == {"intel": "integrated", "nvidia": "discrete"}
    assert r.topology.mode == "hybrid"
    assert r.topology.primary.vendor == "intel" and r.topology.offload.vendor == "nvidia"
    nv = r.nvidia[0]
    assert nv.architecture == "pascal" and nv.driver_branch == "legacy580"


def test_surface_pro7(machine):
    _, r = machine("surface_pro7")
    assert r.chassis.surface and r.chassis.surface_model == "Surface Pro 7"
    assert r.has_touchscreen and r.has_pen and r.has_touchpad
    assert r.displays[0].internal and r.displays[0].hidpi
    assert r.gpus[0].architecture == "gen11"
    disk = r.disks[0]
    assert disk.existing_systems == ["Windows"]
    assert any(p.is_esp for p in disk.partitions)
    assert r.firmware.secure_boot is True


def test_virtual_machine(machine):
    _, r = machine("qemu_vm")
    assert r.virt.is_virtual and r.virt.guest_list == "virt-qemu"
    assert r.chassis.kind == "vm"
    assert r.gpus[0].kind == "virtual"
    assert [d.name for d in r.disks] == ["vda"]  # sr0 skipped
    assert r.disks[0].transport == "virtio"
    assert not r.wifi


def test_amd_devices(machine):
    _, r = machine("rx7900xtx_desktop")
    gpu = r.gpus[0]
    assert gpu.model == "NITRO+ Radeon RX 7900 XTX Vapor-X"  # subsystem name wins
    assert gpu.vram_gib == 24 and gpu.vram_source == "driver"
    assert gpu.extras["rocm"] == "native" and gpu.extras["gfx"] == "gfx1100"
    hdd = next(d for d in r.disks if d.name == "sda")
    assert hdd.rotational and hdd.kind == "HDD"
    assert hdd.existing_systems == ["Linux"]
    assert r.topology.mode == "single"

    _, apu = machine("rembrandt_laptop")
    g = apu.gpus[0]
    assert g.kind == "integrated" and g.extras["hsa_override_gfx_version"] == "10.3.0"
    assert g.model == "Radeon 680M"


def test_amd_apu_named_from_cpu(machine):
    _, r = machine("amd_hybrid_laptop")
    igpu = next(g for g in r.gpus if g.kind == "integrated")
    assert igpu.model.startswith("Radeon 780M Graphics")
    assert r.topology.mode == "hybrid"
    dgpu = next(g for g in r.gpus if g.kind == "discrete")
    assert dgpu.extras["gfx"] == "gfx1102"


def test_ambiguous_vram_estimate_is_conservative():
    from distrokit.hardware.graphics import estimate_vram

    # One PCI ID covers the 7900 XT (20 GB), XTX (24 GB) and GRE (16 GB).
    assert estimate_vram("amd", "Radeon RX 7900 XT/7900 XTX/7900 GRE/7900M") == 16 * 2**30
    assert estimate_vram("nvidia", "GeForce RTX 4080 SUPER") == 16 * 2**30
    assert estimate_vram("nvidia", "GeForce GTX 1080 Mobile") == 8 * 2**30
    assert estimate_vram("nvidia", "Some Future GPU") == 0


def test_multi_gpu_desktop_primary_is_display_gpu(machine):
    _, r = machine("arc_desktop")
    assert r.topology.mode == "multi"
    assert r.topology.primary.model == "Arc A770"
    arc = r.topology.primary
    assert arc.kind == "discrete" and arc.architecture == "xe-hpg"


def test_live_medium_excluded(machine):
    _, r = machine("live_usb_machine")
    usb = next(d for d in r.disks if d.name == "sdb")
    assert usb.live_medium and not usb.installable
    assert [d.name for d in r.installable_disks] == ["nvme0n1"]


def test_free_regions(machine):
    _, r = machine("surface_pro7")
    disk = r.disks[0]
    regions = disk.free_regions()
    # 256 GB disk with ~120 GB used by Windows leaves one large trailing gap.
    assert len(regions) == 1
    assert regions[0].size_bytes > 100 * 10**9
    assert regions[0].start_bytes % (1024 * 1024) == 0


def test_report_json_roundtrip(machine):
    import json

    _, r = machine("surface_pro7")
    data = json.loads(r.to_json())
    assert data["chassis"]["surface"] is True
    assert data["input"]["touchscreen"] is True
    assert data["disks"][0]["free_regions"]


def test_input_fallback_without_udev(tmp_path):
    from distrokit.hardware import inputdev
    from distrokit.hardware.sysroot import SysRoot

    (tmp_path / "proc/bus/input").mkdir(parents=True)
    (tmp_path / "proc/bus/input/devices").write_text(
        'I: Bus=0018 Vendor=04f3 Product=2af1 Version=0100\nN: Name="ELAN2514:00 04F3:2AF1"\nH: Handlers=mouse1 event7\nB: PROP=2\n\n'
        'I: Bus=0018 Vendor=06cb Product=cd7e Version=0100\nN: Name="SYNA2B52:00 06CB:CD7E Touchpad"\nH: Handlers=mouse0 event8\nB: PROP=5\n\n'
        'I: Bus=0018 Vendor=04f3 Product=2af1 Version=0100\nN: Name="ELAN2514:00 04F3:2AF1 Stylus"\nH: Handlers=event9\nB: PROP=2\n'
    )
    kinds = [d.kind for d in inputdev.detect_input(SysRoot(tmp_path))]
    assert kinds == ["touchscreen", "touchpad", "pen"]
