#!/usr/bin/env bash
# Install the updater shipped in the newest Nexora ISO without reinstalling.
# The ISO is used only as a source of the signed/release-built Nexora packages;
# the installed system and user data are not reformatted or reinstalled.
set -Eeuo pipefail

REPO="trail-b1az3r/distro"
WORKDIR=""
MOUNTPOINT=""
cleanup() {
  if [[ -n "${MOUNTPOINT}" ]] && mountpoint -q "${MOUNTPOINT}"; then
    sudo umount "${MOUNTPOINT}" || true
  fi
  [[ -z "${WORKDIR}" ]] || rm -rf -- "${WORKDIR}"
}
trap cleanup EXIT

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '\n==> %s\n' "$*"; }

[[ $EUID -ne 0 ]] || die "Run this script as your normal user, not with sudo."
for cmd in curl jq pacman mount umount mountpoint find; do
  command -v "$cmd" >/dev/null || die "Required command missing: $cmd"
done
command -v unsquashfs >/dev/null || die "Install squashfs-tools first: sudo pacman -S squashfs-tools"
command -v sha256sum >/dev/null || die "sha256sum is required"

[[ -r /etc/os-release ]] || die "Cannot identify the installed operating system."
. /etc/os-release
[[ "${ID:-}" == "nexora" || " ${ID_LIKE:-} " == *" arch "* || " ${ID_LIKE:-} " == *" endeavouros "* ]] ||
  die "This updater installer is intended for Nexora or an Arch/EndeavourOS-based Nexora install."

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/nexora-updater.XXXXXX")"
MOUNTPOINT="$WORKDIR/iso"
mkdir -p "$MOUNTPOINT"

log "Checking the latest Nexora ISO release"
release_json="$WORKDIR/release.json"
curl --fail --location --silent --show-error \
  "https://api.github.com/repos/$REPO/releases/latest" -o "$release_json"
tag="$(jq -r '.tag_name // empty' "$release_json")"
[[ -n "$tag" ]] || die "GitHub did not return a latest release."

iso_url="$(jq -r '.assets[] | select(.name | test("\\.iso$"; "i")) | .browser_download_url' "$release_json" | head -n1)"
iso_name="$(jq -r '.assets[] | select(.name | test("\\.iso$"; "i")) | .name' "$release_json" | head -n1)"
[[ -n "$iso_url" && -n "$iso_name" ]] || die "Release $tag has no ISO asset."

# Prefer the checksum asset whose filename matches the ISO. Never install from
# an incomplete download; if the release has no checksum, fail closed.
checksum_url="$(jq -r --arg n "$iso_name" '.assets[] | select(.name == ($n + ".sha256") or .name == ($n + ".sha256sum")) | .browser_download_url' "$release_json" | head -n1)"
[[ -n "$checksum_url" ]] || checksum_url="$(jq -r '.assets[] | select(.name | test("sha256"; "i")) | .browser_download_url' "$release_json" | head -n1)"
[[ -n "$checksum_url" ]] || die "Release $tag does not publish a SHA-256 checksum."

iso="$WORKDIR/$iso_name"
log "Downloading $iso_name from $tag"
curl --fail --location --show-error --retry 3 "$iso_url" -o "$iso"
curl --fail --location --show-error "$checksum_url" -o "$WORKDIR/checksums.txt"

# Support both '<hash>  filename' and a checksum file containing just a hash.
expected="$(awk -v n="$iso_name" '$2 == n || $2 == "*" n {print $1; exit} /^[[:xdigit:]]{64}$/ {print; exit}' "$WORKDIR/checksums.txt")"
[[ "$expected" =~ ^[[:xdigit:]]{64}$ ]] || die "Could not find the ISO's SHA-256 in the published checksum."
printf '%s  %s\n' "$expected" "$iso" | sha256sum --check --status ||
  die "ISO checksum verification failed; no packages were installed."

log "Mounting the verified ISO and locating its offline Nexora repository"
sudo mount -o loop,ro "$iso" "$MOUNTPOINT"
pkgdir="$WORKDIR/packages"
mkdir -p "$pkgdir"

# Releases built with --offline minimal/full carry the distribution repository
# either directly on the ISO or inside the live root filesystem.
find "$MOUNTPOINT" -type f \( -name 'nexora-core-*.pkg.tar.*' -o -name 'nexora-welcome-*.pkg.tar.*' \) \
  -exec cp -n -- '{}' "$pkgdir/" \;

while IFS= read -r squashfs; do
  [[ -n "$squashfs" ]] || continue
  sudo unsquashfs -f -d "$WORKDIR/squashfs" "$squashfs" >/dev/null
  find "$WORKDIR/squashfs" -type f \( -name 'nexora-core-*.pkg.tar.*' -o -name 'nexora-welcome-*.pkg.tar.*' \) \
    -exec cp -n -- '{}' "$pkgdir/" \;
  rm -rf -- "$WORKDIR/squashfs"
done < <(find "$MOUNTPOINT" -type f -name '*.sfs' -o -name '*.squashfs')

core_pkg="$(find "$pkgdir" -maxdepth 1 -type f -name 'nexora-core-*.pkg.tar.*' -print -quit)"
[[ -n "$core_pkg" ]] || die "The ISO does not contain nexora-core. Build/publish with the offline Nexora repository included."

packages=("$core_pkg")
welcome_pkg="$(find "$pkgdir" -maxdepth 1 -type f -name 'nexora-welcome-*.pkg.tar.*' -print -quit)"
[[ -z "$welcome_pkg" ]] || packages+=("$welcome_pkg")

printf '\nThe verified ISO contains these updater packages:\n'
for package in "${packages[@]}"; do
  pacman -Qp "$package"
done
printf '\nThis will update only the Nexora updater/core package(s). It will not reinstall Nexora, repartition disks, or modify /home.\n'
read -r -p "Install these packages now? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || { log "Cancelled; no packages were installed."; exit 0; }

log "Installing the updater packages from the ISO"
sudo pacman -U --needed -- "${packages[@]}"
log "Updater package installation finished. Restart the updater app if it was open."
