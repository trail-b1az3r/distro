"""Where things live, both in a source checkout and on an installed system.

The same code runs from the git repository (tests, ISO builds) and from the
installed package. The layouts are:

=================  ==========================  ================================
What               Source checkout             Installed system
=================  ==========================  ================================
Python code        ``<repo>/lib/distrokit``    ``/usr/lib/<id>/distrokit``
Data (profiles,    ``<repo>/``                 ``/usr/share/<id>/``
hardware tables,
AI catalogues...)
System config      n/a                         ``/etc/<id>/``
State              n/a                         ``/var/lib/<id>/``
Logs               n/a                         ``/var/log/<id>/``
=================  ==========================  ================================

``DISTROKIT_DATA`` overrides the data root, which the tests use.
"""

from __future__ import annotations

import os
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
_CODE_ROOT = _PKG_DIR.parent


def _detect_data_root() -> Path:
    override = os.environ.get("DISTROKIT_DATA")
    if override:
        return Path(override).resolve()
    repo = _CODE_ROOT.parent
    if (repo / "distro.conf").is_file() and (repo / "lib" / "distrokit").is_dir():
        return repo
    # Installed: /usr/lib/<id>/distrokit -> /usr/share/<id>
    return Path("/usr/share") / _CODE_ROOT.name


DATA_ROOT: Path = _detect_data_root()
CODE_ROOT: Path = _CODE_ROOT
PACKAGE_DIR: Path = _PKG_DIR


def is_source_checkout() -> bool:
    return (DATA_ROOT / "lib" / "distrokit").is_dir()


def data(*parts: str) -> Path:
    """Path to a data file shipped with the distribution."""
    return DATA_ROOT.joinpath(*parts)


def qml_dir() -> Path:
    return PACKAGE_DIR / "gui" / "qml"


class SystemPaths:
    """Runtime paths on a (possibly not yet booted) system rooted at ``root``.

    During installation ``root`` is the target mount point, so the same code
    writes ``/mnt/etc/<id>/...`` in the installer and ``/etc/<id>/...`` later.
    """

    def __init__(self, distro_id: str, root: Path | str = "/"):
        self.id = distro_id
        self.root = Path(root)

    def _p(self, path: str) -> Path:
        return self.root / path.lstrip("/")

    @property
    def sysconf(self) -> Path:
        return self._p(f"/etc/{self.id}")

    @property
    def state(self) -> Path:
        return self._p(f"/var/lib/{self.id}")

    @property
    def logs(self) -> Path:
        return self._p(f"/var/log/{self.id}")

    @property
    def install_record(self) -> Path:
        return self.state / "install.json"

    @property
    def hardware_report(self) -> Path:
        return self.state / "hardware.json"

    @property
    def gpu_state(self) -> Path:
        return self.state / "gpu.json"

    @property
    def pending_tasks(self) -> Path:
        return self.state / "pending-tasks.json"

    @property
    def share(self) -> Path:
        return self._p(f"/usr/share/{self.id}")

    @property
    def libdir(self) -> Path:
        return self._p(f"/usr/lib/{self.id}")

    def path(self, absolute: str) -> Path:
        return self._p(absolute)


def user_state_dir(distro_id: str, home: Path | None = None) -> Path:
    home = home or Path.home()
    base = os.environ.get("XDG_STATE_HOME") if home == Path.home() else None
    return (Path(base) if base else home / ".local" / "state") / distro_id


def user_config_dir(distro_id: str, home: Path | None = None) -> Path:
    home = home or Path.home()
    base = os.environ.get("XDG_CONFIG_HOME") if home == Path.home() else None
    return (Path(base) if base else home / ".config") / distro_id


def user_data_dir(distro_id: str, home: Path | None = None) -> Path:
    home = home or Path.home()
    base = os.environ.get("XDG_DATA_HOME") if home == Path.home() else None
    return (Path(base) if base else home / ".local" / "share") / distro_id
