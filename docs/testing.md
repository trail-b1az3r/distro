# Testing

| Suite | Runs | Needs |
|---|---|---|
| `tests/unit` | hardware detection on fixture machines, GPU plans, boot configuration, installer plans and written files, disk plans, AI (catalogue, recommendations, backends, downloads, registry, tasks, tool installs), desktop deploy and keybind collisions, CLI, doctor, repair, updater, pacman configs, packaging (PKGBUILDs, staging, dependency resolution, reproducible tarball), ISO assembly, the QEMU harness | Python 3.11+, Pillow, NumPy (any Linux) |
| `tests/gui` | the installer (every page, validation, a full demo installation), Welcome, updater, AI launcher and the SDDM login theme, offscreen with QML warnings treated as failures | PySide6 |
| `tests/integration` | real partitioning, formatting, mounting and rollback on loop devices | root, `losetup`, `sfdisk`, ext4 |
| `tests/qemu` | installs the ISO in QEMU/KVM and checks the booted result | QEMU, OVMF, KVM, an ISO |

```bash
make test-unit
make test-gui
sudo make test-integration
make lint                        # ruff, shellcheck (incl. rendered templates), PKGBUILD syntax, completions
tests/qemu/run.sh --list
tests/qemu/run.sh                # newest ISO in dist/, all scenarios
```

## Fixture machines

`tests/hwfixtures.py` builds fake sysfs/procfs/udev trees: an RTX 4080
desktop, an RX 7900 XTX desktop, the brief's hybrid GTX 1080 laptop, a
Surface Pro 7 (with Windows installed), a QEMU VM, a Rembrandt (AMD APU)
laptop, a Kepler desktop, an Intel Arc desktop, an AMD+NVIDIA hybrid laptop
and a machine booted from the live USB stick. Add one for new hardware
classes and assert what detection and the GPU plan should produce.

## QEMU scenarios

`tests/qemu/scenarios/*.json`: firmware (UEFI via OVMF or BIOS), disk bus
(virtio, NVMe, SATA), size, memory and an installer configuration. The
harness:

1. extracts the kernel and initramfs from the ISO, boots them with
   `console=ttyS0` and `nexora.autoinstall=fw_cfg`, passing the configuration
   through QEMU's fw_cfg, and waits for `AUTOINSTALL: RESULT 0`;
2. boots the installed disk, answers the LUKS prompt, logs in as root on the
   serial console and runs checks: os-release, hostname, file system,
   encryption, NetworkManager, SDDM, boot entries (systemd-boot or GRUB +
   theme), package integrity, the user's desktop files and their owner, the
   Plymouth and SDDM themes, the install record, `nexora-gpu status`,
   `nexora doctor`, and whether the system reached `running`.

Logs (`install.log`, `boot.log`) and `result.json` land in `build/qemu/<scenario>/`.
Add a scenario by adding a JSON file; `test_qemu_harness.py` validates it
against the installer's rules.

## Continuous integration

`.github/workflows/ci.yml` runs lint, unit, GUI and integration tests on
Ubuntu, and on Arch Linux builds the distribution's packages (running their
tests), installs them, exercises the installed CLI and resolves the AUR plan.
`iso.yml` builds the ISO in a container and runs the QEMU scenarios; it runs
weekly and for every release.
