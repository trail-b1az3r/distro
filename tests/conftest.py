import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lib"))
sys.path.insert(0, str(REPO / "tests"))
os.environ.setdefault("NO_COLOR", "1")

import hwfixtures  # noqa: E402


@pytest.fixture
def repo() -> Path:
    return REPO


@pytest.fixture
def machine(tmp_path):
    """Factory: machine("surface_pro7") -> (root path, HardwareReport)."""
    from distrokit import hardware

    def build(name: str):
        root = tmp_path / name
        hwfixtures.MACHINES[name](root)
        return root, hardware.detect(root, live_label_prefix="NEXORA")

    return build
