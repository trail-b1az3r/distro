"""The AI launcher and model manager (``<id>-ai``), exposed to QML as ``ai``.

    <id>-ai                 launcher (HyperNix, assistants, Claude Code, local model)
    <id>-ai --models        open on the model manager
    <id>-ai --launch <id>   start an entry directly (used by desktop entries)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from .. import hardware, paths, util
from ..ai import backends, launcher, models, runtime
from ..branding import load as load_branding
from ..gpu.plan import build_plan
from . import common


class AiBackend(QObject):
    changed = Signal()
    busyChanged = Signal()
    progress = Signal(str, float)
    log = Signal(str)
    hfResult = Signal("QVariant")

    def __init__(self, start_tab: str = "launcher", home: Path | None = None, report=None):
        super().__init__()
        self.b = load_branding()
        self.home = home or Path.home()
        self._tab = start_tab
        self._busy = False
        self.report = report or hardware.detect()
        plan = build_plan(self.report, branding=self.b)
        self.backend = backends.select(self.report, plan)
        self.catalog = models.load_catalog()
        self.rec = models.recommend(self.report, "cuda" if self.backend.name == "cuda_legacy" else self.backend.name,
                                    self.catalog)
        self.registry = models.Registry(self.b.id, self.home)

    @Property(str, constant=True)
    def startTab(self) -> str:  # noqa: N802
        return self._tab

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property("QVariant", notify=changed)
    def entries(self) -> list:
        return [e.to_dict() for e in launcher.entries(self.home, self.b)]

    @Property("QVariant", constant=True)
    def recommendation(self) -> dict:
        d = self.rec.to_dict()
        d["backend"] = self.backend.to_dict()
        return d

    @Property("QVariant", constant=True)
    def categories(self) -> list:
        return [{"id": k, **v} for k, v in self.catalog.categories.items()]

    @Property("QVariant", notify=changed)
    def installed(self) -> dict:
        return self.registry.load()

    @Property(bool, notify=changed)
    def serverRunning(self) -> bool:  # noqa: N802
        return runtime.is_running(0.3)

    @Property(str, constant=True)
    def endpoint(self) -> str:
        return runtime.endpoint()

    def _set_busy(self, v: bool) -> None:
        self._busy = v
        self.busyChanged.emit()

    @Slot(str, str)
    def launch(self, entry_id: str, action: str) -> None:
        try:
            launcher.launch(entry_id, action or "run")
        except Exception as exc:  # noqa: BLE001
            self.log.emit(f"Could not start {entry_id}: {exc}")

    @Slot(str)
    def installModel(self, model_id: str) -> None:  # noqa: N802
        model = self.catalog.get(model_id)
        if model is None or self._busy:
            return
        self._set_busy(True)

        def work():
            return models.install_catalog_model(
                model, self.registry,
                lambda done, total: self.progress.emit(model_id, done / total if total else 0.0),
            )

        def done(_path):
            self._set_busy(False)
            self.log.emit(f"{model.name} installed.")
            self.changed.emit()

        common.run_async(work, done, lambda e: (self._set_busy(False), self.log.emit(f"Download failed: {e}")))

    @Slot("QVariant")
    def addCustom(self, data) -> None:  # noqa: N802
        if hasattr(data, "toVariant"):
            data = data.toVariant()
        custom = models.CustomModel(**{k: v for k, v in dict(data).items() if k in models.CustomModel.__dataclass_fields__})
        errors = custom.validate()
        if errors:
            self.log.emit(" ".join(errors))
            return
        self._set_busy(True)

        def work():
            return models.install_custom_model(custom, self.registry,
                                               lambda d, t: self.progress.emit(custom.id, d / t if t else 0.0))

        def done(_):
            self._set_busy(False)
            self.log.emit(f"Added {custom.id}.")
            self.changed.emit()

        common.run_async(work, done, lambda e: (self._set_busy(False), self.log.emit(f"Failed: {e}")))

    @Slot(str, str)
    def hfLookup(self, repo: str, file: str) -> None:  # noqa: N802
        def work():
            if file:
                return {"ok": True, "files": [{"file": file, "size": models.hf_file_info(repo, file)["size"]}]}
            return {"ok": True, "files": models.hf_list_gguf(repo)}

        def done(r):
            for f in r["files"]:
                f["sizeText"] = util.human_bytes(f["size"])
            self.hfResult.emit(r)

        common.run_async(work, done, lambda e: self.hfResult.emit({"ok": False, "error": str(e)}))

    @Slot(str)
    def setDefault(self, model_id: str) -> None:  # noqa: N802
        self.registry.set_default(model_id)
        self.changed.emit()

    @Slot(str)
    def removeModel(self, model_id: str) -> None:  # noqa: N802
        entry = self.registry.remove(model_id)
        if entry and entry.get("path"):
            p = Path(entry["path"])
            if p.is_file() and self.registry.models_dir in p.parents:
                p.unlink()
            if entry.get("mmproj"):
                Path(entry["mmproj"]).unlink(missing_ok=True)
        self.changed.emit()

    @Slot(bool)
    def setServer(self, on: bool) -> None:  # noqa: N802
        res = runtime.start(self.b) if on else runtime.stop(self.b)
        if not res.ok:
            self.log.emit(res.stderr.strip() or "The model server could not be started; see `journalctl --user -u "
                          + runtime.service_name(self.b) + "`.")
        self.changed.emit()

    @Slot()
    def refresh(self) -> None:
        self.changed.emit()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--models", action="store_true")
    p.add_argument("--launch", metavar="ID")
    a = p.parse_args(argv)
    if a.launch:
        launcher.launch(a.launch)
        return 0
    b = load_branding()
    app = common.make_app("ai", "AI Assistant")
    backend = AiBackend("models" if a.models else "launcher")
    engine, _w = common.load_qml(app, paths.qml_dir() / "ai" / "Main.qml",
                                 {"ai": backend, "launcher": common.Launcher(), "iconDir": str(common.icon_dir())})
    if not engine.rootObjects():
        return 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
