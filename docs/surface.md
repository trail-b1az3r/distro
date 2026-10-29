# Microsoft Surface

Surface devices (Pro, Laptop, Book, Go, Studio) are detected from the
firmware's product name and Surface ACPI devices. The
[linux-surface](https://github.com/linux-surface/linux-surface) project's
kernel adds touchscreen and pen support (through `iptsd`), cameras on some
models, better battery life and fixes for the Type Cover.

* **Recommended, never forced:** on detected Surface hardware the installer
  pre-selects the Surface kernel; you can switch it off. On other hardware it
  is off and can be switched on (for example if detection missed a model).
* It is installed **in addition** to the regular kernel, which stays in the
  boot menu as a fallback. The Surface kernel is the default entry.
* The package repository is linux-surface's own; its signing key ships with
  the distribution ([`hardware/surface/linux-surface.asc`](../hardware/surface/linux-surface.asc))
  and is checked against the fingerprint in `surface.toml` before it is
  trusted.
* Installing it needs the internet (it is not on the ISO).

```bash
nexora surface status              # detected model, kernel state
sudo nexora surface enable         # repository, key, kernel, iptsd, libwacom-surface
sudo nexora surface enable --secure-boot   # also the MOK key package (for shim setups)
sudo nexora surface disable        # back to the regular kernel (the repository is kept)
```

## Starting the ISO

Surface firmware only starts unsigned systems with Secure Boot off:

1. Shut the Surface down. Hold **Volume Up** and press **Power**; let go of
   Volume Up when the Surface logo appears. This is *Surface UEFI*.
2. **Security** → **Secure Boot** → **Change configuration** → **None**
   (on some firmware versions: Secure Boot **Disabled**). On the Surface Pro 5
   and later the boot screen shows a red bar from now on: that is expected.
3. **Boot configuration**: make sure **Enable Boot from USB devices** is on.
   Exit and restart.
4. With the stick in (a USB-A stick, or USB-C on later models), shut down,
   hold **Volume Down** and press **Power**; let go when the menu appears.

If the Surface starts Windows instead, Secure Boot is still on or the stick
was not written as described in [installation.md](installation.md#1-write-the-iso-to-a-usb-stick).
The live system runs the regular kernel: the Type Cover, its touchpad, the
display, Wi-Fi and Bluetooth work; the touchscreen and pen need the Surface
kernel, so they work after installing.

## Surface Pro 5 (2017)

The fifth-generation Surface Pro reports itself as plain "Surface Pro"; it is
recognised by its firmware SKU and shown as *Surface Pro (5th Gen)*. Notes:

* **Wi-Fi** is a Marvell 88W8897 (`mwifiex`). Its firmware,
  `linux-firmware-marvell`, is not part of Arch's `linux-firmware` any more:
  it is on the live ISO, and the installer adds it whenever a Marvell card is
  found, with or without the Surface kernel. Wi-Fi power saving is off for
  these cards (`/usr/lib/NetworkManager/conf.d/50-nexora-mwifiex.conf`): with
  it on, they drop the connection. The card also does not come back from
  suspend, so the driver is unloaded before sleeping and loaded again on
  waking (`/usr/lib/systemd/system-sleep/nexora-mwifiex`).
* **Saved Wi-Fi passwords**: members of `wheel` manage networks without a
  password prompt (`/usr/share/polkit-1/rules.d/50-nexora-networkmanager.rules`),
  which NetworkManager needs to keep the passwords the desktop gives it. On a
  system installed before this, connect once with `nmtui` to save a network.
* **Display**: 2736 × 1824 at 12.3"; the installer suggests a scale of 2
  (a 1368 × 912 desktop, like Windows' 200 %). Change it in
  `~/.config/hypr/custom/general.lua` (1.6 or 1.75 fit more on screen).
* **Touchscreen and pen** (IPTS) need the Surface kernel, which the installer
  pre-selects.
* **Secure Boot** can be turned back on after installing with your own keys:
  the installer's *Secure Boot* option sets that up with `sbctl`.

## Other models

Older models with Marvell Wi-Fi (Surface Pro 3–6, Surface Book and Laptop 1–2,
Surface Studio) also get `linux-firmware-marvell` and the power-saving fix.
