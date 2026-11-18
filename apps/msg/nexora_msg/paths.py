"""Where nexora-msg keeps things (XDG)."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    path = Path(os.environ.get("NEXORA_MSG_DATA") or base / "nexora-msg")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def cache_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    path = base / "nexora-msg"
    path.mkdir(parents=True, exist_ok=True)
    return path


def store_path() -> Path:
    return data_dir() / "messages.db"


def backups_dir() -> Path:
    path = data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path
