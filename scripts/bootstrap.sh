#!/usr/bin/env bash
# Prepare an ISO build host: Arch Linux, EndeavourOS, or the archlinux
# container image (build.sh --container runs this inside the container).
#
#   scripts/bootstrap.sh [--container] [--builder] [--with-qemu]
#
#   --container   running in a throwaway container: also creates the unprivileged
#                 "builder" user makepkg runs as, with password-less pacman
#   --builder     create that user on this host too
#   --with-qemu   also install QEMU and OVMF for tests/qemu/run.sh
#
# What it does: enables [multilib], installs the build tools, and makes the
# [endeavouros] repository trusted using EndeavourOS's keyring and mirror list
# at the commits pinned (with SHA-256 sums) in iso/sources.conf.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
# shellcheck source=SCRIPTDIR/../iso/sources.conf
source iso/sources.conf

container=0 builder=0 qemu=0
for arg in "$@"; do
    case "$arg" in
        --container) container=1 builder=1 ;;
        --builder) builder=1 ;;
        --with-qemu) qemu=1 ;;
        -h | --help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option $arg" >&2; exit 2 ;;
    esac
done

((EUID == 0)) || exec sudo "$0" "$@"
[[ -e /etc/arch-release ]] || { echo "bootstrap.sh needs an Arch-based system (or use ./build.sh --container)" >&2; exit 1; }

step() { printf '\033[1;35m==>\033[0m %s\n' "$*"; }

fetch() { # url sha256 destination
    local tmp
    tmp="$(mktemp)"
    curl -fsSL --retry 3 -o "$tmp" "$1"
    if ! echo "$2  $tmp" | sha256sum -c --quiet -; then
        rm -f "$tmp"
        echo "checksum mismatch for $1 (see iso/sources.conf)" >&2
        exit 1
    fi
    install -Dm644 "$tmp" "$3"
    rm -f "$tmp"
}

step "Enabling [multilib]"
if ! grep -q '^\[multilib\]' /etc/pacman.conf; then
    sed -i '/^#\[multilib\]/,/^#Include/ s/^#//' /etc/pacman.conf
    grep -q '^\[multilib\]' /etc/pacman.conf || printf '\n[multilib]\nInclude = /etc/pacman.d/mirrorlist\n' >>/etc/pacman.conf
fi

if ((container)); then
    # The container image ships without man pages and keys; initialise the keyring.
    pacman-key --init >/dev/null
    pacman-key --populate archlinux >/dev/null
fi

step "Installing build tools"
pkgs=(archiso arch-install-scripts git base-devel pacman-contrib python python-pillow python-numpy python-pytest
    librsvg grub ttf-dejavu squashfs-tools libisoburn mtools dosfstools erofs-utils curl)
((qemu)) && pkgs+=(qemu-desktop edk2-ovmf python-pexpect)
pacman -Syu --needed --noconfirm "${pkgs[@]}"

step "Trusting the EndeavourOS repository"
keyrings=/usr/share/pacman/keyrings
if ! pacman -Q endeavouros-keyring &>/dev/null; then
    base="$EOS_KEYRING_REPO/$EOS_KEYRING_COMMIT"
    fetch "$base/endeavouros.gpg" "$EOS_KEYRING_GPG_SHA256" "$keyrings/endeavouros.gpg"
    fetch "$base/endeavouros-trusted" "$EOS_KEYRING_TRUSTED_SHA256" "$keyrings/endeavouros-trusted"
    fetch "$base/endeavouros-revoked" "$EOS_KEYRING_REVOKED_SHA256" "$keyrings/endeavouros-revoked"
    pacman-key --populate endeavouros
fi
if [[ ! -e /etc/pacman.d/endeavouros-mirrorlist ]]; then
    fetch "$EOS_MIRRORLIST_REPO/$EOS_MIRRORLIST_COMMIT/endeavouros-mirrorlist/endeavouros-mirrorlist" \
        "$EOS_MIRRORLIST_SHA256" /etc/pacman.d/endeavouros-mirrorlist
fi

if ((builder)); then
    step "Creating the unprivileged build user"
    id builder &>/dev/null || useradd -m -s /bin/bash builder
    if ((container)); then
        echo 'builder ALL=(ALL:ALL) NOPASSWD: ALL' >/etc/sudoers.d/90-builder
    else
        echo 'builder ALL=(root) NOPASSWD: /usr/bin/pacman' >/etc/sudoers.d/90-builder
    fi
    chmod 440 /etc/sudoers.d/90-builder
fi

git config --global --add safe.directory "$PWD" || true
git config --global --add safe.directory "$PWD/desktop/dots" || true
step "Build host ready. Next: ./build.sh"
