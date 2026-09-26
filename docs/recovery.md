# Recovery

Every command here explains what it is going to change and asks before doing
it. Nothing destructive runs silently.

## From the running system

| Command | What it does |
|---|---|
| `nexora doctor` | diagnose; prints a fix for each problem |
| `sudo nexora repair` | fix what the doctor found (packages, boot, drivers) |
| `sudo nexora repair packages` | stale lock, keyrings, full update, reinstall packages with missing files, dependency check |
| `sudo nexora repair boot` | reinstall the boot loader, rebuild every initramfs, regenerate boot entries |
| `sudo nexora repair-gpu [--safe]` | re-detect GPUs and reinstall drivers (`--safe`: open-source drivers) |
| `nexora reset-desktop` | restore the desktop configuration; changed files and `~/.config/hypr/custom/` are backed up to `~/.local/state/nexora/desktop-backups/<date>/` |

## Snapshots (Btrfs)

With *Snapshots* on (default on Btrfs), Snapper keeps hourly/daily/weekly
snapshots of `/` (5/7/2/1) and takes one before and after every pacman
transaction (snap-pac). Your home (`@home`) is not rolled back with the system.

```bash
sudo snapper -c root list
sudo snapper -c root create -d "before experimenting"
sudo snapper -c root undochange 42..0 /etc/somefile   # restore one file
```

To roll the whole system back:

* **GRUB:** the boot menu has *Snapshots* entries (grub-btrfs). Boot the
  snapshot, check that it works, then make it permanent with
  `sudo snapper rollback` and reboot.
* **systemd-boot:** boot the live ISO, run `sudo nexora rescue --shell` and,
  inside, `snapper --no-dbus -c root rollback <number>`; leave with `exit` and reboot.

The Welcome wizard's *Backup* page shows the snapshot state and can take one.
Snapshots are not backups: keep copies of important files on another disk.

## From the live ISO

When the system does not boot at all, start the ISO and run:

```bash
sudo nexora rescue
```

It lists installed systems, unlocks an encrypted one (asking for the
passphrase), mounts it with its subvolumes, offers the package and boot
repairs from outside, and unmounts it again. For manual work,
`sudo nexora rescue --shell` opens a shell inside the installed system
(`arch-chroot`) instead; leaving the shell unmounts it.
