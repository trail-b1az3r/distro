"""Small shared helpers: running commands, terminal output, confirmation,
privilege handling and file writes."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

# --------------------------------------------------------------------------
# Terminal output
# --------------------------------------------------------------------------


def _color_enabled(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"

    def __init__(self, enabled: bool | None = None):
        self.enabled = _color_enabled() if enabled is None else enabled

    def __call__(self, text: str, *codes: str) -> str:
        if not self.enabled or not codes:
            return text
        return "".join(codes) + text + self.RESET

    def ok(self, text: str) -> str:
        return f"{self('✓', self.GREEN, self.BOLD)} {text}"

    def warn(self, text: str) -> str:
        return f"{self('!', self.YELLOW, self.BOLD)} {text}"

    def fail(self, text: str) -> str:
        return f"{self('✗', self.RED, self.BOLD)} {text}"

    def info(self, text: str) -> str:
        return f"{self('•', self.CYAN)} {text}"

    def header(self, text: str) -> str:
        return self(text, self.BOLD)

    def dim(self, text: str) -> str:
        return self(text, self.DIM)


style = Style()


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def table(rows: Iterable[tuple[str, str]], indent: int = 0) -> str:
    rows = list(rows)
    if not rows:
        return ""
    width = max(len(k) for k, _ in rows)
    pad = " " * indent
    return "\n".join(f"{pad}{k.ljust(width)}  {v}" for k, v in rows)


# --------------------------------------------------------------------------
# Running commands
# --------------------------------------------------------------------------


class CommandError(RuntimeError):
    def __init__(self, cmd: Sequence[str], returncode: int, output: str = ""):
        self.cmd = list(cmd)
        self.returncode = returncode
        self.output = output
        tail = output.strip().splitlines()[-15:]
        msg = f"command failed ({returncode}): {shlex.join(self.cmd)}"
        if tail:
            msg += "\n" + "\n".join("  " + line for line in tail)
        super().__init__(msg)


@dataclass
class Result:
    cmd: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass
class Runner:
    """Runs commands, or records them when ``dry_run`` is set.

    ``log`` receives every command line and every output line, which is how
    the installer streams live logs to its UI.
    """

    dry_run: bool = False
    log: Callable[[str], None] | None = None
    env: dict[str, str] = field(default_factory=dict)
    recorded: list[list[str]] = field(default_factory=list)

    def _emit(self, line: str) -> None:
        if self.log:
            self.log(line)

    def run(
        self,
        cmd: Sequence[str],
        *,
        check: bool = True,
        capture: bool = False,
        input: str | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        stream: bool = True,
        mutating: bool = True,
        secret_input: bool = False,
    ) -> Result:
        cmd = [str(c) for c in cmd]
        shown = shlex.join(cmd)
        self._emit(f"$ {shown}")
        if self.dry_run and mutating:
            self.recorded.append(cmd)
            return Result(cmd, 0, "", "")
        full_env = os.environ.copy()
        full_env.update(self.env)
        if env:
            full_env.update(env)
        full_env.setdefault("LC_ALL", "C.UTF-8")
        exe = cmd[0]
        found = os.path.exists(exe) if "/" in exe else shutil.which(exe, path=full_env.get("PATH"))
        if not found:
            message = f"{cmd[0]}: command not found"
            self._emit(message)
            if check:
                raise CommandError(cmd, 127, message)
            return Result(cmd, 127, "", message)
        if capture or not stream:
            proc = subprocess.run(
                cmd,
                input=input,
                text=True,
                capture_output=True,
                cwd=cwd,
                env=full_env,
            )
            if not capture:
                for line in (proc.stdout + proc.stderr).splitlines():
                    self._emit(line)
            if check and proc.returncode != 0:
                raise CommandError(cmd, proc.returncode, proc.stdout + proc.stderr)
            return Result(cmd, proc.returncode, proc.stdout, proc.stderr)

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=cwd,
            env=full_env,
            bufsize=1,
        )
        if input is not None:
            assert proc.stdin
            proc.stdin.write(input)
            proc.stdin.close()
        tail: list[str] = []
        assert proc.stdout
        for line in proc.stdout:
            line = line.rstrip("\n")
            self._emit(line)
            tail.append(line)
            if len(tail) > 200:
                del tail[:100]
        rc = proc.wait()
        if check and rc != 0:
            raise CommandError(cmd, rc, "\n".join(tail))
        return Result(cmd, rc, "\n".join(tail), "")

    def output(self, cmd: Sequence[str], check: bool = True) -> str:
        """Run a read-only command and return its stdout (runs in dry-run too)."""
        return self.run(cmd, check=check, capture=True, mutating=False).stdout


def run_quiet(cmd: Sequence[str], timeout: float = 10.0) -> tuple[int, str]:
    """Run a read-only probe; never raises. Returns (rc, stdout)."""
    try:
        proc = subprocess.run(
            [str(c) for c in cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C.UTF-8"},
        )
        return proc.returncode, proc.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def which(name: str) -> str | None:
    return shutil.which(name)


# --------------------------------------------------------------------------
# Interaction and privileges
# --------------------------------------------------------------------------


def confirm(question: str, default: bool = False, assume_yes: bool = False) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return default
    hint = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{question} {hint} ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def is_root() -> bool:
    return os.geteuid() == 0


def escalate(reason: str, argv: list[str] | None = None) -> None:
    """Re-run this process with sudo after telling the user why.

    Never escalates silently: the reason is always printed first, and sudo
    itself asks for the password. Returns only if already root.
    """
    if is_root():
        return
    sudo = which("sudo") or which("pkexec")
    if not sudo:
        eprint(style.fail(f"Administrator rights are needed to {reason}, and neither sudo nor pkexec is available."))
        raise SystemExit(1)
    eprint(style.info(f"Administrator rights are needed to {reason}."))
    argv = argv if argv is not None else [sys.executable, *sys.argv]
    env_keep = []
    for key in ("DISTROKIT_DATA", "PYTHONPATH", "NO_COLOR", "FORCE_COLOR"):
        if key in os.environ:
            env_keep.append(f"{key}={os.environ[key]}")
    cmd = [sudo]
    if os.path.basename(sudo) == "sudo":
        cmd += ["env", *env_keep] if env_keep else []
    os.execvp(cmd[0], cmd + argv)


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------


def atomic_write(path: Path, content: str | bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode() if isinstance(content, str) else content
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def read_text(path: Path | str, default: str = "") -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return default


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data: Any, mode: int = 0o644) -> None:
    atomic_write(path, json.dumps(data, indent=2, sort_keys=True) + "\n", mode)


def human_bytes(n: float, binary: bool = True) -> str:
    step = 1024.0 if binary else 1000.0
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"] if binary else ["B", "kB", "MB", "GB", "TB", "PB"]
    value = float(n)
    for unit in units:
        if abs(value) < step or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}".replace(".0 ", " ")
        value /= step
    return f"{value:.1f} {units[-1]}"


def human_size_marketing(n: int) -> str:
    """Disk size the way it is printed on the box (1 TB, 512 GB)."""
    gb = n / 1e9
    if gb >= 1000:
        tb = gb / 1000
        return f"{tb:.0f} TB" if abs(tb - round(tb)) < 0.1 else f"{tb:.1f} TB"
    return f"{gb:.0f} GB"
