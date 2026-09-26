"""Per-user setup tasks that need the network: AI tools, HyperNix, model
downloads and the desktop shell's Python environment.

The installer queues them for the new user and runs them straight away when
the machine is online. Anything that could not finish (offline install, a
download that failed, a service that was down) stays in the queue, and the
first-boot wizard or ``<cli> setup resume`` runs it later. A failed task never
blocks the installation or the desktop.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import paths, util
from .ai import models, tools
from .ai.tools import UserContext
from .branding import Branding


@dataclass
class Task:
    id: str
    kind: str  # tool | hypernix | model | custom_model | desktop_venv
    label: str
    params: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending | running | done | failed | skipped
    error: str = ""
    size_bytes: int = 0
    updated: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TaskQueue:
    def __init__(self, branding: Branding, home: Path, root: Path | str = "/"):
        self.branding = branding
        self.home = Path(home)
        self.root = Path(root)
        self.path = paths.user_state_dir(branding.id, self.home) / "setup-tasks.json"

    def _host(self) -> Path:
        return self.root / str(self.path).lstrip("/") if str(self.root) != "/" else self.path

    def load(self) -> list[Task]:
        raw = util.read_json(self._host(), []) or []
        return [Task(**t) for t in raw]

    def save(self, tasks: list[Task]) -> None:
        util.write_json(self._host(), [t.to_dict() for t in tasks])

    def add(self, task: Task) -> None:
        tasks = [t for t in self.load() if t.id != task.id]
        tasks.append(task)
        self.save(tasks)

    def pending(self) -> list[Task]:
        return [t for t in self.load() if t.status in ("pending", "failed", "running")]

    def skip(self, task_id: str) -> None:
        tasks = self.load()
        for t in tasks:
            if t.id == task_id:
                t.status = "skipped"
        self.save(tasks)

    def run(self, ctx: UserContext, log: Callable[[str], None] | None = None,
            progress: Callable[[str, int, int], None] | None = None, only: list[str] | None = None) -> list[Task]:
        """Run pending tasks in order. Returns the tasks that failed."""
        log = log or (lambda _m: None)
        tasks = self.load()
        failed = []
        for task in tasks:
            if task.status not in ("pending", "failed", "running") or (only and task.id not in only):
                continue
            task.status, task.error, task.updated = "running", "", int(time.time())
            self.save(tasks)
            log(f"▶ {task.label}")
            try:
                execute(task, ctx, lambda done, total, t=task: progress and progress(t.id, done, total))
                task.status = "done"
                log(f"✓ {task.label}")
            except Exception as exc:  # noqa: BLE001 - a task must never take the rest down
                task.status = "failed"
                task.error = str(exc).strip().splitlines()[-1] if str(exc).strip() else exc.__class__.__name__
                log(f"✗ {task.label}: {task.error}")
                log("".join(traceback.format_exception_only(exc)).strip())
                failed.append(task)
            task.updated = int(time.time())
            self.save(tasks)
        return failed


def execute(task: Task, ctx: UserContext, progress: Callable[[int, int], None]) -> None:
    p = task.params
    if task.kind == "tool":
        tools.install_tool(tools.load_spec(p["tool"]), ctx)
    elif task.kind == "hypernix":
        tools.install_hypernix(ctx, p["torch_index"], p.get("env", {}))
    elif task.kind == "model":
        catalog = models.load_catalog()
        model = catalog.get(p["model"])
        if model is None:
            raise KeyError(f"unknown catalogue model {p['model']}")
        reg = models.Registry(ctx.branding.id, ctx.home, ctx.root)
        if ctx.runner.dry_run:
            ctx.runner._emit(f"download {model.url} ({util.human_bytes(model.download_bytes)})")
            return
        models.install_catalog_model(model, reg, progress, make_default=p.get("default", True))
        _chown_home(ctx)
    elif task.kind == "custom_model":
        custom = models.CustomModel(**p["custom"])
        reg = models.Registry(ctx.branding.id, ctx.home, ctx.root)
        if ctx.runner.dry_run:
            ctx.runner._emit(f"install custom model {custom.id} from {custom.source}")
            return
        models.install_custom_model(custom, reg, progress, make_default=p.get("default", True))
        _chown_home(ctx)
    elif task.kind == "desktop_venv":
        venv = ctx.home / ".local" / "state" / "quickshell" / ".venv"
        req = p["requirements"]
        ctx.run(["uv", "venv", "--allow-existing", "--prompt", ".venv", "--python", p.get("python", "3.12"), str(venv)])
        ctx.run(["uv", "pip", "install", "--python", str(venv / "bin" / "python"), "-r", req])
    else:
        raise ValueError(f"unknown task kind {task.kind!r}")


def _chown_home(ctx: UserContext) -> None:
    """Downloads run in this (possibly root) process; hand the files over."""
    import os
    import pwd

    if os.getuid() != 0:
        return
    if str(ctx.root) == "/":
        pw = pwd.getpwnam(ctx.user)
        uid, gid = pw.pw_uid, pw.pw_gid
    else:
        uid, gid = _lookup_ids(ctx.root, ctx.user)
    for sub in (".local/share", ".config"):
        base = ctx.host_home / sub
        for dirpath, dirnames, filenames in os.walk(base):
            for name in [*dirnames, *filenames]:
                try:
                    os.lchown(os.path.join(dirpath, name), uid, gid)
                except OSError:
                    pass
        try:
            os.lchown(base, uid, gid)
        except OSError:
            pass


def _lookup_ids(root: Path, user: str) -> tuple[int, int]:
    for line in (root / "etc" / "passwd").read_text().splitlines():
        parts = line.split(":")
        if parts[0] == user:
            return int(parts[2]), int(parts[3])
    raise KeyError(f"user {user} not found in {root}/etc/passwd")


def queue_for_install(queue: TaskQueue, *, assistant: str, hypernix: bool, claude_code: bool,
                      backend_torch_index: str, backend_env: dict[str, str], model: str | None,
                      custom_model: dict[str, Any] | None, dots_requirements: str | None) -> list[Task]:
    """Queue the tasks an installation's choices call for."""
    added: list[Task] = []

    def add(task: Task) -> None:
        queue.add(task)
        added.append(task)

    if dots_requirements:
        add(Task("desktop-venv", "desktop_venv", "Desktop shell Python environment",
                 {"requirements": dots_requirements, "python": "3.12"}))
    if hypernix:
        add(Task("hypernix", "hypernix", "HyperNix", {"torch_index": backend_torch_index, "env": backend_env}))
    wanted = {"hermis": ["hermis"], "openclaw": ["openclaw"], "both": ["hermis", "openclaw"]}.get(assistant, [])
    for tool_id in wanted:
        spec = tools.load_spec(tool_id)
        add(Task(f"tool:{tool_id}", "tool", f"{spec.name} AI assistant", {"tool": tool_id}))
    if claude_code:
        add(Task("tool:claude-code", "tool", "Claude Code", {"tool": "claude-code"}))
    if model:
        m = models.load_catalog().get(model)
        if m is None:
            raise KeyError(f"unknown catalogue model {model}")
        add(Task(f"model:{m.id}", "model", f"Model: {m.name}", {"model": m.id, "default": True},
                 size_bytes=m.download_bytes))
    if custom_model:
        c = models.CustomModel(**custom_model)
        errors = c.validate() if c.source != "path" else []
        if errors:
            raise ValueError("; ".join(errors))
        add(Task(f"model:{c.id}", "custom_model", f"Model: {c.name or c.id}", {"custom": c.to_dict(), "default": True},
                 size_bytes=c.size_bytes))
    return added
