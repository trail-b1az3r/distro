"""Runs an :class:`~distrokit.installer.steps.Installation` step by step.

Progress is reported as events (dicts), which the graphical installer turns
into its progress bar and live log, and unattended installs print as JSON
lines. Everything is also written to ``/var/log/<id>/installer.log`` on the
live system and copied into the installed system.
"""

from __future__ import annotations

import json
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from .. import util
from .steps import Installation, InstallError

Event = Callable[[dict[str, Any]], None]
_PACMAN_PROGRESS = re.compile(r"^\((\s*\d+)/(\d+)\) (installing|upgrading|reinstalling)")


class Engine:
    def __init__(self, installation: Installation, emit: Event, log_file: Path | None = None):
        self.inst = installation
        self._emit_cb = emit
        self.log_file = log_file
        self._log_fh = None
        self.failed_step: str | None = None
        self.error: str = ""
        self._step_index = 0
        self._weights: list[float] = []
        self._done_weight = 0.0
        self._current_weight = 0.0

    # -- events ----------------------------------------------------------------
    def emit(self, event: dict[str, Any]) -> None:
        event.setdefault("time", round(time.time(), 3))
        if event.get("type") == "log":
            line = event["line"]
            if self._log_fh:
                self._log_fh.write(line + "\n")
                self._log_fh.flush()
            m = _PACMAN_PROGRESS.match(line.strip())
            if m and self._current_weight:
                done, total = int(m.group(1)), int(m.group(2))
                self._progress(done / max(total, 1))
        self._emit_cb(event)

    def _progress(self, fraction_of_step: float) -> None:
        total = sum(self._weights) or 1.0
        value = (self._done_weight + self._current_weight * min(max(fraction_of_step, 0.0), 1.0)) / total
        self._emit_cb({"type": "progress", "value": round(value, 4)})

    # -- run -------------------------------------------------------------------
    def run(self) -> bool:
        inst = self.inst
        inst.emit = self.emit
        inst.runner.log = lambda line: self.emit({"type": "log", "line": line})
        if self.log_file is not None:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_fh = self.log_file.open("a", encoding="utf-8")
            self.log_file.chmod(0o600)
            self._log_fh.write(f"\n==== installation started {time.ctime()} ====\n")
            self._log_fh.write(inst.cfg.to_json(redact=True) + "\n")
        steps = inst.steps()
        self._weights = [s.weight for s in steps]
        self.emit({"type": "plan", "steps": [{"id": s.id, "label": s.label, "critical": s.critical} for s in steps]})
        ok = True
        for i, step in enumerate(steps):
            self._step_index = i
            self._current_weight = step.weight
            self.emit({"type": "step", "id": step.id, "label": step.label, "index": i, "total": len(steps)})
            self._progress(0)
            started = time.time()
            try:
                step.func()
            except Exception as exc:  # noqa: BLE001
                detail = str(exc) or exc.__class__.__name__
                self.emit({"type": "log", "line": "".join(traceback.format_exception(exc)).rstrip()})
                if step.critical:
                    self.failed_step, self.error = step.id, detail
                    self.emit({"type": "error", "step": step.id, "label": step.label, "message": detail})
                    ok = False
                    break
                inst.warnings.append(f"{step.label}: {detail}")
                self.emit({"type": "warning", "step": step.id, "message": detail})
            self.emit({"type": "step-done", "id": step.id, "seconds": round(time.time() - started, 1)})
            self._done_weight += step.weight
            self._current_weight = 0.0
            self._progress(0)
        try:
            if ok and self.log_file is not None:
                inst.install_log_copy(self.log_file)
            inst.cleanup(failed=not ok)
        except Exception as exc:  # noqa: BLE001
            self.emit({"type": "warning", "step": "cleanup", "message": str(exc)})
        if ok:
            self.emit({"type": "done", "warnings": inst.warnings})
        if self._log_fh:
            self._log_fh.write(f"==== installation {'finished' if ok else 'FAILED'} {time.ctime()} ====\n")
            self._log_fh.close()
        return ok


def json_lines(stream=sys.stdout) -> Event:
    def emit(event: dict[str, Any]) -> None:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()

    return emit


def human(stream=sys.stdout, style: util.Style | None = None, verbose: bool = True) -> Event:
    style = style or util.style

    def emit(event: dict[str, Any]) -> None:
        t = event.get("type")
        if t == "step":
            stream.write(style.header(f"[{event['index'] + 1}/{event['total']}] {event['label']}") + "\n")
        elif t == "log" and verbose:
            stream.write("    " + event["line"] + "\n")
        elif t == "warning":
            stream.write(style.warn(event["message"]) + "\n")
        elif t == "error":
            stream.write(style.fail(f"{event['label']}: {event['message']}") + "\n")
        elif t == "done":
            stream.write(style.ok("Installation complete.") + "\n")
            for w in event.get("warnings", []):
                stream.write(style.warn(w) + "\n")
        stream.flush()

    return emit


__all__ = ["Engine", "InstallError", "json_lines", "human"]
