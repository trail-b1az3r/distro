"""The Rust store (frontline-msg-core), run as a service: one JSON request per line, one reply per line."""

from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path


class CoreError(RuntimeError):
    pass


def find_binary() -> str:
    env = os.environ.get("FRONTLINE_MSG_CORE")
    if env:
        return env
    here = Path(__file__).resolve().parent.parent / "core" / "target"
    for build in ("release", "debug"):
        candidate = here / build / "frontline-msg-core"
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("frontline-msg-core")
    if found:
        return found
    raise CoreError("frontline-msg-core is not installed")


class Core:
    def __init__(self, store: str | Path, binary: str | None = None):
        self.store = str(store)
        self.binary = binary or find_binary()
        self.lock = threading.Lock()
        self.ids = itertools.count(1)
        self.proc: subprocess.Popen | None = None

    def _start(self) -> subprocess.Popen:
        if self.proc is None or self.proc.poll() is not None:
            self.proc = subprocess.Popen([self.binary, "serve", self.store], stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        return self.proc

    def call(self, op: str, **args):
        with self.lock:
            proc = self._start()
            request = {"id": next(self.ids), "op": op, **args}
            try:
                proc.stdin.write(json.dumps(request) + "\n")
                proc.stdin.flush()
                line = proc.stdout.readline()
            except (BrokenPipeError, OSError) as error:
                self.proc = None
                raise CoreError(f"the store stopped: {error}") from None
            if not line:
                self.proc = None
                raise CoreError("the store stopped")
        reply = json.loads(line)
        if not reply.get("ok"):
            raise CoreError(reply.get("error", "failed"))
        return reply["data"]

    def close(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
