# Release process

Releases are tagged `vYYYY.MM` (a second release in a month: `vYYYY.MM.1`).

## Before tagging

1. `main` is green in CI (lint, tests, Arch packages).
2. Run the ISO workflow manually (*Actions → ISO → Run workflow*) and check
   that every QEMU scenario passes; download the ISO and try it on at least one
   real machine with each GPU vendor you can reach.
3. Update pinned inputs if needed, each in its own reviewed commit:
   * `git -C desktop/dots pull` (the desktop), then `make test` (keybind collisions);
   * `scripts/build-packages.sh --update-lock` (AUR commits: read the diffs of
     changed PKGBUILDs);
   * `scripts/update-pins.sh` (EndeavourOS keyring and mirror list: check any
     new signing keys);
   * model sizes in `ai/models/catalog.toml` if upstream files changed.
4. Bump `__version__` in `lib/distrokit/__init__.py` for user-visible changes
   to the tools.

## From your own build

`./build.sh --publish` (with `--container` anywhere, or on Arch) builds the
ISO and then publishes it with `scripts/publish-release.sh`:

```bash
gh auth login                         # once: the GitHub CLI (pacman -S github-cli)
./build.sh --container --publish      # or --tag v2026.10.1 to choose the tag
scripts/publish-release.sh            # publish the ISO already in dist/ (--dry-run to look first)
```

1. The tag is `v<version>` from the ISO (`vYYYY.MM`), or the next free
   `vYYYY.MM.N` when that one already marks another commit. It is put on the
   commit the ISO was built from (recorded in its metadata), so commit before
   building: `--publish` refuses to start with uncommitted changes. With
   `GPGKEY` set the tag is signed.
2. The release is created as a draft with the ISO (split into parts under
   GitHub's 2 GiB limit, with joining instructions for Linux, macOS and
   Windows in the notes), the SHA-256 and BLAKE2 checksums and the metadata.
3. The tag is pushed and the release published. Because the release already
   carries the ISO, the tag's Release workflow does not build another.
4. The `repo` release (the package repository installed systems use) gets
   this build's packages, unless `--no-repo`.

Publishing runs on your machine as you (never in the build container) and
uploads several GB: on a slow connection, prefer tagging and letting CI build.
Running it again for the same tag replaces the release's files.

## Tagging (CI builds the release)

```bash
git tag -s v2026.09 -m "Nexora 2026.09"
git push origin v2026.09
```

`.github/workflows/release.yml` then:

1. builds the ISO in a container (`iso.yml`) and runs the QEMU scenarios;
2. creates the GitHub release with the ISO (split into parts under 2 GiB when
   larger), SHA-256 and BLAKE2 checksums, and the metadata (package lists, AUR
   lock, build information), with the same `scripts/publish-release.sh`;
3. updates the `repo` release, which is the package repository installed
   systems use (`DISTRO_REPO_SERVER`), with the packages of this build
   (`scripts/publish-repo.sh`).

## Signing

Add a GPG private key as the repository secret `GPG_PRIVATE_KEY` (no
passphrase, or use a subkey dedicated to CI). Builds then sign packages, the
repository database and the checksums. Set `DISTRO_REPO_KEY_ID` in
`distro.conf` to the key's fingerprint and ship the public key (for example
in a keyring package) so installed systems require signatures; until then the
repository is used with `DISTRO_REPO_SIGLEVEL_UNSIGNED`.

## After the release

* Announce with the release notes, the checksums, and known issues.
* Watch for bug reports with `nexora doctor --report` bundles.
