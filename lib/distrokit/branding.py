"""Distribution identity, read from ``distro.conf``.

``distro.conf`` is a list of ``KEY="value"`` lines shared with shell scripts.
This module parses it without invoking a shell and exposes the values, plus a
small template renderer that replaces ``@KEY@`` tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import paths

_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
_TOKEN = re.compile(r"@([A-Z][A-Z0-9_]*)@")
_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")

REQUIRED_KEYS = (
    "DISTRO_NAME",
    "DISTRO_PRETTY_NAME",
    "DISTRO_ID",
    "DISTRO_CLI",
    "ISO_LABEL_PREFIX",
    "LIVE_USER",
    "DISTRO_REPO_NAME",
)


class BrandingError(ValueError):
    pass


def _unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        body = raw[1:-1]
        if raw[0] == '"':
            if "$" in body or "`" in body:
                raise BrandingError(f"expansions are not allowed in distro.conf values: {raw}")
            body = body.replace('\\"', '"').replace("\\\\", "\\")
        return body
    if "#" in raw:
        raw = raw.split("#", 1)[0].rstrip()
    if any(c in raw for c in "$`;|&<> "):
        raise BrandingError(f"unquoted value must be a single literal word: {raw}")
    return raw


def parse_conf(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _LINE.match(stripped)
        if not m:
            raise BrandingError(f"line {lineno}: expected KEY=\"value\", got: {line!r}")
        values[m.group(1)] = _unquote(m.group(2))
    return values


@dataclass(frozen=True)
class Branding:
    values: dict[str, str] = field(default_factory=dict)

    def __getitem__(self, key: str) -> str:
        return self.values[key]

    def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    @property
    def name(self) -> str:
        return self.values["DISTRO_NAME"]

    @property
    def pretty_name(self) -> str:
        return self.values["DISTRO_PRETTY_NAME"]

    @property
    def id(self) -> str:
        return self.values["DISTRO_ID"]

    @property
    def cli(self) -> str:
        return self.values["DISTRO_CLI"]

    @property
    def repo_name(self) -> str:
        return self.values["DISTRO_REPO_NAME"]

    def package(self, component: str) -> str:
        """Package name of one of the distribution's own components."""
        return f"{self.id}-{component}"

    def system_paths(self, root: Path | str = "/") -> paths.SystemPaths:
        return paths.SystemPaths(self.id, root)

    def validate(self) -> None:
        missing = [k for k in REQUIRED_KEYS if not self.values.get(k)]
        if missing:
            raise BrandingError(f"distro.conf is missing: {', '.join(missing)}")
        for key in ("DISTRO_ID", "DISTRO_CLI", "DISTRO_REPO_NAME"):
            if not _ID_RE.match(self.values[key]):
                raise BrandingError(f"{key} must match {_ID_RE.pattern}: {self.values[key]!r}")
        if not re.match(r"^[A-Z0-9_]{1,24}$", self.values["ISO_LABEL_PREFIX"]):
            raise BrandingError("ISO_LABEL_PREFIX must be 1-24 characters of A-Z, 0-9 and _")
        if not re.match(r"^[a-z_][a-z0-9_-]{0,31}$", self.values["LIVE_USER"]):
            raise BrandingError("LIVE_USER must be a valid user name")
        for key, value in self.values.items():
            if key.startswith("BRAND_") and not re.match(r"^#[0-9A-Fa-f]{6}$", value):
                raise BrandingError(f"{key} must be a #RRGGBB colour: {value!r}")

    def render(self, text: str, extra: dict[str, str] | None = None, strict: bool = True) -> str:
        """Replace ``@KEY@`` tokens with branding (and ``extra``) values."""
        table = dict(self.values)
        if extra:
            table.update(extra)

        def sub(m: re.Match[str]) -> str:
            key = m.group(1)
            if key in table:
                return table[key]
            if strict:
                raise BrandingError(f"unknown template token @{key}@")
            return m.group(0)

        return _TOKEN.sub(sub, text)

    def render_path(self, relpath: str) -> str:
        return self.render(relpath)

    def os_release(self, version: str, build_id: str = "") -> str:
        lines = {
            "NAME": self.name,
            "PRETTY_NAME": self.pretty_name,
            "ID": self.id,
            "ID_LIKE": self.get("DISTRO_ID_LIKE", "arch"),
            "BUILD_ID": build_id or "rolling",
            "VERSION_ID": version,
            "ANSI_COLOR": "38;2;124;108;255",
            "HOME_URL": self.get("DISTRO_HOME_URL"),
            "DOCUMENTATION_URL": self.get("DISTRO_DOC_URL"),
            "SUPPORT_URL": self.get("DISTRO_SUPPORT_URL"),
            "BUG_REPORT_URL": self.get("DISTRO_BUG_URL"),
            "LOGO": self.id,
        }
        return "".join(f'{k}="{v}"\n' for k, v in lines.items() if v)


def load_file(path: Path) -> Branding:
    b = Branding(parse_conf(path.read_text(encoding="utf-8")))
    b.validate()
    return b


@lru_cache(maxsize=1)
def load() -> Branding:
    """Branding of this checkout / installation."""
    return load_file(paths.data("distro.conf"))
