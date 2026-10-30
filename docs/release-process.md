# Release process

Releases are numbered `YY.MM.<release>` with a name, both set in `distro.conf`
(`ISO_VERSION_FORMAT`, `ISO_RELEASE`, `ISO_CODENAME`). The October 2026
maintenance release is **26.10.0.1.2 "Origin"**, tagged `v26.10.0.1.2`.
Actions > Tag puts a tag on a commit without releasing it. Bump `ISO_RELEASE`
(and give it a new `ISO_CODENAME`) for each release; use a new patch number
rather than moving a tag that already has a published release.

## Before tagging

1. `main` is green in CI (lint, tests, Arch packages).
2. The Release workflow builds the **Developer** profile with the **Full offline**
   repository and runs every QEMU scenario, including a Developer installation
   with networking disabled. Do not publish unless those checks pass.
3. Test the ISO on at least one real machine, including a Wi-Fi connection
   through Halcyon's NetworkManager password agent.
4. Update pinned inputs if needed, each in its own reviewed commit:
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
./build.sh --container --publish      # or --tag v26.10.0.1.0.1 to choose the tag
scripts/publish-release.sh            # publish the ISO already in dist/ (--dry-run to look first)
```

1. The tag is `v<version>` from the ISO (`v26.10.0.1.0`), or the next free
   `v<version>.N` when that one already marks another commit. It is put on the
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
git tag -s v26.10.0.1.0 -m 'Nexora Linux 26.10.0.1.0 "Origin"'
git push origin v26.10.0.1.0
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

## The RELEASE_TOKEN secret

The workflows' own token (`GITHUB_TOKEN`) may not create releases in this
repository, nor tag a commit whose workflow files differ from `main`'s
(GitHub: "Resource not accessible by integration", "without `workflows`
permission"). Give the workflows a token of yours instead:

1. GitHub > Settings > Developer settings > Fine-grained tokens > Generate:
   only this repository, permissions **Contents: Read and write** and
   **Workflows: Read and write**.
2. This repository > Settings > Secrets and variables > Actions > New
   repository secret: name `RELEASE_TOKEN`, the token as its value.

Release and Publish use it whenever it is set. **Actions > Publish** publishes
the ISO an earlier run built and tested (its run ID and the tag), without
building it again.
