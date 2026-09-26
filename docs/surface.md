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

Older models with Marvell Wi-Fi also get `linux-firmware-marvell`.
