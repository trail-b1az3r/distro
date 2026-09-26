#!/usr/bin/env bash
# Refresh the pinned EndeavourOS keyring and mirror list in iso/sources.conf
# to the current upstream commits, recording their SHA-256 sums. Review the
# resulting diff (new signing keys!) before committing it.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
# shellcheck source=SCRIPTDIR/../iso/sources.conf
source iso/sources.conf

head_of() { git ls-remote "https://github.com/endeavouros-team/$1" HEAD | cut -f1; }
sum_of() { curl -fsSL --retry 3 "$1" | sha256sum | cut -d' ' -f1; }
set_var() { sed -i "s|^$1=.*|$1=\"$2\"|" iso/sources.conf; }

k="$(head_of keyring)"
m="$(head_of PKGBUILDS)"
set_var EOS_KEYRING_COMMIT "$k"
set_var EOS_KEYRING_GPG_SHA256 "$(sum_of "$EOS_KEYRING_REPO/$k/endeavouros.gpg")"
set_var EOS_KEYRING_TRUSTED_SHA256 "$(sum_of "$EOS_KEYRING_REPO/$k/endeavouros-trusted")"
set_var EOS_KEYRING_REVOKED_SHA256 "$(sum_of "$EOS_KEYRING_REPO/$k/endeavouros-revoked")"
set_var EOS_MIRRORLIST_COMMIT "$m"
set_var EOS_MIRRORLIST_SHA256 "$(sum_of "$EOS_MIRRORLIST_REPO/$m/endeavouros-mirrorlist/endeavouros-mirrorlist")"
git --no-pager diff --stat iso/sources.conf
echo "Updated iso/sources.conf; review the keyring change before committing."
