# Microsoft Surface

Surface devices (Pro, Laptop, Book, Go, Studio) are detected from the
firmware's product name and Surface ACPI devices. Nexora's Surface support is
built entirely from its own fork of linux-surface,
[trail-b1az3r/linux-surface](https://github.com/trail-b1az3r/linux-surface). The Surface
kernel adds touchscreen and pen support (through `iptsd`), cameras on some
models, better battery life and fixes for the Type Cover.

* **Recommended, never forced:** on detected Surface hardware the installer
  pre-selects the Surface kernel; you can switch it off. On other hardware it
  is off and can be switched on (for example if detection missed a model).
* It is installed **in addition** to the regular kernel, which stays in the
  boot menu as a fallback. The Surface kernel is the default entry.
* The packages come from Nexora's **`[nexora-surface]`** repository, not linux-surface's server. The
  [Surface packages workflow](../.github/workflows/surface.yml) builds them (`scripts/build-surface.sh`):
  * `linux-surface` and `linux-surface-headers`, from the fork's `pkg/arch/kernel` at the commit pinned in
    [`surface.toml`](../hardware/surface/surface.toml) (`[fork] commit`);
  * `surface-contrib`, from the fork's `contrib/`, at the same commit;
  * `iptsd`, from [linux-surface/iptsd](https://github.com/linux-surface/iptsd) at a pinned tag;
  * `libwacom-surface`, from the AUR.

  It runs when the pins change, every week, and by hand. Like the distribution's own repository, it is served over
  HTTPS from GitHub releases, unsigned. Enabling Surface support takes linux-surface's `[linux-surface]` repository
  out of `pacman.conf`, and these packages replace its packages (a Nexora build always has the higher pkgrel).
* **Secure Boot:** the kernel is not signed with linux-surface's MOK key. Use the installer's Secure Boot option
  (sbctl, with systemd-boot), which signs every installed kernel on the machine.
* To take a newer fork, set `[fork] commit` in `surface.toml`. The push to main rebuilds the repository.
* Installing it needs the internet (it is not on the ISO).

```bash
nexora surface status              # detected model, kernel state
sudo nexora surface enable         # repository, key, kernel, iptsd, libwacom-surface
sudo nexora surface disable        # back to the regular kernel (the repository is kept)
```

## Extras from the linux-surface fork

What the fork adds to linux-surface (`contrib/`) is packaged as `surface-contrib` and installed with the rest of
Surface support:

* **Cameras on the Surface Pro 4, 5 and 6 and the Surface Book 1 and 2** (Intel IPU3): `surface-camd`, a userspace
  driver for the front, rear and **IR** cameras. It shows them to every app as ordinary webcams: "Surface Front
  Camera" on `/dev/video50`, "Surface Rear Camera" on `/dev/video51` and "Surface IR Camera" on `/dev/video52`
  (usable with Howdy for face unlock). On those models it is turned on when the package is installed, along with
  `v4l2loopback-dkms`. On other models nothing changes.
* **Speaker EQ for the Surface Pro 5 and 7+**: a PipeWire filter that corrects the small speakers. Run it as your
  user.
* **Modern suspend for the Surface Pro 5**: deep sleep where the firmware has it, then s2idle and
  suspend-then-hibernate, plus a Wi-Fi hook. You turn it on yourself because it changes how the lid behaves.
* Example thermald configurations, in `/usr/share/surface-contrib/thermald/`.

```bash
surface-contrib cameras status            # configuration, services, devices
sudo surface-contrib cameras on|off       # turn the cameras on or off
surface-contrib cameras doctor            # check every camera layer (report: logs for a bug report)
surface-contrib speaker-eq                # speaker EQ (Pro 5 / 7+), as your user
sudo surface-contrib suspend --install    # Pro 5 suspend (--test checks deep idle, --uninstall)
```

## touchD controls

When Surface support is enabled, Nexora installs `touchd-dkms` alongside
`iptsd` and `libwacom-surface`. It provides the IPTS DKMS fallback, the
`touchdctl` utility and a Surface Pro 5 profile. The package checks each
installed kernel and skips DKMS when IPTS is already built in or supplied by
the kernel, so it does not stack a second driver over the in-tree one.

On a Surface Pro 5, package installation automatically enables the tuned
contact/palm/pen profile if no administrator profile already exists. On an
existing install, you can apply it manually and restart IPTSD:

```bash
sudo touchdctl profile surface-pro-5
sudo touchdctl restart
touchdctl status
```

Other controls:

- `sudo touchdctl calibrate` runs the upstream IPTS calibration tool; put the
  measured values in `/etc/iptsd.d/90-calibration.conf`.
- `touchdctl pen-buttons` prints the Hyprland Plus pen-button mapping guide.
- `touchdctl handwriting` opens an installed handwriting overlay. The
  optional `handwrite-input` frontend uses local TrOCR recognition; its first
  run downloads model weights. It is not installed by default.
- Hyprland Plus 0.57.0.p2 and later support app-scoped pen pressure curves and optional
  speed/tilt modulation. These apply to Krita, GIMP, Inkscape, MyPaint and
  Blender, not general desktop input. For example:

```ini
input {
    tablettool {
        pressure_curve = soft
        pressure_speed = 0.15
        pressure_tilt = 0.10
    }
}
```

The DKMS module is a fallback, not a promise that unsupported kernels can be
patched at runtime. A kernel without the IPTS prerequisites may reject the
build; in that case the existing input stack is left alone and DKMS reports
the failure.

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
  suspend, so the recovery hook stops NetworkManager and unloads the driver
  before sleeping, then reloads it, waits for udev, and restores NetworkManager
  after waking (`/usr/lib/systemd/system-sleep/nexora-mwifiex`).
* **Saved Wi-Fi passwords**: members of `wheel` manage networks without a
  password prompt (`/usr/share/polkit-1/rules.d/50-nexora-networkmanager.rules`),
  which NetworkManager needs to keep the passwords the desktop gives it. On a
  system installed before this, connect once with `nmtui` to save a network.
* **Display**: 2736 × 1824 at 12.3"; the installer suggests a scale of 2
  (a 1368 × 912 desktop, like Windows' 200 %). Change it in
  `~/.config/hypr/custom/general.lua` (1.6 or 1.75 fit more on screen).
* **Touchscreen and pen** (IPTS) use the Surface kernel and `iptsd`. Nexora also
  installs `touchd-dkms`: the upstream IPTS DKMS fallback, `touchdctl`, and
  the Surface Pro 5 tuning profile. If the selected kernel already contains
  IPTS, the package detects that and skips the duplicate DKMS module.
* **Secure Boot** can be turned back on after installing with your own keys:
  the installer's *Secure Boot* option sets that up with `sbctl`.

## Other models

Older models with Marvell Wi-Fi (Surface Pro 3–6, Surface Book and Laptop 1–2,
Surface Studio) also get `linux-firmware-marvell` and the power-saving fix.
