#!/usr/bin/env bash
# Publish the ISO built last as a GitHub release, tagged at the commit it was
# built from (see docs/release-process.md).
#
#   scripts/publish-release.sh [--tag vYYYY.MM[.N]] [--no-repo] [--prerelease] [--dry-run]
#
# Takes the newest dist/*.iso with its checksums/ and metadata/ (as written by
# ./build.sh, which runs this with --publish) and:
#   1. picks the tag: v<ISO version>, or the next free v<version>.N, unless
#      --tag names one; an existing tag must point at the ISO's commit;
#   2. creates the release as a draft and uploads the ISO (split into parts
#      under GitHub's 2 GiB asset limit), its checksums and metadata;
#   3. creates the tag (signed with GPGKEY when set) and pushes it;
#   4. publishes the release, then updates the "repo" release, the package
#      repository installed systems use (scripts/publish-repo.sh), unless
#      --no-repo.
# The release is complete before the tag is pushed, so the tag's Release
# workflow finds it and does not rebuild. Running it again for the same tag
# replaces the release's files.
#
# Needs git, the GitHub CLI (gh, logged in with `gh auth login` or GH_TOKEN)
# and python3; publishing the package repository also needs repo-add (Arch),
# or a build/repo-assets prepared by ./build.sh --publish.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

die() { echo "publish-release.sh: $*" >&2; exit 1; }
usage() { sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; }

tag="" repo=1 prerelease=() dry=0
while (($#)); do
    case "$1" in
        -h | --help) usage; exit 0 ;;
        --tag) (($# >= 2)) || die "--tag needs a value"; tag="$2"; shift ;;
        --no-repo) repo=0 ;;
        --prerelease) prerelease=(--prerelease) ;;
        --dry-run) dry=1 ;;
        *) die "unknown option $1 (see --help)" ;;
    esac
    shift
done

run() {
    printf '+ %s\n' "$*"
    ((dry)) || "$@"
}

# The ISO and what was recorded about it.
iso="$(find dist -maxdepth 1 -name '*.iso' -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)"
[[ -n "$iso" ]] || die "no ISO in dist/: build one with ./build.sh first"
name="$(basename "$iso" .iso)"
meta="metadata/$name.json"
[[ -f "$meta" ]] || die "$meta is missing: publish an ISO together with the metadata its build wrote"
for sum in sha256 b2sum; do
    [[ -f "checksums/$name.iso.$sum" ]] || die "checksums/$name.iso.$sum is missing"
done
field() { python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get(sys.argv[2]) or "")' "$meta" "$1"; }
version="$(field version)"
commit="$(field source_commit)"
[[ -n "$commit" ]] || die "$meta does not name the commit the ISO was built from (built outside git?)"
git cat-file -e "$commit^{commit}" 2>/dev/null || die "commit $commit (the ISO's source) is not in this repository"
actual="$(sha256sum "$iso" | cut -d' ' -f1)"
[[ "$actual" == "$(field sha256)" ]] || die "$iso does not match the SHA-256 in $meta: rebuild it or restore the right file"

command -v gh >/dev/null || die "the GitHub CLI (gh) is needed: pacman -S github-cli, or https://cli.github.com"
((dry)) || gh auth status >/dev/null 2>&1 || [[ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]] \
    || die "gh is not logged in: run 'gh auth login' (or set GH_TOKEN)"

# The tag: one that is free, or one that already marks this commit.
remote_tag_commit() { git ls-remote --tags origin "refs/tags/$1^{}" "refs/tags/$1" | sort -k2 | tail -1 | cut -f1; }
tag_commit() {
    local c
    c="$(git rev-parse -q --verify "refs/tags/$1^{commit}" 2>/dev/null || true)"
    [[ -n "$c" ]] || c="$(remote_tag_commit "$1")"
    echo "$c"
}
if [[ -z "$tag" ]]; then
    base="v$version" n=0 tag="v$version"
    while :; do
        at="$(tag_commit "$tag")"
        [[ -z "$at" || "$at" == "$commit" ]] && break
        n=$((n + 1)) tag="$base.$n"
    done
else
    at="$(tag_commit "$tag")"
    [[ -z "$at" || "$at" == "$commit" ]] || die "tag $tag already marks ${at:0:12}, not the ISO's commit ${commit:0:12}"
