"""PCI and USB device enumeration from sysfs."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import ids
from .sysroot import SysRoot

PCI_BASE = "/sys/bus/pci/devices"
USB_BASE = "/sys/bus/usb/devices"


@dataclass
class PciDevice:
    slot: str
    class_code: int
    vendor_id: int
    device_id: int
    subsys_vendor_id: int
    subsys_device_id: int
    driver: str
    vendor: str
    name: str
    subsystem_name: str
    boot_vga: bool

    @property
    def base_class(self) -> int:
        return self.class_code >> 16

    @property
    def sub_class(self) -> int:
        return (self.class_code >> 8) & 0xFF

    @property
    def is_display(self) -> bool:
        return self.base_class == 0x03

    @property
    def is_network(self) -> bool:
        return self.base_class == 0x02

    @property
    def sysfs(self) -> str:
        return f"{PCI_BASE}/{self.slot}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["pci_id"] = f"{self.vendor_id:04x}:{self.device_id:04x}"
        return d


def list_pci(sysroot: SysRoot) -> list[PciDevice]:
    db = ids.pci_ids(sysroot)
    devices = []
    for slot in sysroot.listdir(PCI_BASE):
        base = f"{PCI_BASE}/{slot}"
        vid = sysroot.read_int(f"{base}/vendor", 0, 16) or 0
        did = sysroot.read_int(f"{base}/device", 0, 16) or 0
        cls = sysroot.read_int(f"{base}/class", 0, 16) or 0
        svid = sysroot.read_int(f"{base}/subsystem_vendor", 0, 16) or 0
        sdid = sysroot.read_int(f"{base}/subsystem_device", 0, 16) or 0
        devices.append(
            PciDevice(
                slot=slot,
                class_code=cls,
                vendor_id=vid,
                device_id=did,
                subsys_vendor_id=svid,
                subsys_device_id=sdid,
                driver=sysroot.readlink_name(f"{base}/driver"),
                vendor=ids.short_vendor(vid, db),
                name=db.device(vid, did),
                subsystem_name=db.subsystem(vid, did, svid, sdid),
                boot_vga=sysroot.read(f"{base}/boot_vga") == "1",
            )
        )
    return devices


@dataclass
class UsbDevice:
    path: str
    vendor_id: int
    product_id: int
    manufacturer: str
    product: str
    name: str
    interface_classes: list[tuple[int, int, int]]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["usb_id"] = f"{self.vendor_id:04x}:{self.product_id:04x}"
        return d


def list_usb(sysroot: SysRoot) -> list[UsbDevice]:
    db = ids.usb_ids(sysroot)
    entries = sysroot.listdir(USB_BASE)
    devices = []
    for entry in entries:
        if ":" in entry or entry.startswith("usb"):
            continue  # interfaces and root hubs
        base = f"{USB_BASE}/{entry}"
        vid = sysroot.read_int(f"{base}/idVendor", None, 16)
        pid = sysroot.read_int(f"{base}/idProduct", None, 16)
        if vid is None or pid is None:
            continue
        ifaces = []
        for iface in entries:
            if iface.startswith(entry + ":"):
                ib = f"{USB_BASE}/{iface}"
                ifaces.append(
                    (
                        sysroot.read_int(f"{ib}/bInterfaceClass", 0, 16) or 0,
                        sysroot.read_int(f"{ib}/bInterfaceSubClass", 0, 16) or 0,
                        sysroot.read_int(f"{ib}/bInterfaceProtocol", 0, 16) or 0,
                    )
                )
        product = sysroot.read(f"{base}/product")
        devices.append(
            UsbDevice(
                path=entry,
                vendor_id=vid,
                product_id=pid,
                manufacturer=sysroot.read(f"{base}/manufacturer"),
                product=product,
                name=db.device(vid, pid) or product,
                interface_classes=ifaces,
            )
        )
    return devices
