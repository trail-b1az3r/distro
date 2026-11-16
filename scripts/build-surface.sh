#!/usr/bin/env bash
# Builds the [nexora-surface] pacman repository's packages: Nexora's Surface support, built entirely from the
# distribution's own sources instead of linux-surface's package server.
#
#   linux-surface, linux-surface-headers   the kernel, from the fork's pkg/arch/kernel (trail-b1az3r/linux-surface)
#   surface-contrib                        the fork's contrib/ (cameras, speaker EQ, Pro 5 suspend)
#   iptsd                                  touch and pen daemon, from linux-surface/iptsd at a pinned tag
#   libwacom-surface                       pen and touch device descriptions, from the AUR
#
# The pins are in hardware/surface/surface.toml ([fork], [build]). Each package's pkgrel gets ".<build>" added
# (SURFACE_BUILD, the CI run number), so a rebuild always upgrades, and a package of the same version from
# linux-surface's own repository is replaced by this one.
#
#   scripts/build-surface.sh [OUT]       (as root in an Arch container; OUT defaults to build/surface)
#   SURFACE_ONLY="iptsd surface-contrib" scripts/build-surface.sh   builds only those (no kernel)
set -Eeuo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
out="$(realpath -m "${1:-$root/build/surface}")"
build="${SURFACE_BUILD:-0}"
only="${SURFACE_ONLY:-linux-surface surface-contrib iptsd libwacom-surface}"
builder="${BUILD_USER:-builder}"

pin() {
    PYTHONPATH="$root/lib" python3 -c '
import sys, tomllib
cfg = tomllib.load(open(sys.argv[1], "rb"))
section, key = sys.argv[2].split(".")
print(cfg[section][key])' "$root/hardware/surface/surface.toml" "$1"
}

FORK_URL="$(pin fork.url)"
FORK_COMMIT="$(pin fork.commit)"
IPTSD_TAG="$(pin build.iptsd_tag)"

work="$out/work"
pkgs="$out/packages"
mkdir -p "$work" "$pkgs"

id "$builder" >/dev/null 2>&1 || useradd -m "$builder"

# Installs a PKGBUILD's dependencies as root (the builder cannot), then builds it as the builder.
make_package() {
    local dir="$1" deps
    deps="$(cd "$dir" && bash -c 'source PKGBUILD >/dev/null 2>&1; echo "${depends[@]} ${makedepends[@]} ${checkdepends[@]}"')"
    if [[ -n "${deps// /}" ]]; then
        # shellcheck disable=SC2086
        pacman -S --needed --noconfirm --asdeps $deps
    fi
    # Every build gets a newer pkgrel than the last, and than linux-surface's own package of the same version.
    sed -i -E "s/^pkgrel=([0-9]+).*/pkgrel=\\1.$build/" "$dir/PKGBUILD"
    chown -R "$builder" "$dir"
    (cd "$dir" && runuser -u "$builder" -- env MAKEFLAGS="-j$(nproc)" PKGEXT=.pkg.tar.zst \
        makepkg -f --noconfirm --skippgpcheck "${@:2}")
    find "$dir" -maxdepth 1 -name '*.pkg.tar.zst' ! -name '*-debug-*' -exec cp -t "$pkgs" -- {} +
}

fetch() {
    local url="$1" ref="$2" dir="$3"
    # The checkout belongs to the builder after a first build: root's git would refuse it.
    local -a g=(git -c safe.directory='*' -C "$dir")
    if [[ ! -d "$dir/.git" ]]; then
        git init -q "$dir"
        "${g[@]}" remote add origin "$url"
    fi
    "${g[@]}" fetch -q --depth 1 origin "$ref"
    "${g[@]}" checkout -q --force FETCH_HEAD
}

if [[ " $only " == *" linux-surface "* || " $only " == *" surface-contrib "* ]]; then
    fetch "$FORK_URL" "$FORK_COMMIT" "$work/fork"
fi

for name in $only; do
    echo "=== $name ==="
    case "$name" in
        linux-surface)
            # The fork's own Arch kernel package (the Arch kernel with the Surface patches). No Secure Boot key: the
            # kernel is not MOK-signed (see docs/surface.md).
            make_package "$work/fork/pkg/arch/kernel"
            ;;
        surface-contrib)
            PYTHONPATH="$root/lib" python3 -m distrokit.build.packages render --out "$work/render" >/dev/null
            dir="$work/render/surface-contrib"
            # Build from the same fork commit as the kernel.
            sed -i -E "s/^_commit=.*/_commit=$FORK_COMMIT/" "$dir/PKGBUILD"
            make_package "$dir"
            ;;
        iptsd)
            # iptsd's PKGBUILD lives in its repository and builds that checkout ($startdir).
            fetch https://github.com/linux-surface/iptsd "refs/tags/$IPTSD_TAG" "$work/iptsd"
            make_package "$work/iptsd"
            ;;
        libwacom-surface)
            fetch https://aur.archlinux.org/libwacom-surface.git HEAD "$work/libwacom-surface"
            # It replaces libwacom: build it without the stock one getting in the way of its tests.
            make_package "$work/libwacom-surface" --nocheck
            ;;
        *) echo "Unknown Surface package: $name" >&2; exit 2 ;;
    esac
done

echo "Built:"
ls -l "$pkgs"
