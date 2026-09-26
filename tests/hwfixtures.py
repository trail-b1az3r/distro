"""Build fake /sys, /proc and /run trees for hardware-detection tests.

Each machine below mirrors what the kernel exposes on the real hardware
(PCI IDs, class codes, DMI strings, EDID, input properties), so detection is
exercised end to end through the same files it reads on a live system.
"""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path

# A subset of hwdata's pci.ids / usb.ids with the devices used below, in the
# upstream format (tab-indented devices and subsystems).
PCI_IDS = """\
# Test subset of pci.ids
1002  Advanced Micro Devices, Inc. [AMD/ATI]
\t15bf  Phoenix1
\t1681  Rembrandt [Radeon 680M]
\t6798  Tahiti XT [Radeon HD 7970/8970 OEM / R9 280X]
\t744c  Navi 31 [Radeon RX 7900 XT/7900 XTX/7900 GRE/7900M]
\t\t1da2 471e  NITRO+ Radeon RX 7900 XTX Vapor-X
\t7480  Navi 33 [Radeon RX 7700S/7600/7600S/7600M XT/PRO W7600]
10de  NVIDIA Corporation
\t1004  GK110 [GeForce GTX 780]
\t1b80  GP104 [GeForce GTX 1080]
\t1be0  GP104BM [GeForce GTX 1080 Mobile]
\t2520  GA106M [GeForce RTX 3060 Mobile / Max-Q]
\t2702  AD103 [GeForce RTX 4080 SUPER]
\t22bb  AD103 High Definition Audio Controller
144d  Samsung Electronics Co Ltd
\ta80a  NVMe SSD Controller PM9A1/PM9A3/980PRO
1af4  Red Hat, Inc.
\t1041  Virtio 1.0 network device
\t1042  Virtio 1.0 block device
\t1050  Virtio 1.0 GPU
8086  Intel Corporation
\t24fd  Wireless 8265 / 8275
\t34f0  Ice Lake-LP PCH CNVi WiFi
\t56a0  DG2 [Arc A770]
\t591b  HD Graphics 630
\t8a5a  Iris Plus Graphics G4 (Ice Lake)
\ta780  Raptor Lake-S GT1 [UHD Graphics 770]
\t2725  Wi-Fi 6E(802.11ax) AX210/AX1675* 2x2 [Typhoon Peak]
14c3  MEDIATEK Corp.
\t0616  MT7922 802.11ax PCI Express Wireless Network Adapter
C 00  Unclassified device
"""

USB_IDS = """\
8087  Intel Corp.
\t0026  AX201 Bluetooth
\t0032  AX210 Bluetooth
\t0a2b  Bluetooth wireless interface
0e8d  MediaTek Inc.
\t0616  Wireless_Device
"""


