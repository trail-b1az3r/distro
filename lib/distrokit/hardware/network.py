"""Wi-Fi, Ethernet and Bluetooth adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import ids
from .pci import PciDevice, UsbDevice
from .sysroot import SysRoot

# Wi-Fi chips that need firmware or drivers outside linux-firmware's defaults.
# (vendor, bus) -> extra package list name / package
_BROADCOM_WL_IDS = {0x4311, 0x4312, 0x4313, 0x4315, 0x4328, 0x4329, 0x432A, 0x432B, 0x432C,
                    0x432D, 0x4353, 0x4357, 0x4358, 0x4359, 0x4365, 0x43A0, 0x43B1}


@dataclass
class NetAdapter:
    interface: str
    kind: str  # wifi | ethernet
    bus: str  # pci | usb | sdio | platform | virtual
    vendor: str
    name: str
    driver: str
    device_id: str
    extra_packages: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BluetoothAdapter:
    name: str
    vendor: str
    bus: str
    device_id: str
    present_as_hci: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _describe_device(sysroot: SysRoot, devpath: str, pci: dict[str, PciDevice]) -> tuple[str, str, str, str]:
    """(bus, vendor, name, id) for the device behind a /sys/class/* entry."""
    real = sysroot.realpath(devpath)
    slot = real.rsplit("/", 1)[-1]
    if slot in pci:
        dev = pci[slot]
        return "pci", dev.vendor, ids.marketing_name(dev.name) or dev.name, f"{dev.vendor_id:04x}:{dev.device_id:04x}"
    # USB interface directory (e.g. 1-4:1.0): the device is its parent.
    parent = real.rsplit("/", 1)[0]
    vid = sysroot.read_int(f"{parent}/idVendor", None, 16)
    pid = sysroot.read_int(f"{parent}/idProduct", None, 16)
    if vid is not None and pid is not None:
        db = ids.usb_ids(sysroot)
        name = db.device(vid, pid) or sysroot.read(f"{parent}/product")
        return "usb", ids.short_vendor(vid, db), name, f"{vid:04x}:{pid:04x}"
    if "/mmc" in real:
        return "sdio", "", "", ""
    if "/virtual/" in real or not real:
        return "virtual", "", "", ""
    return "platform", "", "", ""


def detect_network(sysroot: SysRoot, pci_devices: list[PciDevice]) -> list[NetAdapter]:
    pci = {d.slot: d for d in pci_devices}
    adapters = []
    for iface in sysroot.listdir("/sys/class/net"):
        base = f"/sys/class/net/{iface}"
        if iface == "lo" or not sysroot.exists(f"{base}/device"):
            continue
        wifi = sysroot.is_dir(f"{base}/wireless") or sysroot.exists(f"{base}/phy80211")
        if not wifi and sysroot.read(f"{base}/type") != "1":
            continue
        bus, vendor, name, dev_id = _describe_device(sysroot, f"{base}/device", pci)
        if bus == "virtual":
            continue
        driver = sysroot.readlink_name(f"{base}/device/driver")
        extra: list[str] = []
        if wifi and vendor == "Broadcom" and bus == "pci":
            try:
                if int(dev_id.split(":")[1], 16) in _BROADCOM_WL_IDS and driver in ("", "wl", "bcma-pci-bridge"):
                    extra.append("broadcom-wl-dkms")
            except (IndexError, ValueError):
                pass
        adapters.append(
            NetAdapter(
                interface=iface,
                kind="wifi" if wifi else "ethernet",
                bus=bus,
                vendor=vendor,
                name=name or driver or iface,
                driver=driver,
                device_id=dev_id,
                extra_packages=extra,
            )
        )
    # Wi-Fi hardware whose driver is not loaded has no interface; report it
    # from PCI so the summary still shows it.
    known = {a.device_id for a in adapters}
    for dev in pci_devices:
        if dev.base_class == 0x02 and dev.sub_class == 0x80 and f"{dev.vendor_id:04x}:{dev.device_id:04x}" not in known:
            adapters.append(
                NetAdapter(
                    interface="",
                    kind="wifi",
                    bus="pci",
                    vendor=dev.vendor,
                    name=ids.marketing_name(dev.name) or dev.name,
                    driver=dev.driver,
                    device_id=f"{dev.vendor_id:04x}:{dev.device_id:04x}",
                    extra_packages=["broadcom-wl-dkms"] if dev.vendor_id == 0x14E4 and dev.device_id in _BROADCOM_WL_IDS else [],
                )
            )
    return adapters


def detect_bluetooth(sysroot: SysRoot, pci_devices: list[PciDevice], usb_devices: list[UsbDevice]) -> list[BluetoothAdapter]:
    pci = {d.slot: d for d in pci_devices}
    adapters = []
    seen = set()
    for hci in sysroot.listdir("/sys/class/bluetooth"):
        if not hci.startswith("hci") or ":" in hci:
            continue
        bus, vendor, name, dev_id = _describe_device(sysroot, f"/sys/class/bluetooth/{hci}/device", pci)
        seen.add(dev_id)
        adapters.append(BluetoothAdapter(name=name or hci, vendor=vendor, bus=bus, device_id=dev_id, present_as_hci=True))
    # Controllers without a loaded driver: USB wireless controller class e0/01/01.
    for dev in usb_devices:
        dev_id = f"{dev.vendor_id:04x}:{dev.product_id:04x}"
        if dev_id in seen:
            continue
        if any(c == (0xE0, 0x01, 0x01) for c in dev.interface_classes):
            adapters.append(
                BluetoothAdapter(
                    name=dev.name or "Bluetooth controller",
                    vendor=ids.short_vendor(dev.vendor_id, ids.usb_ids(sysroot)),
                    bus="usb",
                    device_id=dev_id,
                    present_as_hci=False,
                )
            )
    return adapters
