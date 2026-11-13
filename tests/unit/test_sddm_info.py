"""The login screen's system information (distrokit.sddm_info) and its service."""
import os
from pathlib import Path

from distrokit import sddm_info
from distrokit.branding import load as load_branding
from distrokit.build import stage


def test_fastfetch_lines_with_the_distributions_config(tmp_path, monkeypatch):
    config = tmp_path / "fastfetch.jsonc"
    config.write_text("{}")
    seen = tmp_path / "args"
    fake = tmp_path / "bin" / "fastfetch"
    fake.parent.mkdir()
    # fastfetch --pipe with a tab separator: the title, separators, session lines and colour blocks are left out.
    fake.write_text("#!/bin/sh\necho \"$@\" > " + str(seen) + "\n"
                    "printf 'root@box\\n-------\\nOS\\tNexora Linux x86_64\\nKernel\\tLinux 6.18\\n"
                    "Uptime\\t3 mins\\nShell\\tbash 5.3\\nCPU\\tIntel i7: 8 cores\\n\\033[40m   \\033[m\\n'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake.parent}:{os.environ['PATH']}")
    rows = sddm_info.fastfetch_rows(config)
    assert rows == [["OS", "Nexora Linux x86_64"], ["Kernel", "Linux 6.18"], ["CPU", "Intel i7: 8 cores"]]
    args = seen.read_text()
    assert f"--config {config}" in args and "--logo none" in args and "--pipe" in args


def test_written_qml_is_safe_and_atomic(tmp_path):
    out = tmp_path / "sddm" / "SystemInfo.qml"
    sddm_info.write(out, sddm_info.qml('host"; Qt.quit(); "', [["OS", 'a "b" \\ c']]))
    text = out.read_text()
    assert text.startswith("//") and "Item {" in text
    assert 'readonly property string host: "host\\"; Qt.quit(); \\""' in text
    assert oct(out.stat().st_mode & 0o777) == "0o644"
    assert not list(out.parent.glob(".*.tmp"))


def test_service_runs_before_sddm(tmp_path):
    b = load_branding()
    stage.Stage(tmp_path, b).run("core")
    unit = (tmp_path / f"usr/lib/systemd/system/{b.id}-sddm-info.service").read_text()
    assert f"ExecStart=/usr/lib/{b.id}/bin/{b.id}-sddm-info" in unit and "Before=display-manager.service" in unit
    dropin = (tmp_path / f"usr/lib/systemd/system/sddm.service.d/{b.id}-sddm-info.conf").read_text()
    assert f"Wants={b.id}-sddm-info.service" in dropin and f"After={b.id}-sddm-info.service" in dropin
    theme = Path(__file__).resolve().parents[2] / "branding/sddm/theme.conf.in"
    assert "infoFile=/var/lib/@DISTRO_ID@/sddm/SystemInfo.qml" in theme.read_text()
