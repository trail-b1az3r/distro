#!/usr/bin/env bash
# Builds an unsigned FrontlineMessages.ipa (macOS, Xcode and XcodeGen). Sideloading tools (SideStore, AltStore,
# Sideloadly) sign it with your Apple ID when they install it.
#   apps/msg/ios/scripts/build-ipa.sh [OUT_DIR]
set -Eeuo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
out="$(mkdir -p "${1:-$here/build}" && cd "${1:-$here/build}" && pwd -P)"
cd "$here"
xcodegen generate --quiet
xcodebuild -project FrontlineMessages.xcodeproj -scheme FrontlineMessages -configuration Release \
  -destination 'generic/platform=iOS' -derivedDataPath "$out/derived" \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" build | tail -n 25
app="$out/derived/Build/Products/Release-iphoneos/FrontlineMessages.app"
[[ -d "$app" ]] || { echo "build produced no app" >&2; exit 1; }
stage="$out/stage"
mkdir -p "$stage/Payload"
cp -R "$app" "$stage/Payload/"
(cd "$stage" && zip -qry "$out/FrontlineMessages.ipa" Payload)
echo "$out/FrontlineMessages.ipa"
