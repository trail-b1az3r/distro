#!/usr/bin/env bash
# Update ONLY Nexora's experimental updater implementation from the newest
# published ISO. The experimental updater (distrokit.experiments) ships in
# nexora-core; no reinstall, partitioning, or full system upgrade is performed.
set -Eeuo pipefail

REPO="trail-b1az3r/distro"
WORKDIR=""
MOUNTPOINT=""

cleanup() {
  if [[ -n "$MOUNTPOINT" ]] && mountpoint -q "$MOUNTPOINT"; then
    sudo umount "$MOUNTPOINT" || true
  fi
  [[ -z "$WORKDIR" ]] || rm -rf -- "$WORKDIR"
}
trap cleanup EXIT

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '\n==> %s\n' "$*"; }

[[ $EUID -ne 0 ]] || die "Run as your normal user; the script uses sudo when needed."
for cmd in curl jq pacman mount umount mountpoint find awk sed; do
  command -v "$cmd" >/dev/null || die "Missing required command: $cmd"
done
command -v unsquashfs >/dev/null || die "Install squashfs-tools first: sudo pacman -S squashfs-tools"
command -v sha256sum >/dev/null || die "sha256sum is required"
command -v vercmp >/dev/null || die "vercmp is required (provided by pacman)."

[[ -r /etc/os-release ]] || die "Cannot identify this system."
. /etc/os-release
[[ "${ID:-}" == "nexora" ]] || die "This script is specifically for an installed Nexora system."

installed_version="$(pacman -Q nexora-core 2>/dev/null | awk '{print $2}')"
[[ -n "$installed_version" ]] || die "nexora-core is not installed."

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/nexora-experimental-updater.XXXXXX")"
MOUNTPOINT="$WORKDIR/iso"
mkdir -p "$MOUNTPOINT"

log "Finding the latest published Nexora ISO"
curl --fail --location --silent --show-error \
  "https://api.github.com/repos/$REPO/releases/latest" -o "$WORKDIR/release.json"

tag="$(jq -r '.tag_name // empty' "$WORKDIR/release.json")"
[[ -n "$tag" ]] || die "GitHub did not return a latest release."

iso_name="$(jq -r '.assets[] | select(.name | test("\\.iso$"; "i")) | .name' "$WORKDIR/release.json" | head -n1)"
iso_url="$(jq -r '.assets[] | select(.name | test("\\.iso$"; "i")) | .browser_download_url' "$WORKDIR/release.json" | head -n1)"
[[ -n "$iso_name" && -n "$iso_url" ]] || die "Release $tag has no ISO asset."

checksum_name="$iso_name.sha256"
checksum_url="$(jq -r --arg n "$checksum_name" '.assets[] | select(.name == $n) | .browser_download_url' "$WORKDIR/release.json" | head -n1)"
[[ -n "$checksum_url" ]] || die "Release $tag does not publish $checksum_name."

log "Downloading ISO $iso_name"
curl --fail --location --show-error --retry 3 "$iso_url" -o "$WORKDIR/$iso_name"
curl --fail --location --show-error "$checksum_url" -o "$WORKDIR/$checksum_name"

expected="$(awk -v n="$iso_name" '$2 == n || $2 == "*" n {print $1; exit} /^[0-9a-fA-F]+$/ && length($1) == 64 {print $1; exit}' "$WORKDIR/$checksum_name")"
[[ "$expected" =~ ^[[:xdigit:]]{64}$ ]] || die "Could not read a SHA-256 checksum for $iso_name."
printf '%s  %s\n' "$expected" "$WORKDIR/$iso_name" | sha256sum --check --status ||
  die "ISO checksum verification failed; nothing has been installed."

log "Mounting the verified ISO read-only"
sudo mount -o loop,ro "$WORKDIR/$iso_name" "$MOUNTPOINT"

mapfile -t squashfs_files < <(find "$MOUNTPOINT" -type f \( -name 'airootfs.sfs' -o -name '*.squashfs' \))
(("${#squashfs_files[@]}" > 0)) || die "No live-root SquashFS image was found inside the ISO."

package="$WORKDIR/nexora-core.pkg.tar.zst"
found=0
for squashfs in "${squashfs_files[@]}"; do
  # The ISO's offline package repository is embedded in the live root at
  # /var/cache/nexora/repo. Stream only nexora-core out; do not unpack the
  # multi-gigabyte live filesystem onto the installed machine.
  internal_path="$(unsquashfs -ll "$squashfs" 2>/dev/null |
    sed -nE 's#^.*squashfs-root/(var/cache/nexora/repo/nexora-core-[^/]+\.pkg\.tar\.(zst|xz|gz))$#\1#p' |
    head -n1)"
  if [[ -n "$internal_path" ]]; then
    unsquashfs -cat "$squashfs" "$internal_path" > "$package"
    found=1
    break
  fi
done
(( found == 1 )) || die "The ISO does not carry nexora-core in /var/cache/nexora/repo. Use a release built with the offline Nexora repository."

package_name="$(pacman -Qp "$package" | awk '{print $1}')"
package_version="$(pacman -Qp "$package" | awk '{print $2}')"
[[ "$package_name" == "nexora-core" ]] || die "Extracted package is $package_name, not nexora-core."
[[ -n "$package_version" ]] || die "Could not read the package version."

if (( $(vercmp "$package_version" "$installed_version") <= 0 )); then
  printf '\nInstalled experimental updater core: %s\nISO experimental updater core:       %s\n' "$installed_version" "$package_version"
  die "The ISO does not contain a newer nexora-core package. No changes were made."
fi

printf '\nLatest ISO release: %s\n' "$tag"
printf 'Installed nexora-core: %s\n' "$installed_version"
printf 'ISO nexora-core:       %s\n' "$package_version"
printf '\nThis updates ONLY nexora-core, which contains the `nexora experiments` experimental updater logic.\n'
printf 'It does not reinstall Nexora, update other packages, change repositories, or touch user files.\n'
read -r -p "Install the newer experimental updater now? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || { log "Cancelled; nothing was installed."; exit 0; }

log "Installing the newer experimental updater core"
sudo pacman -U -- "$package"

log "Experimental updater updated to nexora-core $package_version"
printf 'You can now run: sudo nexora experiments status\n'
