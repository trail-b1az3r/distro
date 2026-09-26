"""The graphical installer's backend, exposed to QML as ``installer``.

The UI runs as the unprivileged live user. When the user confirms, the
installation runs in ``<id>-installer --engine`` under sudo, which reports
progress as JSON lines. In demo mode (``--demo``) the same engine runs
in-process as a dry run, so the whole flow can be tried (and tested) without
touching a disk.
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import threading
import time
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from .. import hardware, paths, surface, util
from ..ai import backends, models
from ..branding import load as load_branding
from ..gpu.plan import build_plan, stack as gpu_stack, stacks_for_vendor
from ..installer import config as cfgmod
from ..installer import disks as diskmod
from ..installer import localization
from ..installer.engine import Engine
from ..installer.steps import Installation, dry_run_commands, is_online, summary
from ..profiles import default_profile, load_features, load_profiles
from . import common

PAGES = ["welcome", "language", "keyboard", "network", "hardware", "disk", "profile", "desktop", "gpu", "kernel",
         "ai", "model", "user", "summary", "install", "done"]
FIELD_PAGE = {
    "locale": "language", "timezone": "language", "keyboard_layout": "keyboard", "keyboard_variant": "keyboard",
    "disk": "disk", "bootloader": "disk", "secure_boot": "disk", "profile": "profile", "features": "profile",
    "kernels": "kernel", "user": "user", "hostname": "user", "ai": "model",
}

LANGUAGES = {
    "en": "English", "de": "Deutsch", "fr": "Français", "es": "Español", "it": "Italiano", "pt": "Português",
    "nl": "Nederlands", "sv": "Svenska", "nb": "Norsk bokmål", "da": "Dansk", "fi": "Suomi", "pl": "Polski",
    "cs": "Čeština", "sk": "Slovenčina", "hu": "Magyar", "ro": "Română", "el": "Ελληνικά", "tr": "Türkçe",
    "ru": "Русский", "uk": "Українська", "bg": "Български", "sr": "Српски", "hr": "Hrvatski", "sl": "Slovenščina",
    "et": "Eesti", "lv": "Latviešu", "lt": "Lietuvių", "ja": "日本語", "ko": "한국어", "zh": "中文", "hi": "हिन्दी",
    "ar": "العربية", "he": "עברית", "fa": "فارسی", "th": "ไทย", "vi": "Tiếng Việt", "id": "Bahasa Indonesia",
    "ms": "Bahasa Melayu", "ca": "Català", "eu": "Euskara", "gl": "Galego", "ga": "Gaeilge", "is": "Íslenska",
}


def locale_label(code: str) -> str:
    lang, _, rest = code.partition("_")
    country = rest.split(".")[0].split("@")[0]
    name = LANGUAGES.get(lang, lang)
    return f"{name} ({country}) — {code}" if country else f"{name} — {code}"


def _current_timezone() -> str:
    try:
        target = os.readlink("/etc/localtime")
        return target.split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return "UTC"


def _set_path(d: dict, path: str, value: Any) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


class EngineThread(threading.Thread):
    """Runs the installation and forwards events to the backend."""

    def __init__(self, backend: "InstallerBackend", payload: dict, demo: bool):
        super().__init__(daemon=True)
        self.backend = backend
        self.payload = payload
        self.demo = demo

    def run(self) -> None:
        if self.demo:
            self._run_demo()
            return
        b = self.backend.branding
        exe = f"/usr/bin/{b.id}-installer"
        cmd = [exe, "--engine"] if os.path.exists(exe) else [sys.executable, "-m", "distrokit.installer.main", "--engine"]
        if os.geteuid() != 0:
            cmd = (["sudo", "-n"] if util.which("sudo") else ["pkexec"]) + cmd
        env = os.environ.copy()
        env["PYTHONPATH"] = str(paths.CODE_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1, env=env)
        except OSError as exc:
            self.backend.engineEvent.emit({"type": "error", "step": "start", "label": "Start", "message": str(exc)})
            return
        assert proc.stdin and proc.stdout
        proc.stdin.write(json.dumps(self.payload))
        proc.stdin.close()
        for line in proc.stdout:
            line = line.rstrip("\n")
            try:
                event = json.loads(line)
            except ValueError:
                event = {"type": "log", "line": line}
            self.backend.engineEvent.emit(event)
        rc = proc.wait()
        if rc != 0:
            self.backend.engineEvent.emit({"type": "exit", "code": rc})

    def _run_demo(self) -> None:
        backend = self.backend

        def emit(event: dict) -> None:
            backend.engineEvent.emit(event)
            if event.get("type") == "step":
                time.sleep(backend.demo_step_delay)

        cfg = cfgmod.InstallConfig.from_dict(self.payload["config"])
        inst = Installation(cfg, backend.report, runner=util.Runner(dry_run=True), online=self.payload.get("online", True))
        Engine(inst, emit).run()


class InstallerBackend(QObject):
    configChanged = Signal()
    disksChanged = Signal()
    onlineChanged = Signal()
    summaryChanged = Signal()
    busyChanged = Signal()
    aiChanged = Signal()
    engineEvent = Signal("QVariant")
    hfResult = Signal("QVariant")
    message = Signal(str)

    def __init__(self, demo: bool = False, hardware_root: str = "/"):
        super().__init__()
        self.branding = load_branding()
        self.demo = demo
        self.demo_step_delay = 0.35
        self.hardware_root = hardware_root
        self.report = hardware.detect(hardware_root, live_label_prefix=self.branding["ISO_LABEL_PREFIX"])
        self._profiles = load_profiles()
        self._feature_defs = load_features()
        self._catalog = models.load_catalog()
        self._online = False if demo else is_online()
        self._busy = False
        self._summary: dict[str, Any] = {}
        self._commands: list[str] = []
        self._surface = surface.detect(self.report)
        self._cfg = self._defaults()
        self._refresh_derived()
        self._history: list[dict] = []
        self.engineEvent.connect(self._on_engine_event)
        self._installing = False

    # -- defaults -----------------------------------------------------------
    def _defaults(self) -> dict[str, Any]:
        cfg = cfgmod.InstallConfig()
        lang = os.environ.get("LANG", "en_US.UTF-8")
        cfg.locale = lang if lang.endswith(".UTF-8") else "en_US.UTF-8"
        cfg.timezone = _current_timezone()
        cfg.profile = default_profile(self._profiles).id
        cfg.surface_kernel = self._surface.recommended
        vendor = re.sub(r"[^a-z0-9]", "", (self.report.chassis.sys_vendor or "").lower())[:10]
        cfg.hostname = f"{self.branding.id}-{vendor}" if vendor else self.branding.id
        disks = self.report.installable_disks
        if disks:
            disk = max(disks, key=lambda d: (d.transport == "nvme", d.size_bytes))
            cfg.disk.disk = disk.path
            cfg.disk.disk_size_bytes = disk.size_bytes
            largest = max((r.size_bytes for r in disk.free_regions()), default=0)
            if disk.existing_systems and largest >= 40 * 2**30:
                cfg.disk.mode = "free-space"
        cfg.bootloader = "auto"
        return cfg.to_dict()

    # -- properties ---------------------------------------------------------
    @Property("QVariant", notify=configChanged)
    def config(self) -> dict:
        return self._cfg

    @Property("QVariant", constant=True)
    def pages(self) -> list:
        return PAGES

    @Property(bool, constant=True)
    def isDemo(self) -> bool:  # noqa: N802
        return self.demo

    @Property(bool, notify=onlineChanged)
    def online(self) -> bool:
        return self._online

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property("QVariant", constant=True)
    def hardware(self) -> dict:
        r = self.report
        icon_for = {"System": "laptop" if r.chassis.portable else "desktop", "Type": "info", "CPU": "cpu", "RAM": "memory",
                    "Storage": "storage", "Display": "display", "Wi-Fi": "wifi", "Bluetooth": "bluetooth",
                    "Input": "touch", "Firmware": "shield", "Surface": "tablet"}
        rows = [{"label": k, "value": v, "icon": icon_for.get(k.split(" ")[0], "gpu" if k.startswith("GPU") else "info")}
                for k, v in r.summary_rows()]
        plan = build_plan(r, branding=self.branding)
        recs = [c.to_dict()["label"] for c in plan.choices]
        if any(g.vendor in ("nvidia", "amd", "intel") for g in r.gpus):
            recs += ["Wayland", "Hardware acceleration"]
        if plan.mode == "hybrid":
            recs.append("Hybrid graphics (PRIME render offload)")
        if r.chassis.surface:
            recs.append("Surface Linux kernel")
        if r.virt.is_virtual:
            recs.append(f"Guest tools for {r.virt.kind}")
        if any(d.hidpi for d in r.displays):
            recs.append("HiDPI scaling")
        return {
            "rows": rows,
            "recommendations": recs,
            "portable": r.chassis.portable,
            "virtual": r.virt.is_virtual,
            "uefi": r.firmware.uefi,
            "secureBoot": r.firmware.secure_boot,
            "setupMode": r.firmware.setup_mode,
            "touch": r.has_touchscreen,
            "displays": [d.to_dict() for d in r.displays],
            "ramGb": r.memory.marketing_gb(),
        }

    @Property("QVariant", notify=disksChanged)
    def disks(self) -> list:
        out = []
        for d in self.report.disks:
            dd = d.to_dict()
            dd["label"] = f"{d.model or d.name} — {util.human_size_marketing(d.size_bytes)} {d.kind}"
            dd["freeText"] = util.human_bytes(dd["largest_free_bytes"]) + " unallocated" if dd["largest_free_bytes"] else "no free space"
            out.append(dd)
        return out

    @Property("QVariant", constant=True)
    def profiles(self) -> list:
        return [p.to_dict() for p in self._profiles.values()]

    @Property("QVariant", notify=configChanged)
    def features(self) -> list:
        prof = self._profiles.get(self._cfg["profile"])
        values = dict(prof.features if prof else {})
        values.update(self._cfg.get("features", {}))
        out = []
        for f in sorted(self._feature_defs.values(), key=lambda f: (f.group, f.order)):
            if f.id == "snapshots" and self._cfg["disk"]["filesystem"] != "btrfs":
                continue
            out.append({"id": f.id, "kind": f.kind, "group": f.group, "label": f.label, "description": f.description,
                        "choices": list(f.choices), "value": values.get(f.id), "network": f.requires_network,
                        "overridden": f.id in self._cfg.get("features", {})})
        return out

    @Property("QVariant", notify=configChanged)
    def gpuCards(self) -> list:  # noqa: N802
        plan = self._gpu_plan
        cards = []
        for c in plan.choices:
            g = self.report.gpu(c.slot)
            assert g is not None
            options = [{"id": s, "label": gpu_stack(s)["label"]} for s in stacks_for_vendor(g.vendor)]
            vram = (f"{g.vram_gib:g} GB" + (" (estimated)" if g.vram_source == "estimate" else "")) if g.vram_bytes else \
                ("Shared memory" if g.kind == "integrated" else "")
            cards.append({"slot": c.slot, "name": c.display_name, "vendor": g.vendor, "kind": g.kind, "role": c.role,
                          "architecture": g.architecture, "vram": vram, "stack": c.stack, "recommended": c.recommended,
                          "recommendedLabel": gpu_stack(c.recommended)["label"], "reason": c.reason, "options": options,
                          "vulkan": gpu_stack(c.stack).get("vulkan", ""), "cuda": gpu_stack(c.stack).get("cuda", ""),
                          "wayland": gpu_stack(c.stack).get("wayland", "")})
        return cards

    @Property("QVariant", notify=configChanged)
    def gpuInfo(self) -> dict:  # noqa: N802
        p = self._gpu_plan
        return {"mode": p.mode, "notes": p.notes, "packages": p.all_packages, "backend": self._backend.description,
                "computePackages": p.compute_packages}

    @Property("QVariant", constant=True)
    def surfaceInfo(self) -> dict:  # noqa: N802
        return self._surface.to_dict()

    @Property("QVariant", notify=aiChanged)
    def ai(self) -> dict:
        rec = self._recommendation
        cats = []
        for cid, meta in self._catalog.categories.items():
            suggested = rec.defaults.get(cid)
            fit = next((f for f in rec.fits if f.model.id == suggested), None)
            cats.append({"id": cid, "label": meta["label"], "description": meta["description"],
                         "suggested": fit.to_dict() if fit else None})
        free = 0
        disk = next((d for d in self.report.disks if d.path == self._cfg["disk"]["disk"]), None)
        if disk is not None:
            free = disk.size_bytes if self._cfg["disk"]["mode"] == "erase" else max((r.size_bytes for r in disk.free_regions()), default=0)
        return {
            "headline": rec.headline,
            "lines": rec.lines,
            "lowMemory": rec.low_memory,
            "categories": cats,
            "catalog": [f.to_dict() for f in rec.fits],
            "backend": self._backend.to_dict(),
            "targetBytes": free,
        }

    @Property("QVariant", constant=True)
    def locales(self) -> list:
        return [{"value": c, "label": locale_label(c)} for c in localization.locales()]

    @Property("QVariant", constant=True)
    def timezones(self) -> list:
        return localization.timezones()

    @Property("QVariant", constant=True)
    def layouts(self) -> list:
        return [{"value": lay.code, "label": f"{lay.name} ({lay.code})",
                 "variants": [{"value": v, "label": n} for v, n in lay.variants]}
                for lay in localization.keyboard_layouts()]

    @Property("QVariant", notify=summaryChanged)
    def summary(self) -> dict:
        return self._summary

    @Property("QVariant", notify=summaryChanged)
    def commands(self) -> list:
        return self._commands

    # -- derived state ------------------------------------------------------
    def _config_obj(self) -> cfgmod.InstallConfig:
        return cfgmod.InstallConfig.from_dict(copy.deepcopy(self._cfg))

    def _refresh_derived(self) -> None:
        cfg = self._config_obj()
        prof = self._profiles[cfg.profile]
        feats = dict(prof.features)
        feats.update(cfg.features)
        kernels = list(dict.fromkeys(cfg.kernels + (["linux-surface"] if cfg.surface_kernel else [])))
        self._gpu_plan = build_plan(self.report, kernels=kernels, compute=bool(feats.get("gpu_compute")),
                                    multilib=cfg.multilib, overrides=cfg.gpu_overrides, branding=self.branding)
        self._backend = backends.select(self.report, self._gpu_plan, cfg.ai.backend)
        self._recommendation = models.recommend(self.report, "cuda" if self._backend.name == "cuda_legacy" else self._backend.name,
                                                self._catalog)

    def _changed(self, ai: bool = False) -> None:
        self._refresh_derived()
        self.configChanged.emit()
        if ai:
            self.aiChanged.emit()

    # -- editing ------------------------------------------------------------
    @Slot(str, "QVariant")
    def set(self, path: str, value: Any) -> None:
        if hasattr(value, "toVariant"):
            value = value.toVariant()
        old_user = self._cfg["user"]["username"]
        _set_path(self._cfg, path, value)
        if path == "profile":
            self._cfg["features"] = {}
            prof = self._profiles.get(value)
            if prof and prof.features.get("hypernix") and not self._cfg["ai"]["model"]:
                self._cfg["ai"]["model"] = self._recommendation.defaults.get("general", "")
        if path == "user.fullname" and (not old_user or old_user == self._suggest_username(self._prev_fullname)):
            self._cfg["user"]["username"] = self._suggest_username(value)
        if path == "user.fullname":
            self._prev_fullname = value
        if path == "disk.disk":
            disk = next((d for d in self.report.disks if d.path == value), None)
            self._cfg["disk"]["disk_size_bytes"] = disk.size_bytes if disk else 0
        if path == "disk.swap" and value in ("zram", "none"):
            self._cfg["disk"]["hibernation"] = False
        if path == "disk.encrypt" and not value:
            self._cfg["disk"]["passphrase"] = ""
        self._changed(ai=path.startswith(("ai", "disk", "profile", "features", "gpu_overrides")))

    _prev_fullname = ""

    @staticmethod
    def _suggest_username(fullname: str) -> str:
        first = (fullname or "").strip().split(" ")[0].lower()
        first = re.sub(r"[^a-z0-9_-]", "", first)
        return first[:32] if first and first[0].isalpha() else ""

    @Slot(str, "QVariant")
    def setFeature(self, fid: str, value: Any) -> None:  # noqa: N802
        feats = dict(self._cfg.get("features", {}))
        prof = self._profiles[self._cfg["profile"]]
        if prof.features.get(fid) == value:
            feats.pop(fid, None)
        else:
            feats[fid] = value
        self._cfg["features"] = feats
        self._changed(ai=True)

    @Slot(str, str)
    def setGpuDriver(self, slot: str, stack_id: str) -> None:  # noqa: N802
        overrides = dict(self._cfg.get("gpu_overrides", {}))
        rec = next((c.recommended for c in self._gpu_plan.choices if c.slot == slot), "")
        if stack_id == rec:
            overrides.pop(slot, None)
        else:
            overrides[slot] = stack_id
        self._cfg["gpu_overrides"] = overrides
        self._changed(ai=True)

    @Slot(str, bool)
    def setKernel(self, kernel: str, enabled: bool) -> None:  # noqa: N802
        ks = [k for k in self._cfg["kernels"] if k != kernel]
        if enabled:
            ks.append(kernel)
        if "linux" not in ks:
            ks.insert(0, "linux")
        self._cfg["kernels"] = ks
        self._changed()

    @Slot(str, str, bool)
    def setMount(self, device: str, mountpoint: str, fmt: bool) -> None:  # noqa: N802
        mounts = [m for m in self._cfg["disk"].get("mounts", []) if m["device"] != device]
        if mountpoint:
            fs = "vfat" if mountpoint in ("/boot", "/efi") else ("swap" if mountpoint == "swap" else self._cfg["disk"]["filesystem"])
            mounts.append({"device": device, "mountpoint": mountpoint, "format": fmt, "filesystem": fs,
                           "encrypt": False})
        self._cfg["disk"]["mounts"] = mounts
        self._changed()

    # -- validation ---------------------------------------------------------
    @Slot(str, result="QVariant")
    def validate(self, page: str) -> list:
        try:
            cfg = self._config_obj()
        except (ValueError, TypeError) as exc:
            return [{"field": "", "message": str(exc), "severity": "error"}]
        issues = cfgmod.validate(cfg, uefi=self.report.firmware.uefi, profiles=set(self._profiles),
                                 features=self._feature_defs,
                                 disks={d.path: d.size_bytes for d in self.report.installable_disks},
                                 check_system=True)
        out = []
        for i in issues:
            top = i.field.split(".")[0]
            if page == "all" or FIELD_PAGE.get(top) == page:
                out.append({"field": i.field, "message": i.message, "severity": i.severity})
        if page in ("disk", "all"):
            try:
                diskmod.plan_disks(cfg, next((d for d in self.report.disks if d.path == cfg.disk.disk), None),
                                   uefi=self.report.firmware.uefi, ram_bytes=self.report.memory.total_bytes,
                                   all_disks=self.report.disks)
            except diskmod.DiskPlanError as exc:
                out.append({"field": "disk", "message": str(exc), "severity": "error"})
        return out

    # -- actions ------------------------------------------------------------
    @Slot()
    def checkNetwork(self) -> None:  # noqa: N802
        def done(result: bool) -> None:
            self._online = bool(result) and not self.demo
            self.onlineChanged.emit()

        common.run_async(is_online, done)

    @Slot()
    def openNetworkSettings(self) -> None:  # noqa: N802
        for cmd in (["nm-connection-editor"], ["kcmshell6", "kcm_networkmanagement"], ["konsole", "-e", "nmtui"]):
            if util.which(cmd[0]):
                subprocess.Popen(cmd, start_new_session=True)
                return
        self.message.emit("No network settings tool is available; use the network icon in the panel.")

    @Slot()
    def openPartitionEditor(self) -> None:  # noqa: N802
        for cmd in (["partitionmanager"], ["gparted"]):
            if util.which(cmd[0]):
                subprocess.Popen(["sudo", "-n", *cmd] if os.geteuid() else cmd, start_new_session=True)
                return
        self.message.emit("No partition editor is installed on this medium.")

    @Slot()
    def rescanDisks(self) -> None:  # noqa: N802
        self.report = hardware.detect(self.hardware_root, live_label_prefix=self.branding["ISO_LABEL_PREFIX"])
        self.disksChanged.emit()
        self._changed(ai=True)

    @Slot(str, str)
    def hfLookup(self, repo: str, file: str) -> None:  # noqa: N802
        custom = models.CustomModel(source="huggingface", repo=repo.strip(), file=file.strip())
        errors = custom.validate()
        if errors:
            self.hfResult.emit({"ok": False, "error": " ".join(errors)})
            return

        def work():
            if file.strip():
                return {"ok": True, "files": [{"file": custom.file, **{"size": models.hf_file_info(custom.repo, custom.file)["size"]}}]}
            return {"ok": True, "files": models.hf_list_gguf(custom.repo)}

        def done(result):
            for f in result.get("files", []):
                f["sizeText"] = util.human_bytes(f["size"])
            self.hfResult.emit(result)

        common.run_async(work, done, lambda e: self.hfResult.emit({"ok": False, "error": f"Could not reach Hugging Face: {e}"}))

    @Slot(result="QVariant")
    def prepareSummary(self) -> dict:  # noqa: N802
        try:
            cfg = self._config_obj()
            inst = Installation(cfg, self.report, runner=util.Runner(dry_run=True), online=self._online or self.demo)
            self._summary = summary(inst)
            self._summary["ok"] = True
            self._summary["confirmToken"] = inst.disk_plan.disk or "manual"
            self._summary["needsConfirm"] = inst.disk_plan.destructive
            self._commands = dry_run_commands(Installation(cfg, self.report, runner=util.Runner(dry_run=True),
                                                           online=self._online or self.demo))
        except (diskmod.DiskPlanError, ValueError, KeyError) as exc:
            self._summary = {"ok": False, "error": str(exc)}
            self._commands = []
        self.summaryChanged.emit()
        return self._summary

    @Slot(str, result=bool)
    def install(self, confirm: str) -> bool:
        if self._installing:
            return False
        if not self._summary.get("ok"):
            return False
        if self._summary.get("needsConfirm") and confirm != self._summary.get("confirmToken"):
            self.message.emit("The confirmation does not match; nothing was changed.")
            return False
        self._installing = True
        self._busy = True
        self.busyChanged.emit()
        payload = {"config": self._cfg, "confirm_disk": confirm, "online": self._online or self.demo}
        EngineThread(self, payload, self.demo).start()
        return True

    def _on_engine_event(self, event: dict) -> None:
        if event.get("type") != "progress":
            self._history.append(event)
        if event.get("type") in ("done", "error", "exit"):
            self._busy = False
            self._installing = False
            self.busyChanged.emit()

    @Slot(result="QVariant")
    def history(self) -> list:
        """Engine events so far, for pages created after the install started."""
        return self._history

    @Slot()
    def reboot(self) -> None:
        if self.demo:
            self.message.emit("Demo mode: not rebooting.")
            return
        subprocess.Popen(["systemctl", "reboot"])

    @Slot(result=str)
    def configJson(self) -> str:  # noqa: N802
        return self._config_obj().to_json(redact=True)


def main(demo: bool = False, hardware_root: str = "/") -> int:
    b = load_branding()
    app = common.make_app("installer", f"Install {b.name}")
    backend = InstallerBackend(demo=demo, hardware_root=hardware_root)
    engine, _warnings = common.load_qml(app, paths.qml_dir() / "installer" / "Main.qml",
                                        {"installer": backend, "launcher": common.Launcher(),
                                         "iconDir": str(common.icon_dir())})
    if not engine.rootObjects():
        return 1
    QTimer.singleShot(0, backend.checkNetwork)
    return app.exec()
