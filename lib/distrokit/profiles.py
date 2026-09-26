"""Installation profiles, features and package manifests.

* ``packages/lists/*.list``  one package per line (``#`` comments,
  ``@KEY@`` branding tokens allowed).
* ``profiles/features.toml`` switchable features and the lists they add.
* ``profiles/<id>.toml``     a profile: base lists plus feature defaults,
  optionally inheriting another profile.
* ``packages/editors.toml``  the code editor implementations.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths
from .branding import Branding
from .branding import load as load_branding


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class Feature:
    id: str
    kind: str
    group: str
    order: int
    label: str
    description: str
    lists: tuple[str, ...] = ()
    choices: dict[str, tuple[str, ...]] = field(default_factory=dict)
    default: Any = None
    requires_network: bool = False

    def validate_value(self, value: Any) -> Any:
        if self.kind == "bool":
            if not isinstance(value, bool):
                raise ProfileError(f"feature {self.id} expects true/false, got {value!r}")
        elif self.kind == "choice":
            if value not in self.choices:
                raise ProfileError(f"feature {self.id} must be one of {sorted(self.choices)}, got {value!r}")
        return value

    def lists_for(self, value: Any) -> tuple[str, ...]:
        if self.kind == "bool":
            return self.lists if value else ()
        return self.choices.get(value, ())

    def enabled(self, value: Any) -> bool:
        if self.kind == "bool":
            return bool(value)
        return value not in (None, "none", "")


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    order: int
    summary: str
    description: str
    approx_size_gb: float
    lists: tuple[str, ...]
    features: dict[str, Any]
    default: bool = False
    inherits: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "order": self.order,
            "summary": self.summary,
            "description": self.description,
            "approxSizeGb": self.approx_size_gb,
            "lists": list(self.lists),
            "features": dict(self.features),
            "default": self.default,
        }


@dataclass(frozen=True)
class Editor:
    id: str
    name: str
    package: str
    source: str
    license: str
    redistributable: bool
    command: str
    desktop_file: str
    notes: str = ""


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"{path}: {exc}") from exc


def load_features(data_root: Path | None = None) -> dict[str, Feature]:
    root = data_root or paths.DATA_ROOT
    raw = _load_toml(root / "profiles" / "features.toml")
    features: dict[str, Feature] = {}
    for fid, spec in raw.items():
        kind = spec.get("kind", "bool")
        if kind not in ("bool", "choice"):
            raise ProfileError(f"feature {fid}: unknown kind {kind!r}")
        choices = {k: tuple(v) for k, v in spec.get("choices", {}).items()}
        if kind == "choice" and not choices:
            raise ProfileError(f"feature {fid}: a choice feature needs choices")
        features[fid] = Feature(
            id=fid,
            kind=kind,
            group=spec.get("group", "Other"),
            order=int(spec.get("order", 100)),
            label=spec["label"],
            description=spec.get("description", ""),
            lists=tuple(spec.get("lists", ())),
            choices=choices,
            default=spec.get("default", False if kind == "bool" else "none"),
            requires_network=bool(spec.get("requires_network", False)),
        )
    return features


def load_profiles(data_root: Path | None = None) -> dict[str, Profile]:
    root = data_root or paths.DATA_ROOT
    features = load_features(root)
    raw: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "profiles").glob("*.toml")):
        if path.name == "features.toml":
            continue
        data = _load_toml(path)
        pid = data.get("profile", {}).get("id")
        if pid != path.stem:
            raise ProfileError(f"{path}: profile.id must be {path.stem!r}")
        raw[pid] = data

    resolved: dict[str, Profile] = {}

    def resolve(pid: str, stack: tuple[str, ...] = ()) -> Profile:
        if pid in resolved:
            return resolved[pid]
        if pid not in raw:
            raise ProfileError(f"unknown profile {pid!r}")
        if pid in stack:
            raise ProfileError(f"profile inheritance loop: {' -> '.join(stack + (pid,))}")
        data = raw[pid]
        meta = data["profile"]
        parent_id = meta.get("inherits", "")
        if parent_id:
            parent = resolve(parent_id, stack + (pid,))
            lists = list(parent.lists)
            feats = dict(parent.features)
        else:
            lists = []
            feats = {fid: f.default for fid, f in features.items()}
        for name in data.get("packages", {}).get("lists", []):
            if name not in lists:
                lists.append(name)
        for fid, value in data.get("features", {}).items():
            if fid not in features:
                raise ProfileError(f"profile {pid}: unknown feature {fid!r}")
            feats[fid] = features[fid].validate_value(value)
        prof = Profile(
            id=pid,
            name=meta["name"],
            order=int(meta.get("order", 100)),
            summary=meta.get("summary", ""),
            description=" ".join(meta.get("description", "").split()),
            approx_size_gb=float(meta.get("approx_size_gb", 0)),
            lists=tuple(lists),
            features=feats,
            default=bool(meta.get("default", False)),
            inherits=parent_id,
        )
        resolved[pid] = prof
        return prof

    for pid in raw:
        resolve(pid)
    defaults = [p.id for p in resolved.values() if p.default]
    if len(defaults) != 1:
        raise ProfileError(f"exactly one profile must set default = true (found {defaults})")
    return dict(sorted(resolved.items(), key=lambda kv: kv[1].order))


def default_profile(profiles: dict[str, Profile]) -> Profile:
    return next(p for p in profiles.values() if p.default)


def load_editors(data_root: Path | None = None) -> dict[str, Editor]:
    root = data_root or paths.DATA_ROOT
    raw = _load_toml(root / "packages" / "editors.toml")
    return {
        eid: Editor(
            id=eid,
            name=spec["name"],
            package=spec["package"],
            source=spec["source"],
            license=spec["license"],
            redistributable=bool(spec["redistributable"]),
            command=spec["command"],
            desktop_file=spec["desktop_file"],
            notes=spec.get("notes", ""),
        )
        for eid, spec in raw.items()
    }


def read_list(name: str, branding: Branding | None = None, data_root: Path | None = None) -> list[str]:
    root = data_root or paths.DATA_ROOT
    branding = branding or load_branding()
    path = root / "packages" / "lists" / f"{name}.list"
    if not path.is_file():
        raise ProfileError(f"package list {name!r} does not exist ({path})")
    packages: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        pkg = branding.render(line)
        if " " in pkg:
            raise ProfileError(f"{path}: one package per line, got {line!r}")
        packages.append(pkg)
    return packages


def available_lists(data_root: Path | None = None) -> list[str]:
    root = data_root or paths.DATA_ROOT
    return sorted(p.stem for p in (root / "packages" / "lists").glob("*.list"))


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


@dataclass
class Selection:
    """The packages chosen for one installation, with where each came from."""

    packages: list[str]
    lists: list[str]
    reasons: dict[str, str]
    features: dict[str, Any]


def effective_features(profile: Profile, overrides: dict[str, Any] | None,
                       features: dict[str, Feature]) -> dict[str, Any]:
    result = dict(profile.features)
    for fid, value in (overrides or {}).items():
        if fid not in features:
            raise ProfileError(f"unknown feature {fid!r}")
        result[fid] = features[fid].validate_value(value)
    return result


def select_packages(
    profile: Profile,
    overrides: dict[str, Any] | None = None,
    extra_lists: list[str] | None = None,
    extra_packages: list[str] | None = None,
    *,
    filesystem: str = "btrfs",
    branding: Branding | None = None,
    data_root: Path | None = None,
) -> Selection:
    root = data_root or paths.DATA_ROOT
    branding = branding or load_branding()
    features = load_features(root)
    feats = effective_features(profile, overrides, features)

    lists = list(profile.lists)
    for fid, value in feats.items():
        feature = features[fid]
        if fid == "snapshots" and filesystem != "btrfs":
            continue
        for name in feature.lists_for(value):
            if name not in lists:
                lists.append(name)
    for name in extra_lists or []:
        if name not in lists:
            lists.append(name)

    packages: list[str] = []
    reasons: dict[str, str] = {}
    for name in lists:
        for pkg in read_list(name, branding, root):
            packages.append(pkg)
            reasons.setdefault(pkg, f"list:{name}")

    if feats.get("code_editor"):
        editors = load_editors(root)
        eid = branding.get("CODE_EDITOR", "code")
        if eid not in editors:
            raise ProfileError(f"CODE_EDITOR={eid!r} is not defined in packages/editors.toml")
        packages.append(editors[eid].package)
        reasons.setdefault(editors[eid].package, "feature:code_editor")

    for pkg in extra_packages or []:
        packages.append(pkg)
        reasons.setdefault(pkg, "extra")

    return Selection(packages=_dedupe(packages), lists=lists, reasons=reasons, features=feats)
