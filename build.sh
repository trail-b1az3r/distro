#!/usr/bin/env bash
# Build the live ISO: dist/<Name>-<YYYY.MM>-x86_64.iso (+ checksums/, metadata/).
#
#   ./build.sh [--profile minimal|standard|developer|ai] [--offline minimal|full]
#              [--clean] [--debug] [--container] [--skip-packages] [--dry-run]
#
# Runs on Arch Linux or EndeavourOS as root (after scripts/bootstrap.sh), or
# anywhere with Docker or Podman using --container. See docs/iso-building.md.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

usage() {
    sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
    cat <<'TXT'

Options:
  --profile P      installation profile offered by default and carried offline (default: standard)
  --offline MODE   minimal: distribution packages on the ISO, the rest is downloaded while installing
                   full:    every package an installation can need (larger ISO, installs with no network)
  --clean          remove previous work directories first
  --debug          fast compression, keep the work directory, show every command
  --container      build inside an Arch Linux container (Docker or Podman)
  --skip-packages  reuse the packages already built in build/repo
  --dry-run        print the build commands without running them
  --archive-date D pin Arch packages to the Arch Linux Archive snapshot of day D (YYYY/MM/DD)
  --config FILE    read settings (ISO_PROFILE, ISO_OFFLINE, ARCHIVE_DATE, ...) from FILE;
                   see iso/build.env.example
TXT
}

die() { echo "build.sh: $*" >&2; exit 1; }

container=0
args=()
while (($#)); do
    case "$1" in
        -h | --help) usage; exit 0 ;;
        --container) container=1 ;;
        --debug) args+=("$1"); set -x ;;
        --config)
            (($# >= 2)) || die "$1 needs a file"
            [[ -r "$2" ]] || die "cannot read $2"
            set -a
            # shellcheck source=/dev/null
            source "$2"
            set +a
            shift ;;
        --profile | --offline | --archive-date | --sign)
            (($# >= 2)) || die "$1 needs a value"
            args+=("$1" "$2"); shift ;;
        --clean | --skip-packages | --dry-run | --no-multilib) args+=("$1") ;;
        *) die "unknown option $1 (see --help)" ;;
    esac
    shift
done

# The desktop comes from the dots submodule.
if [[ -d .git && ! -e desktop/dots/dots ]]; then
    git submodule update --init --recursive
fi
[[ -e desktop/dots/dots ]] || die "desktop/dots is empty: clone with --recursive or run 'git submodule update --init --recursive'"

if ((container)); then
    engine="$(command -v podman || command -v docker || true)"
    [[ -n "$engine" ]] || die "--container needs podman or docker"
    # shellcheck source=SCRIPTDIR/iso/sources.conf
    source iso/sources.conf
    run=("$engine")
    # The Docker daemon's socket belongs to root (and the docker group).
    if [[ ${engine##*/} == docker && -z ${DOCKER_HOST:-} && -S /var/run/docker.sock && ! -w /var/run/docker.sock ]]; then
        echo "build.sh: $(id -un) cannot use the Docker daemon: running docker with sudo (or join the docker group)" >&2
        run=(sudo "$engine")
    fi
    if [[ -d /usr/lib/modules && ! -d /usr/lib/modules/$(uname -r) ]]; then
        echo "build.sh: warning: the running kernel's modules ($(uname -r)) are gone, usually after a kernel update:" \
            "reboot if the container fails to start" >&2
    fi
    envs=()
    for v in SOURCE_DATE_EPOCH ARCHIVE_DATE GPGKEY ISO_PROFILE ISO_OFFLINE AUR_GIT_MIRROR; do
        if [[ -v $v ]]; then envs+=(-e "$v=${!v}"); fi
    done
    owner="${HOST_UID:-${SUDO_UID:-$(id -u)}}:${HOST_GID:-${SUDO_GID:-$(id -g)}}"
    inner="scripts/bootstrap.sh --container && BUILD_CONTAINER=1 BUILD_USER=builder ./build.sh ${args[*]@Q}"
    inner+=" ; status=\$?; chown -R $owner build dist checksums metadata 2>/dev/null; exit \$status"
    # Host networking: the build only makes outgoing connections, and a bridge
    # needs veth interfaces, which fail on hosts that cannot load the module.
    exec "${run[@]}" run --rm --privileged --network host \
        -v "$PWD:/src" -w /src "${envs[@]}" \
        "$BUILD_IMAGE" bash -c "$inner"
fi

[[ -e /etc/arch-release ]] || die "this host is not Arch-based: use ./build.sh --container"
if ((EUID != 0)) && [[ " ${args[*]} " != *" --dry-run "* ]]; then
    exec sudo --preserve-env=SOURCE_DATE_EPOCH,ARCHIVE_DATE,GPGKEY,BUILD_USER,BUILD_CONTAINER,ISO_PROFILE,ISO_OFFLINE,AUR_GIT_MIRROR "$0" "${args[@]}"
fi
export BUILD_USER="${BUILD_USER:-${SUDO_USER:-builder}}"
id "$BUILD_USER" &>/dev/null || die "build user '$BUILD_USER' does not exist (makepkg does not run as root): run scripts/bootstrap.sh --builder"
git config --global --add safe.directory "$PWD" 2>/dev/null || true
PYTHONPATH=lib exec python3 -m distrokit.build.iso build "${args[@]}"
