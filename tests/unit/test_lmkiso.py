"""Syntax and advertised options for the local ISO wrapper."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "lmkiso"


def test_lmkiso_is_executable_and_valid_bash():
    assert os.access(SCRIPT, os.X_OK)
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_lmkiso_exposes_requested_options():
    text = SCRIPT.read_text()
    for option in (
        "-apkg", "-apkge", "--contain", "--de", "-V", "-f", "-s", "-sy",
        "--no-confirm", "-p", "-h", "-c", "-o", "-P", "-Pc", "-q", "-D", "-ocl",
    ):
        assert option in text
