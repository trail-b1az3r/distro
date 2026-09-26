#!/usr/bin/env bash
# Install the ISO in QEMU/KVM for every scenario in tests/qemu/scenarios and
# check the installed systems. See tests/qemu/qemu_test.py and docs/testing.md.
#
#   tests/qemu/run.sh [--iso dist/X.iso] [--scenario NAME]... [--keep] [--timeout MIN] [--list]
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/../.."
exec python3 tests/qemu/qemu_test.py "$@"