def make_edid(name: str, width: int, height: int, width_mm: int, height_mm: int, mfg: str = "SAM",
              product: int = 0x1234) -> bytes:
    """A valid EDID 1.4 base block with one detailed timing and a name."""
    edid = bytearray(128)
    edid[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    word = ((ord(mfg[0]) - 64) << 10) | ((ord(mfg[1]) - 64) << 5) | (ord(mfg[2]) - 64)
    edid[8:10] = struct.pack(">H", word)
    edid[10:12] = struct.pack("<H", product)
    edid[18], edid[19] = 1, 4
    edid[21], edid[22] = width_mm // 10, height_mm // 10
    # Detailed timing descriptor (only the fields the parser reads matter).
    dtd = bytearray(18)
    dtd[0:2] = struct.pack("<H", 14850)  # pixel clock, non-zero
    dtd[2] = width & 0xFF
    dtd[4] = (width >> 8) << 4
    dtd[5] = height & 0xFF
    dtd[7] = (height >> 8) << 4
    dtd[12] = width_mm & 0xFF
    dtd[13] = height_mm & 0xFF
    dtd[14] = ((width_mm >> 8) << 4) | (height_mm >> 8)
    edid[54:72] = dtd
    name_desc = bytearray(18)
    name_desc[3] = 0xFC
    text = name.encode()[:13]
    name_desc[5 : 5 + len(text)] = text
    if len(text) < 13:
        name_desc[5 + len(text)] = 0x0A
        for i in range(5 + len(text) + 1, 18):
            name_desc[i] = 0x20
    edid[72:90] = name_desc
    for off in (90, 108):
        edid[off + 3] = 0x10  # dummy descriptor
    edid[127] = (-sum(edid[:127])) % 256
    return bytes(edid)


class FakeMachine:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._input_blocks: list[str] = []
        self._event = 0
        self._lsblk: list[dict] = []
        self.write("/usr/share/hwdata/pci.ids", PCI_IDS)
        self.write("/usr/share/hwdata/usb.ids", USB_IDS)
        self.write("/proc/bus/input/devices", "")
        for d in ("/sys/bus/pci/devices", "/sys/class/drm", "/sys/block", "/sys/class/net",
                  "/sys/class/power_supply", "/sys/bus/usb/devices", "/sys/class/bluetooth"):
            self.mkdir(d)

    # -- primitives ---------------------------------------------------------
    def path(self, p: str) -> Path:
        return self.root / p.lstrip("/")

    def mkdir(self, p: str) -> Path:
        path = self.path(p)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(self, p: str, content: str | bytes) -> None:
        path = self.path(p)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)

    def symlink(self, p: str, target: str) -> None:
        path = self.path(p)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or path.exists():
            path.unlink()
        os.symlink(target, path)

    def _devlink(self, link: str, real: str) -> None:
        """Symlink a /sys/class entry to its /sys/devices directory, relative
        like the kernel does, so realpath() resolves inside the fake root."""
        self.mkdir(real)
        rel = os.path.relpath(self.path(real), self.path(link).parent)
        self.symlink(link, rel)

    # -- platform -----------------------------------------------------------
    def cpu(self, vendor_id: str, model: str, cores: int, threads: int, flags: str = "fpu sse sse2 ssse3 sse4_1 sse4_2 popcnt avx avx2 fma bmi1 bmi2 movbe xsave cx16 lahf_lm f16c",
            family: int = 6, model_no: int = 158) -> "FakeMachine":
        blocks = []
        per_core = max(1, threads // cores)
        for i in range(threads):
            blocks.append(
                f"processor\t: {i}\nvendor_id\t: {vendor_id}\ncpu family\t: {family}\nmodel\t\t: {model_no}\n"
                f"model name\t: {model}\nphysical id\t: 0\ncore id\t\t: {i // per_core}\ncpu cores\t: {cores}\nflags\t\t: {flags}\n"
            )
        self.write("/proc/cpuinfo", "\n".join(blocks) + "\n")
        return self

    def memory(self, gib: float, swap_gib: float = 0) -> "FakeMachine":
        kb = int(gib * 1024 * 1024 * 0.97)  # MemTotal excludes reserved memory
        self.write("/proc/meminfo", f"MemTotal:       {kb} kB\nMemFree:        {kb // 2} kB\nSwapTotal:      {int(swap_gib * 1048576)} kB\n")
        return self

    def dmi(self, vendor: str, product: str, chassis_type: int, family: str = "", version: str = "") -> "FakeMachine":
        base = "/sys/class/dmi/id"
        for k, v in {"sys_vendor": vendor, "product_name": product, "product_family": family,
                     "product_version": version, "chassis_type": str(chassis_type), "board_vendor": vendor,
                     "board_name": product, "bios_vendor": "American Megatrends", "bios_version": "1.0"}.items():
            self.write(f"{base}/{k}", v + "\n")
        return self

    def battery(self) -> "FakeMachine":
        self.write("/sys/class/power_supply/BAT0/type", "Battery\n")
        self.write("/sys/class/power_supply/AC/type", "Mains\n")
        return self

    def lid(self) -> "FakeMachine":
        self.write("/proc/acpi/button/lid/LID0/state", "state:      open\n")
        return self

    def uefi(self, secure_boot: bool | None = False, setup_mode: bool = False) -> "FakeMachine":
        self.write("/sys/firmware/efi/fw_platform_size", "64\n")
        guid = "8be4df61-93ca-11d2-aa0d-00e098032b8c"
        if secure_boot is not None:
            self.write(f"/sys/firmware/efi/efivars/SecureBoot-{guid}", b"\x06\x00\x00\x00" + bytes([1 if secure_boot else 0]))
            self.write(f"/sys/firmware/efi/efivars/SetupMode-{guid}", b"\x06\x00\x00\x00" + bytes([1 if setup_mode else 0]))
        return self

    def acpi_device(self, hid: str) -> "FakeMachine":
        self.mkdir(f"/sys/bus/acpi/devices/{hid}:00")
        return self

    # -- PCI ----------------------------------------------------------------
    def pci(self, slot: str, cls: int, vid: int, did: int, driver: str | None = None, boot_vga: bool | None = None,
            svid: int = 0, sdid: int = 0, extra: dict[str, str] | None = None) -> "FakeMachine":
        real = f"/sys/devices/pci0000:00/{slot}"
        self._devlink(f"/sys/bus/pci/devices/{slot}", real)
        self.write(f"{real}/class", f"0x{cls:06x}\n")
        self.write(f"{real}/vendor", f"0x{vid:04x}\n")
        self.write(f"{real}/device", f"0x{did:04x}\n")
        self.write(f"{real}/subsystem_vendor", f"0x{svid:04x}\n")
        self.write(f"{real}/subsystem_device", f"0x{sdid:04x}\n")
        if boot_vga is not None:
            self.write(f"{real}/boot_vga", "1\n" if boot_vga else "0\n")
        if driver:
            self.symlink(f"{real}/driver", f"../../../bus/pci/drivers/{driver}")
        for k, v in (extra or {}).items():
            self.write(f"{real}/{k}", v)
        return self

    def gpu_card(self, card: str, slot: str) -> "FakeMachine":
        self._devlink(f"/sys/class/drm/{card}", f"/sys/devices/pci0000:00/{slot}/drm/{card}")
        self.symlink(f"/sys/devices/pci0000:00/{slot}/drm/{card}/device", "../..")
        return self

    def connector(self, card: str, name: str, slot: str, edid: bytes | None, modes: list[str],
                  connected: bool = True) -> "FakeMachine":
        real = f"/sys/devices/pci0000:00/{slot}/drm/{card}/{card}-{name}"
        self._devlink(f"/sys/class/drm/{card}-{name}", real)
        self.write(f"{real}/status", "connected\n" if connected else "disconnected\n")
        self.write(f"{real}/modes", "\n".join(modes) + ("\n" if modes else ""))
        self.write(f"{real}/edid", edid or b"")
        return self

    # -- storage ------------------------------------------------------------
    def disk(self, name: str, size_bytes: int, model: str, transport: str = "nvme", rotational: bool = False,
             removable: bool = False, partitions: list[dict] | None = None, pttype: str = "gpt",
             mountpoints: list[str] | None = None, label: str | None = None) -> "FakeMachine":
        parent = {
            "nvme": "/sys/devices/pci0000:00/0000:00:1d.0/0000:6e:00.0/nvme/nvme0",
            "sata": "/sys/devices/pci0000:00/0000:00:17.0/ata1/host0/target0:0:0/0:0:0:0",
            "usb": "/sys/devices/pci0000:00/0000:00:14.0/usb2/2-1/2-1:1.0/host6/target6:0:0/6:0:0:0",
            "virtio": "/sys/devices/pci0000:00/0000:00:04.0/virtio2",
            "mmc": "/sys/devices/pci0000:00/0000:00:1a.0/mmc_host/mmc0/mmc0:0001",
        }[transport]
        real = f"{parent}/block/{name}"
        self._devlink(f"/sys/block/{name}", real)
        self.write(f"{real}/size", f"{size_bytes // 512}\n")
        self.write(f"{real}/removable", "1\n" if removable else "0\n")
        self.write(f"{real}/ro", "0\n")
        self.write(f"{real}/queue/rotational", "1\n" if rotational else "0\n")
        self.write(f"{real}/queue/logical_block_size", "512\n")
        self.write(f"{real}/device/model", model + "\n")
        children = []
        for i, part in enumerate(partitions or [], 1):
            pname = f"{name}p{i}" if name[-1].isdigit() else f"{name}{i}"
            self.write(f"{real}/{pname}/partition", f"{i}\n")
            self.write(f"{real}/{pname}/start", f"{part['start'] // 512}\n")
            self.write(f"{real}/{pname}/size", f"{part['size'] // 512}\n")
            children.append({
                "name": pname, "path": f"/dev/{pname}", "size": part["size"], "type": "part",
                "fstype": part.get("fstype"), "label": part.get("label"), "partlabel": part.get("partlabel"),
                "uuid": part.get("uuid", f"uuid-{pname}"), "parttype": part.get("parttype"),
                "mountpoints": part.get("mountpoints", [None]),
            })
        self._lsblk.append({"name": name, "path": f"/dev/{name}", "size": size_bytes, "type": "disk",
                            "pttype": pttype, "model": model, "label": label, "mountpoints": mountpoints or [None],
                            "children": children})
        self.write("/lsblk.json", json.dumps({"blockdevices": self._lsblk}))
        return self

    # -- network / USB / input ---------------------------------------------
    def usb(self, path: str, vid: int, pid: int, product: str, ifaces: list[tuple[int, int, int]]) -> "FakeMachine":
        real = f"/sys/devices/pci0000:00/0000:00:14.0/usb1/{path}"
        self._devlink(f"/sys/bus/usb/devices/{path}", real)
        self.write(f"{real}/idVendor", f"{vid:04x}\n")
        self.write(f"{real}/idProduct", f"{pid:04x}\n")
        self.write(f"{real}/product", product + "\n")
        for n, (c, s, p) in enumerate(ifaces):
            ipath = f"{path}:1.{n}"
            ireal = f"{real}/{ipath}"
            self._devlink(f"/sys/bus/usb/devices/{ipath}", ireal)
            self.write(f"{ireal}/bInterfaceClass", f"{c:02x}\n")
            self.write(f"{ireal}/bInterfaceSubClass", f"{s:02x}\n")
            self.write(f"{ireal}/bInterfaceProtocol", f"{p:02x}\n")
        return self

    def wifi_pci(self, iface: str, slot: str, driver: str) -> "FakeMachine":
        real = f"/sys/devices/pci0000:00/{slot}/net/{iface}"
        self._devlink(f"/sys/class/net/{iface}", real)
        self.mkdir(f"{real}/wireless")
        self.write(f"{real}/type", "1\n")
        self.symlink(f"{real}/device", "../..")
        return self

    def ethernet_virtio(self, iface: str, slot: str) -> "FakeMachine":
        real = f"/sys/devices/pci0000:00/{slot}/virtio0/net/{iface}"
        self._devlink(f"/sys/class/net/{iface}", real)
        self.write(f"{real}/type", "1\n")
        self.symlink(f"{real}/device", "../..")
        return self

    def bluetooth_usb(self, hci: str, usb_path: str) -> "FakeMachine":
        iface = f"/sys/devices/pci0000:00/0000:00:14.0/usb1/{usb_path}/{usb_path}:1.0"
        real = f"{iface}/bluetooth/{hci}"
        self._devlink(f"/sys/class/bluetooth/{hci}", real)
        self.symlink(f"{real}/device", "../..")
        return self

    def input(self, name: str, bus: str, prop: int, handlers: str, udev: dict[str, str] | None = None) -> "FakeMachine":
        ev = self._event
        self._event += 1
        self._input_blocks.append(
            f"I: Bus={bus} Vendor=0000 Product=0000 Version=0000\nN: Name=\"{name}\"\nP: Phys=\nS: Sysfs=/devices/virtual/input/input{ev}\n"
            f"U: Uniq=\nH: Handlers={handlers} event{ev}\nB: PROP={prop:x}\nB: EV=b\n"
        )
        self.write("/proc/bus/input/devices", "\n".join(self._input_blocks) + "\n")
        self.write(f"/sys/class/input/event{ev}/dev", f"13:{64 + ev}\n")
        if udev:
            self.write(f"/run/udev/data/c13:{64 + ev}", "".join(f"E:{k}={v}\n" for k, v in udev.items()))
        return self


GiB = 2**30
TB = 10**12
GB = 10**9


def standard_nvme(m: FakeMachine, size: int = 1 * TB, model: str = "Samsung SSD 980 PRO 1TB") -> None:
    m.pci("0000:6e:00.0", 0x010802, 0x144D, 0xA80A, "nvme")
    m.disk("nvme0n1", size, model, "nvme")


# ---------------------------------------------------------------------------
# Machines
# ---------------------------------------------------------------------------


def rtx4080_desktop(root: Path) -> FakeMachine:
    m = FakeMachine(root)
    m.cpu("AuthenticAMD", "AMD Ryzen 9 7950X 16-Core Processor", 16, 32, family=25, model_no=97)
    m.memory(64).dmi("ASUS", "ProArt X670E-CREATOR WIFI", 3).uefi(False)
    m.pci("0000:01:00.0", 0x030000, 0x10DE, 0x2702, "nouveau", boot_vga=True)
    m.pci("0000:01:00.1", 0x040300, 0x10DE, 0x22BB, "snd_hda_intel")
    m.gpu_card("card1", "0000:01:00.0")
    m.connector("card1", "DP-1", "0000:01:00.0", make_edid("DELL U2723QE", 3840, 2160, 597, 336, "DEL"), ["3840x2160", "2560x1440"])
    standard_nvme(m, 2 * TB, "Samsung SSD 990 PRO 2TB")
    m.pci("0000:05:00.0", 0x028000, 0x14C3, 0x0616, "mt7921e")
    m.wifi_pci("wlp5s0", "0000:05:00.0", "mt7921e")
    m.usb("1-7", 0x0E8D, 0x0616, "Wireless_Device", [(0xE0, 0x01, 0x01)])
    m.bluetooth_usb("hci0", "1-7")
    m.input("Logitech USB Receiver", "0003", 0, "sysrq kbd leds", {"ID_INPUT_KEYBOARD": "1"})
    m.input("Logitech USB Receiver Mouse", "0003", 0, "mouse0", {"ID_INPUT_MOUSE": "1"})
    return m


def rx7900xtx_desktop(root: Path) -> FakeMachine:
    m = FakeMachine(root)
    m.cpu("AuthenticAMD", "AMD Ryzen 7 7800X3D 8-Core Processor", 8, 16, family=25, model_no=97)
    m.memory(32).dmi("Micro-Star International Co., Ltd.", "MS-7D67", 3).uefi(True)
    m.pci("0000:03:00.0", 0x030000, 0x1002, 0x744C, "amdgpu", boot_vga=True, svid=0x1DA2, sdid=0x471E,
          extra={"mem_info_vram_total": str(24 * GiB)})
    m.gpu_card("card0", "0000:03:00.0")
    m.connector("card0", "DP-1", "0000:03:00.0", make_edid("LG ULTRAGEAR", 2560, 1440, 597, 336, "GSM"), ["2560x1440"])
    m.connector("card0", "HDMI-A-1", "0000:03:00.0", make_edid("LG TV", 3840, 2160, 1210, 680, "GSM"), ["3840x2160"])
    standard_nvme(m)
    m.disk("sda", 4 * TB, "ST4000DM004-2U9104", "sata", rotational=True,
           partitions=[{"start": 1 << 20, "size": 4 * TB - (2 << 20), "fstype": "ext4", "label": "Data"}])
    return m


def hybrid_gtx1080_laptop(root: Path) -> FakeMachine:
    """The example from the brief: i7-7700HQ, GTX 1080 (Mobile), 32 GB, 1 TB NVMe."""
    m = FakeMachine(root)
    m.cpu("GenuineIntel", "Intel(R) Core(TM) i7-7700HQ CPU @ 2.80GHz", 4, 8)
    m.memory(32).dmi("Micro-Star International Co., Ltd.", "GT73VR 7RF", 10).battery().lid().uefi(False)
    m.pci("0000:00:02.0", 0x030000, 0x8086, 0x591B, "i915", boot_vga=True)
    m.pci("0000:01:00.0", 0x030000, 0x10DE, 0x1BE0, "nouveau", boot_vga=False)
    m.gpu_card("card0", "0000:00:02.0").gpu_card("card1", "0000:01:00.0")
    m.connector("card0", "eDP-1", "0000:00:02.0", make_edid("", 1920, 1080, 382, 215, "CMN"), ["1920x1080"])
    m.connector("card1", "HDMI-A-1", "0000:01:00.0", None, [], connected=False)
    standard_nvme(m)
    m.pci("0000:02:00.0", 0x028000, 0x8086, 0x24FD, "iwlwifi")
    m.wifi_pci("wlp2s0", "0000:02:00.0", "iwlwifi")
    m.usb("1-14", 0x8087, 0x0A2B, "", [(0xE0, 0x01, 0x01), (0xE0, 0x01, 0x01)])
    m.bluetooth_usb("hci0", "1-14")
    m.input("SynPS/2 Synaptics TouchPad", "0011", 0x5, "mouse0", {"ID_INPUT_TOUCHPAD": "1", "ID_INPUT_MOUSE": "1"})
    m.input("AT Translated Set 2 keyboard", "0011", 0, "sysrq kbd leds", {"ID_INPUT_KEYBOARD": "1"})
    return m


def surface_pro7(root: Path) -> FakeMachine:
    m = FakeMachine(root)
    m.cpu("GenuineIntel", "Intel(R) Core(TM) i5-1035G4 CPU @ 1.10GHz", 4, 8, model_no=126)
    m.memory(8).dmi("Microsoft Corporation", "Surface Pro 7", 9, family="Surface").battery().uefi(True)
    m.acpi_device("MSHW0184")
    m.pci("0000:00:02.0", 0x030000, 0x8086, 0x8A5A, "i915", boot_vga=True)
    m.gpu_card("card0", "0000:00:02.0")
    m.connector("card0", "eDP-1", "0000:00:02.0", make_edid("", 2736, 1824, 260, 173, "LGD"), ["2736x1824"])
    m.pci("0000:01:00.0", 0x010802, 0x144D, 0xA80A, "nvme")
    m.disk("nvme0n1", 256 * GB, "KBG40ZPZ256G TOSHIBA MEMORY", "nvme",
           partitions=[
               {"start": 1 << 20, "size": 260 << 20, "fstype": "vfat", "parttype": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"},
               {"start": 261 << 20, "size": 16 << 20, "parttype": "e3c9e316-0b5c-4db8-817d-f92df00215ae"},
               {"start": 277 << 20, "size": 120 * GB, "fstype": "ntfs", "parttype": "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7", "label": "Windows"},
           ])
    m.pci("0000:00:14.3", 0x028000, 0x8086, 0x34F0, "iwlwifi")
    m.wifi_pci("wlp0s20f3", "0000:00:14.3", "iwlwifi")
    m.usb("1-10", 0x8087, 0x0026, "", [(0xE0, 0x01, 0x01)])
    m.bluetooth_usb("hci0", "1-10")
    m.input("IPTS Touch", "0019", 0x2, "mouse1", {"ID_INPUT_TOUCHSCREEN": "1"})
    m.input("IPTS Stylus", "0019", 0x2, "mouse2", {"ID_INPUT_TABLET": "1"})
    m.input("Microsoft Surface Type Cover Touchpad", "0003", 0x5, "mouse0", {"ID_INPUT_TOUCHPAD": "1"})
    m.input("Microsoft Surface Type Cover Keyboard", "0003", 0, "sysrq kbd leds", {"ID_INPUT_KEYBOARD": "1"})
    return m


def qemu_vm(root: Path) -> FakeMachine:
    m = FakeMachine(root)
    m.cpu("GenuineIntel", "QEMU Virtual CPU version 2.5+", 4, 4, flags="fpu sse sse2 hypervisor")
    m.memory(8).dmi("QEMU", "Standard PC (Q35 + ICH9, 2009)", 1).uefi(None)
    m.pci("0000:00:01.0", 0x030000, 0x1AF4, 0x1050, "virtio-pci", boot_vga=True)
    m.gpu_card("card0", "0000:00:01.0")
    m.connector("card0", "Virtual-1", "0000:00:01.0", None, ["1280x800", "1024x768"])
    m.pci("0000:00:04.0", 0x010000, 0x1AF4, 0x1042, "virtio-pci")
    m.disk("vda", 64 * GiB, "", "virtio")
    m.disk("sr0", 3 * GiB, "QEMU DVD-ROM", "sata")
    m.pci("0000:00:03.0", 0x020000, 0x1AF4, 0x1041, "virtio-pci")
    m.ethernet_virtio("enp0s3", "0000:00:03.0")
    return m


def rembrandt_laptop(root: Path) -> FakeMachine:
    m = FakeMachine(root)
    m.cpu("AuthenticAMD", "AMD Ryzen 7 6800U with Radeon Graphics", 8, 16, family=25, model_no=68)
    m.memory(16).dmi("LENOVO", "21CF", 10, version="ThinkPad T14s Gen 3").battery().lid().uefi(False)
    m.pci("0000:04:00.0", 0x030000, 0x1002, 0x1681, "amdgpu", boot_vga=True,
          extra={"mem_info_vram_total": str(512 * 2**20)})
    m.gpu_card("card0", "0000:04:00.0")
    m.connector("card0", "eDP-1", "0000:04:00.0", make_edid("", 1920, 1200, 301, 188, "AUO"), ["1920x1200"])
    standard_nvme(m, 512 * GB, "SAMSUNG MZVL2512HCJQ-00BL7")
    m.input("ELAN0678:00 04F3:3195 Touchpad", "0018", 0x5, "mouse0", {"ID_INPUT_TOUCHPAD": "1"})
    return m


def kepler_desktop(root: Path) -> FakeMachine:
    m = FakeMachine(root)
    m.cpu("GenuineIntel", "Intel(R) Core(TM) i7-4770K CPU @ 3.50GHz", 4, 8, model_no=60)
    m.memory(16).dmi("Gigabyte Technology Co., Ltd.", "Z87X-UD3H", 3)
    m.pci("0000:01:00.0", 0x030000, 0x10DE, 0x1004, "nouveau", boot_vga=True)
    m.gpu_card("card0", "0000:01:00.0")
    m.connector("card0", "DVI-D-1", "0000:01:00.0", make_edid("VG248", 1920, 1080, 531, 299, "ACI"), ["1920x1080"])
    m.disk("sda", 500 * GB, "Samsung SSD 850 EVO 500GB", "sata")
    return m


def arc_desktop(root: Path) -> FakeMachine:
    """Intel Arc A770 driving the monitors, Raptor Lake iGPU enabled but idle."""
    m = FakeMachine(root)
    m.cpu("GenuineIntel", "13th Gen Intel(R) Core(TM) i5-13600K", 14, 20, model_no=183)
    m.memory(32).dmi("ASRock", "Z790 Pro RS", 3).uefi(False)
    m.pci("0000:00:02.0", 0x030000, 0x8086, 0xA780, "i915", boot_vga=False)
    m.pci("0000:03:00.0", 0x030000, 0x8086, 0x56A0, "i915", boot_vga=True)
    m.gpu_card("card0", "0000:00:02.0").gpu_card("card1", "0000:03:00.0")
    m.connector("card1", "DP-2", "0000:03:00.0", make_edid("27GP850", 2560, 1440, 597, 336, "GSM"), ["2560x1440"])
    standard_nvme(m)
    return m


def amd_hybrid_laptop(root: Path) -> FakeMachine:
    """Phoenix APU with a Radeon RX 7600S (Navi 33) for offload."""
    m = FakeMachine(root)
    m.cpu("AuthenticAMD", "AMD Ryzen 9 7940HS w/ Radeon 780M Graphics", 8, 16, family=25, model_no=116)
    m.memory(16).dmi("ASUSTeK COMPUTER INC.", "ROG Zephyrus G14 GA402XV", 10).battery().lid().uefi(False)
    m.pci("0000:65:00.0", 0x030000, 0x1002, 0x15BF, "amdgpu", boot_vga=True, extra={"mem_info_vram_total": str(4 * GiB)})
    m.pci("0000:03:00.0", 0x038000, 0x1002, 0x7480, "amdgpu", extra={"mem_info_vram_total": str(8 * GiB)})
    m.gpu_card("card1", "0000:65:00.0").gpu_card("card0", "0000:03:00.0")
    m.connector("card1", "eDP-1", "0000:65:00.0", make_edid("", 2560, 1600, 302, 189, "TMX"), ["2560x1600"])
    standard_nvme(m)
    return m


def live_usb_machine(root: Path) -> FakeMachine:
    """An installer boot: the live USB stick must never be offered as a target."""
    m = rtx4080_desktop(root)
    m.disk("sdb", 32 * GB, "SanDisk Ultra", "usb", removable=True, pttype="dos",
           partitions=[{"start": 1 << 20, "size": 3 * GB, "fstype": "iso9660", "label": "NEXORA_202609",
                        "mountpoints": ["/run/archiso/bootmnt"]}])
    return m


MACHINES = {
    "rtx4080_desktop": rtx4080_desktop,
    "rx7900xtx_desktop": rx7900xtx_desktop,
    "hybrid_gtx1080_laptop": hybrid_gtx1080_laptop,
    "surface_pro7": surface_pro7,
    "qemu_vm": qemu_vm,
    "rembrandt_laptop": rembrandt_laptop,
    "kepler_desktop": kepler_desktop,
    "arc_desktop": arc_desktop,
    "amd_hybrid_laptop": amd_hybrid_laptop,
    "live_usb_machine": live_usb_machine,
}
