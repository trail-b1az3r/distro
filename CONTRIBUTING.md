# Contributing

Thank you for helping! Bug reports, hardware reports, documentation and code
are all welcome.

## Reporting problems

Include `nexora doctor --report` (review the bundle first) and, for
installation problems, `/var/log/nexora/install.log`. For hardware that is
detected wrongly, `nexora hardware --json` and `lspci -nnk` help most.

## Development setup

No Arch system is needed for most work:

```bash
git clone --recursive https://github.com/trail-b1az3r/distro && cd distro
python3 -m pip install pytest pillow numpy pyside6 ruff
make test-unit test-gui lint
make installer-demo              # the installer against a simulated machine
PYTHONPATH=lib python3 -m distrokit hardware    # the CLI from the checkout
```

Building packages and the ISO needs Arch Linux (or `./build.sh --container`).

## Guidelines

* Keep `lib/distrokit` standard-library only (the GUIs may use PySide6), and
  keep data in data files (`profiles/`, `packages/`, `hardware/`, `ai/`).
* Never hard-code the distribution's name: use `Branding` (`b.name`, `b.id`,
  `b.cli`) in code and `@DISTRO_*@` tokens in templates.
* Anything that changes a system goes through `util.Runner`, takes a `root`,
  and is described to the user before it runs.
* Add tests: a fixture machine for new hardware, a dry-run assertion for new
  installer behaviour, a scenario for new install paths.
* `make lint` and `make test` must pass. CI runs them plus the Arch package
  build.
* Commit messages: imperative summary line, a body explaining why.

## Pinned inputs

Changes to `desktop/dots`, `packages/aur.lock.json` and `iso/sources.conf`
pull third-party code into the build. Keep them in separate commits and say
what changed upstream.