fi
git branch -r --contains "$commit" 2>/dev/null | grep -q . \
    || echo "publish-release.sh: note: ${commit:0:12} is on no pushed branch; pushing the tag publishes it" >&2
echo "==> $name as $tag (commit ${commit:0:12})"

# Release notes, from the build metadata.
work="build/release"
rm -rf "$work"
mkdir -p "$work/upload"
# shellcheck disable=SC1091
home="$(. ./distro.conf && echo "$DISTRO_HOME_URL")"
python3 - "$meta" "$home/blob/$tag/docs" > "$work/notes.md" <<'PY'
import json, sys
m, docs = json.load(open(sys.argv[1])), sys.argv[2]
size = m["size_bytes"] / 2**30
print(f"## {m['name']} {m['version']}\n")
print(f"* ISO: `{m['iso']}` ({size:.2f} GiB), SHA-256 `{m['sha256']}`")
print(f"* Built from `{m['source_commit'][:12]}`, desktop `{m['desktop'][:12]}`, "
      f"{m.get('live_packages', '?')} live packages, offline repository: {m['offline']}")
if m["size_bytes"] > 2_000_000_000:
    parts = (m["size_bytes"] + 1900 * 2**20 - 1) // (1900 * 2**20)
    names = [f"{m['iso']}.part-{i:02d}" for i in range(parts)]
    print(f"\nGitHub takes files up to 2 GiB, so the ISO comes in {parts} parts. Download them all, then join them:\n")
    print(f"* Linux / macOS: `cat {m['iso']}.part-* > {m['iso']}`")
    print(f"* Windows (Command Prompt): `copy /b {' + '.join(names)} {m['iso']}`")
    print(f"\nand check the result against `{m['iso']}.sha256` (`sha256sum -c`, or `certutil -hashfile {m['iso']} SHA256` on Windows).")
print(f"\nWrite it to a USB stick with Rufus (either mode), balenaEtcher, Ventoy or `dd`; see "
      f"[installation]({docs}/installation.md). Turn Secure Boot off to start it "
      f"(Microsoft Surface: [surface.md]({docs}/surface.md#starting-the-iso)).")
PY

if (($(stat -c %s "$iso") > 2000000000)); then
    echo "==> Splitting the ISO into parts under 2 GiB"
    split -b 1900M -d -a 2 "$iso" "$work/upload/$name.iso.part-"
else
    ln -f "$iso" "$work/upload/" 2>/dev/null || cp "$iso" "$work/upload/"
fi
cp "checksums/$name.iso".* "$work/upload/"
for f in metadata/"$name".*; do cp "$f" "$work/upload/"; done
((dry)) && { echo "--- notes ---"; cat "$work/notes.md"; ls -l "$work/upload"; }

# Draft with every file first, then the tag, then publish (see the top).
if gh release view "$tag" >/dev/null 2>&1; then
    run gh release upload "$tag" "$work"/upload/* --clobber
    run gh release edit "$tag" --notes-file "$work/notes.md"
else
    run gh release create "$tag" --draft --target "$commit" --title "$(field name) $version" \
        --notes-file "$work/notes.md" "${prerelease[@]}" "$work"/upload/*
fi
if ! git rev-parse -q --verify "refs/tags/$tag" >/dev/null && [[ -z "$(remote_tag_commit "$tag")" ]]; then
    sign=(-a)
    [[ -n "${GPGKEY:-}" ]] && sign=(-s -u "$GPGKEY")
    run git tag "${sign[@]}" -m "$(field name) $version" "$tag" "$commit"
fi
[[ -n "$(remote_tag_commit "$tag")" ]] || run git push origin "refs/tags/$tag"
run gh release edit "$tag" --draft=false

if ((repo)); then
    assets="build/repo-assets"
    if command -v repo-add >/dev/null; then
        run scripts/publish-repo.sh build/repo "$assets"
    elif [[ ! -d "$assets" ]]; then
        die "repo-add is missing (Arch's pacman), so the package repository was not published; " \
            "build with ./build.sh --container --publish, or rerun with --no-repo"
    fi
    gh release view repo >/dev/null 2>&1 || run gh release create repo --title "Package repository" \
        --notes "pacman repository used by installed systems (see distro.conf)." --latest=false
    run gh release upload repo "$assets"/* --clobber
fi
echo "==> Published $tag: $(gh release view "$tag" --json url --jq .url 2>/dev/null || echo "(dry run)")"
