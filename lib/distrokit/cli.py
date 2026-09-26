"""The distribution's command-line tool (installed as ``/usr/bin/<cli>``).

    <cli> system | hardware | gpu | surface | update | install | ai | model |
          doctor | repair | repair-gpu | reset-desktop | setup | installer | iso

Read-only commands never need root. Commands that change the system say
what they will do, ask for confirmation, and then re-run themselves through
sudo; nothing escalates silently.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import __version__, paths, util
from .branding import load as load_branding

B = load_branding()
S = util.style


def _json(data) -> None:
    print(json.dumps(data, indent=2, default=str))


def _confirm_or_exit(plan_text: str, yes: bool, question: str = "Continue?") -> None:
    print(plan_text)
    if not util.confirm(question, default=False, assume_yes=yes):
        print("Nothing was changed.")
        raise SystemExit(1)


def _need_root(reason: str) -> None:
    util.escalate(reason)


# ---------------------------------------------------------------------------
# system / hardware
# ---------------------------------------------------------------------------


def cmd_system(a) -> int:
    from .system import info

    rows = info.gather(B)
    if a.json:
        _json(dict(rows))
    else:
        print(S.header(B.pretty_name))
        print(util.table(rows))
    return 0


def cmd_hardware(a) -> int:
    from . import hardware
    from .gpu import build_plan

    report = hardware.detect(a.root, live_label_prefix=B["ISO_LABEL_PREFIX"])
    if a.json:
        print(report.to_json())
        return 0
    print(S.header("Hardware Detected"))
    print(util.table(report.summary_rows()))
    plan = build_plan(report)
    print()
    print(S.header("Recommended Configuration"))
    for c in plan.choices:
        print(S.ok(c.to_dict()["label"]))
    if any(g.vendor in ("nvidia", "amd", "intel") for g in report.gpus):
        print(S.ok("Wayland"))
        print(S.ok("Hardware acceleration"))
    if plan.mode == "hybrid":
        print(S.ok("Hybrid graphics (PRIME render offload)"))
    if report.chassis.surface:
        print(S.ok("Surface Linux kernel"))
    if report.cpu.microcode_package:
        print(S.ok(f"CPU microcode ({report.cpu.microcode_package})"))
    if report.virt.is_virtual:
        print(S.ok(f"Virtual machine guest tools ({report.virt.kind})"))
    return 0


# ---------------------------------------------------------------------------
# gpu
# ---------------------------------------------------------------------------


def _parse_overrides(values: list[str]) -> dict[str, str]:
    out = {}
    for v in values or []:
        if "=" not in v:
            raise SystemExit(f"--driver expects SLOT=STACK, e.g. 0000:01:00.0=nouveau (got {v!r})")
        slot, stack = v.split("=", 1)
        out[slot] = stack
    return out


def cmd_gpu(a) -> int:
    from . import boot, hardware
    from .gpu import apply as gpu_apply
    from .gpu import status as gpu_status
    from .gpu.plan import build_plan

    root = Path(a.root)
    report = hardware.detect(root if str(root) != "/" else "/")
    if a.action == "status":
        statuses = gpu_status.gather(report, root, B)
        print(gpu_status.to_json(statuses) if a.json else gpu_status.render(statuses))
        return 0 if all(s.status == "Configured" for s in statuses) else 1
    state = gpu_apply.load_state(root, B) or {}
    previous = {c["slot"]: c["stack"] for c in state.get("plan", {}).get("choices", [])}
    overrides = {s: st for s, st in previous.items() if report.gpu(s)}
    if a.recommended:
        overrides = {}
    overrides.update(_parse_overrides(a.driver))
    kernels = [k.pkgbase for k in boot.installed_kernels(root)] or ["linux"]
    compute = a.compute if a.compute is not None else bool(state.get("plan", {}).get("compute_packages"))
    plan = build_plan(report, kernels=kernels, compute=compute, overrides=overrides, branding=B)
    if a.action in ("detect", "plan"):
        if a.json:
            _json({"gpus": [g.to_dict() for g in report.gpus], "topology": report.topology.to_dict(), "plan": plan.to_dict()})
            return 0
        print(S.header("GPU Detection"))
        for g in report.gpus:
            vram = f"{g.vram_gib:g} GB" + (" (estimated)" if g.vram_source == "estimate" else "") if g.vram_bytes else \
                ("shared" if g.kind == "integrated" else "unknown")
            print(util.table([("Vendor", g.vendor_name if g.vendor not in ("nvidia", "amd", "intel") else
                                {"nvidia": "NVIDIA", "amd": "AMD", "intel": "Intel"}[g.vendor]),
                              ("Model", g.model), ("Type", g.kind), ("Architecture", g.architecture),
                              ("VRAM", vram), ("PCI", f"{g.slot} [{g.pci_id}]"),
                              ("Driver now", g.driver_in_use or "none")]))
            print()
        print(S.header(f"Plan ({plan.mode})"))
        for line in plan.describe():
            print(S.info(line))
        print(util.table([("Install", " ".join(plan.all_packages) or "-"),
                          ("Kernel parameters", " ".join(plan.kernel_params) or "-"),
                          ("Environment", " ".join(f"{k}={v}" for k, v in plan.env.items()) or "-")]))
        return 0
    # configure
    installed = set()
    from . import pkg

    installed = set(pkg.installed_packages(root))
    add = [p for p in plan.all_packages if p not in installed]
    remove = [p for p in plan.conflicts if p in installed]
    text = [S.header("The GPU manager will:")] + [f"  • {line}" for line in plan.describe()]
    text.append(f"  • install: {', '.join(add) if add else 'nothing new'}")
    if remove:
        text.append(f"  • remove: {', '.join(remove)}")
    text.append(f"  • write /etc/modprobe.d, /etc/mkinitcpio.conf.d and /etc/{B.id}/gpu.env, rebuild the initramfs and boot entries")
    _confirm_or_exit("\n".join(text), a.yes)
    _need_root("configure graphics drivers")
    runner = util.Runner(log=print)
    result = gpu_apply.apply(plan, root=root, runner=runner, branding=B, user=os.environ.get("SUDO_USER"))
    print(S.ok("Graphics configured." + (" Reboot to load the new driver." if result["installed"] or result["removed"] else "")))
    return 0


# ---------------------------------------------------------------------------
# surface
# ---------------------------------------------------------------------------


def cmd_surface(a) -> int:
    from . import hardware, surface

    report = hardware.detect()
    info = surface.detect(report)
    state = util.read_json(B.system_paths().state / "surface.json", {}) or {}
    if a.action == "status":
        print(util.table([("Surface hardware", "yes" if info.detected else "no"),
                          ("Model", info.model or "-"),
                          ("Surface kernel", "enabled" if state.get("enabled") else "not installed")]))
        print(info.message)
        return 0
    if a.action == "enable":
        sp = surface.plan(info, True, secure_boot_mok=bool(a.secure_boot))
        _confirm_or_exit(S.header("Enable Surface support:") + "\n" + "\n".join(
            [f"  • add the linux-surface repository (key {surface.config()['repository']['key_fingerprint']})",
             f"  • install {', '.join(sp.packages)}", "  • make linux-surface the default boot entry"] +
            [f"  note: {n}" for n in sp.notes]), a.yes)
        _need_root("install the Surface kernel")
        surface.apply(sp, runner=util.Runner(log=print), branding=B)
        print(S.ok("Surface kernel installed. Reboot to use it."))
        return 0
    _confirm_or_exit("Remove the Surface kernel and its packages; the standard kernel becomes the default.", a.yes)
    _need_root("remove the Surface kernel")
    removed = surface.disable(runner=util.Runner(log=print), branding=B)
    print(S.ok(f"Removed: {', '.join(removed) or 'nothing'}"))
    return 0


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def cmd_update(a) -> int:
    from .system import update

    if a.desktop_only:
        for line in update.apply_desktop(B, log=lambda m: None):
            print(S.ok(line))
        return 0
    wanted = [s for s in ("packages", "aur", "flatpak", "desktop", "gpu", "ai")
              if not getattr(a, f"no_{s}", False)]
    print(S.header("Checking for updates…"))
    news = update.arch_news(update.last_update_time())
    sources = update.check_all(B, wanted)
    total = 0
    for src in sources:
        if not src.available:
            if src.error:
                print(S.dim(f"  {src.label}: {src.error}"))
            continue
        if src.error:
            print(S.warn(f"{src.label}: {src.error}"))
            continue
        mark = S.ok if not src.count else S.info
        print(mark(f"{src.label}: {src.count or 'up to date'}"))
        if a.verbose or src.id not in ("packages", "aur"):
            for it in src.items[:30]:
                print(S.dim(f"    {it.name} {it.current} -> {it.new}".rstrip()))
        total += src.count
    if news:
        print()
        print(S.warn("Arch Linux news since your last update (read before updating):"))
        for n in news:
            print(f"    {n.title}\n      {n.link}")
    if a.check:
        return 100 if total else 0
    if not total:
        print(S.ok("Everything is up to date."))
        return 0
    runner = util.Runner(log=print)
    by_id = {s.id: s for s in sources}
    if by_id.get("packages") and by_id["packages"].count:
        print(S.header("Updating system packages: sudo pacman -Syu"))
        update.apply_packages(runner, interactive=not a.yes)
    if by_id.get("aur") and by_id["aur"].count:
        print(S.header("Updating AUR packages: yay -Sua"))
        update.apply_aur(runner, interactive=not a.yes)
    if by_id.get("flatpak") and by_id["flatpak"].count:
        update.apply_flatpak(runner)
    if by_id.get("desktop") and by_id["desktop"].count:
        for line in update.apply_desktop(B):
            print(S.ok(line))
    if by_id.get("ai") and by_id["ai"].count:
        print(S.ok("Updated: " + ", ".join(update.apply_ai(runner, B))))
    if by_id.get("gpu") and by_id["gpu"].count:
        print(S.warn(f"Graphics configuration changed; run `sudo {B.cli} gpu configure` to review and apply."))
    print(S.ok("Update complete."))
    return 0


# ---------------------------------------------------------------------------
# install (features and tools by name)
# ---------------------------------------------------------------------------

FEATURE_ALIASES = {
    "apps": "apps", "browser": "browser", "office": "office", "onlyoffice": "office", "plasma": "plasma_fallback",
    "dev": "dev_basic", "devtools": "dev_basic", "compilers": "dev_full", "editor": "code_editor", "vscode": "code_editor",
    "snapshots": "snapshots", "firewall": "firewall", "podman": ("containers", "podman"), "docker": ("containers", "docker"),
}
AI_TOOLS = {"claude-code": "claude-code", "claude": "claude-code", "hermis": "hermis", "hermes": "hermis",
            "openclaw": "openclaw", "hypernix": "hypernix"}


def cmd_install(a) -> int:
    from .profiles import load_editors, load_features, read_list

    feats = load_features()
    names = a.names
    to_pacman: list[str] = []
    for name in names:
        key = name.lower()
        if key in AI_TOOLS:
            return cmd_ai(argparse.Namespace(action="install", tool=AI_TOOLS[key], backend="", yes=a.yes))
        alias = FEATURE_ALIASES.get(key)
        if alias:
            fid, value = alias if isinstance(alias, tuple) else (alias, True)
            feature = feats[fid]
            lists = feature.lists_for(value)
            for lst in lists:
                to_pacman += read_list(lst, B)
            if fid == "code_editor":
                to_pacman.append(load_editors()[B.get("CODE_EDITOR", "code")].package)
        else:
            to_pacman.append(name)
    to_pacman = list(dict.fromkeys(to_pacman))
    print(S.info("Installing with yay (repositories first, then the AUR): " + " ".join(to_pacman)))
    if os.geteuid() == 0:
        return subprocess.call(["pacman", "-S", "--needed", *to_pacman])
    if util.which("yay"):
        return subprocess.call(["yay", "-S", "--needed", *to_pacman])
    return subprocess.call(["sudo", "pacman", "-S", "--needed", *to_pacman])


# ---------------------------------------------------------------------------
# ai
# ---------------------------------------------------------------------------


def _backend():
    from . import hardware
    from .ai import backends
    from .gpu.plan import build_plan

    report = hardware.detect()
    plan = build_plan(report, branding=B)
    return report, plan, backends


def cmd_ai(a) -> int:
    from .ai import launcher, runtime, tools

    if a.action == "status":
        rows = []
        for e in launcher.entries(Path.home(), B):
            state = "installed" if e.installed else "not installed"
            if e.installed and not e.configured:
                state += ", needs setup"
            rows.append((e.name, state))
        rows.append(("Local model server", "running at " + runtime.endpoint() if runtime.is_running() else "stopped"))
        rows.append(("llama.cpp", runtime.installed_package() or "not installed"))
        print(S.header("AI"))
        print(util.table(rows))
        return 0
    if a.action == "backend":
        report, plan, backends = _backend()
        be = backends.select(report, plan)
        print(util.table([("Backend", be.description), ("GPU", be.gpu or "-"), ("PyTorch index", be.torch_index),
                          ("llama.cpp build", be.llama_package)] + [(k, v) for k, v in be.env.items()]))
        return 0
    if a.action == "launch":
        launcher.launch(a.tool)
        return 0
    if a.action == "update":
        from .system import update

        print(S.ok("Updated: " + (", ".join(update.apply_ai(util.Runner(log=print), B)) or "nothing installed")))
        return 0
    if a.action == "runtime":
        report, plan, backends = _backend()
        be = backends.select(report, plan, a.backend or "")
        package = {"cuda": "llama.cpp-cuda", "cuda_legacy": "llama.cpp-cuda", "rocm": "llama.cpp-hip"}.get(a.backend, be.llama_package) \
            if a.backend else be.llama_package
        print(S.info(f"Installing {package} (local model server, {be.description})"))
        return subprocess.call(["yay", "-S", "--needed", package] if util.which("yay") else ["sudo", "pacman", "-S", "--needed", package])
    if os.geteuid() == 0:
        print(S.fail(f"AI tools install into your home directory: run `{B.cli} ai {a.action} {a.tool}` without sudo."))
        return 1
    ctx = tools.UserContext.current(util.Runner(log=print))
    if a.tool == "hypernix":
        if a.action == "install":
            report, plan, backends = _backend()
            be = backends.select(report, plan, a.backend or "")
            print(S.info(f"Installing HyperNix with PyTorch for {be.description} ({be.torch_index})"))
            tools.install_hypernix(ctx, be.torch_index, be.env)
            _install_desktop_entry("hypernix")
            print(S.ok("HyperNix installed. Try: hypernix devices"))
        else:
            tools.remove_hypernix(ctx)
            print(S.ok("HyperNix removed."))
        return 0
    spec = tools.load_spec(a.tool)
    if a.action == "install":
        print(S.info(f"Installing {spec.name} ({spec.requirement}) for {ctx.user}"))
        try:
            tools.install_tool(spec, ctx)
        except tools.ToolError as exc:
            print(S.fail(str(exc)))
            return 1
        _install_desktop_entry(a.tool)
        print(S.ok(f"{spec.name} installed: run `{spec.commands[0]}`" + (" (first run starts its setup)" if spec.launch.get("setup") else "")))
    else:
        tools.remove_tool(spec, ctx)
        entry = Path.home() / ".local/share/applications" / f"{B.id}-{a.tool}.desktop"
        entry.unlink(missing_ok=True)
        print(S.ok(f"{spec.name} removed."))
    return 0


def _install_desktop_entry(tool_id: str) -> None:
    src = paths.data("desktop", "overlay", "applications", "user", f"{tool_id}.desktop.in")
    if src.exists():
        dest = Path.home() / ".local/share/applications" / f"{B.id}-{tool_id}.desktop"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(B.render(src.read_text()))


# ---------------------------------------------------------------------------
# model
# ---------------------------------------------------------------------------


def _progress_printer(label: str):
    last = [0.0]

    def cb(done: int, total: int) -> None:
        import time

        now = time.time()
        if now - last[0] < 0.5 and done != total:
            return
        last[0] = now
        pct = f"{done / total * 100:5.1f}%" if total else ""
        sys.stderr.write(f"\r{label}: {util.human_bytes(done)} / {util.human_bytes(total)} {pct}   ")
        if done >= total:
            sys.stderr.write("\n")

    return cb


def cmd_model(a) -> int:
    from .ai import models, runtime

    catalog = models.load_catalog()
    reg = models.Registry(B.id)
    if a.action in ("list", "recommend"):
        report, plan, backends = _backend()
        be = backends.select(report, plan)
        rec = models.recommend(report, be.name if be.name != "cuda_legacy" else "cuda", catalog)
        if a.json:
            _json({"recommendation": rec.to_dict(), "installed": reg.load()})
            return 0
        print(S.header("AI Hardware Recommendations"))
        print(rec.headline)
        print("Suggested models:")
        for line in rec.lines:
            print(f"  • {line}")
        if a.action == "recommend":
            print(S.dim("Recommendations are advice; any model can be installed."))
            return 0
        installed = reg.load()
        print()
        for cat, meta in catalog.categories.items():
            print(S.header(meta["label"]))
            for f in (f for f in rec.fits if f.model.category == cat):
                m = f.model
                tag = {"gpu": "fits GPU", "offload": "GPU+RAM", "cpu": "CPU", "too-large": "too large"}[f.placement]
                mark = "●" if m.id in installed["models"] else " "
                default = " (default)" if installed["default"] == m.id else ""
                star = " ★" if rec.defaults.get(cat) == m.id else ""
                print(f" {mark} {m.id:<30} {util.human_bytes(m.download_bytes):>9}  {tag:<9} {m.name}{star}{default}")
        print(S.dim("★ suggested for this machine   ● installed"))
        return 0
    if a.action == "installed":
        data = reg.load()
        for mid, entry in data["models"].items():
            print(f"{'*' if data['default'] == mid else ' '} {mid:<30} {entry.get('path', entry.get('source', ''))}")
        return 0
    if a.action == "info":
        m = catalog.get(a.id)
        if m is None:
            print(S.fail(f"No catalogue model {a.id!r}"))
            return 1
        _json(m.to_dict())
        return 0
    if a.action == "install":
        m = catalog.get(a.id)
        if m is None:
            print(S.fail(f"No catalogue model {a.id!r}; see `{B.cli} model list`, or add your own with `{B.cli} model add`."))
            return 1
        ok, free = models.check_space(reg.models_dir, m.download_bytes)
        print(util.table([("Model", m.name), ("Download", util.human_bytes(m.download_bytes)),
                          ("Memory (8k context)", util.human_bytes(m.memory_bytes())),
                          ("Free space", util.human_bytes(free)), ("License", m.license)]))
        if not ok:
            print(S.fail("Not enough free space."))
            return 1
        if not util.confirm("Download it?", default=True, assume_yes=a.yes):
            return 1
        models.install_catalog_model(m, reg, _progress_printer(m.id), make_default=a.default)
        print(S.ok(f"{m.name} installed" + (" and set as default" if reg.load()["default"] == m.id else "")))
        return 0
    if a.action == "add":
        source = "huggingface" if a.hf else "url" if a.url else "path" if a.path else "hypernix" if a.hypernix else ""
        custom = models.CustomModel(source=source, repo=a.hf or "", file=a.file or "", url=a.url or "",
                                    path=a.path or "", hypernix_id=a.hypernix or "", name=a.name or "", context=a.context)
        errors = custom.validate()
        if errors:
            for e in errors:
                print(S.fail(e))
            return 1
        if source == "huggingface":
            info = models.hf_file_info(custom.repo, custom.file)
            print(S.info(f"{custom.file}: {util.human_bytes(info['size'])}"))
            if not util.confirm("Download it?", default=True, assume_yes=a.yes):
                return 1
        models.install_custom_model(custom, reg, _progress_printer(custom.id), make_default=a.default)
        print(S.ok(f"Added {custom.id}"))
        return 0
    if a.action == "remove":
        entry = reg.remove(a.id)
        if not entry:
            print(S.fail(f"{a.id} is not installed"))
            return 1
        p = Path(entry.get("path", ""))
        if p.is_file() and reg.models_dir in p.parents:
            p.unlink()
            if entry.get("mmproj"):
                Path(entry["mmproj"]).unlink(missing_ok=True)
        print(S.ok(f"Removed {a.id}"))
        return 0
    if a.action == "default":
        reg.set_default(a.id)
        print(S.ok(f"Default model: {a.id}"))
        return 0
    if a.action == "serve":
        if a.foreground:
            return runtime.serve_foreground(B)
        if a.stop:
            runtime.stop(B)
            print(S.ok("Stopped."))
            return 0
        if a.status:
            print("running at " + runtime.endpoint() if runtime.is_running() else "stopped")
            return 0
        res = runtime.start(B)
        print(S.ok(f"Serving the default model at {runtime.endpoint()}") if res.ok else S.fail(res.stderr.strip()))
        return 0 if res.ok else 1
    return 2


# ---------------------------------------------------------------------------
# doctor / repair / reset
# ---------------------------------------------------------------------------


def cmd_doctor(a) -> int:
    from .system import doctor

    doc = doctor.Doctor(a.root, B)
    results = doc.run()
    if a.json:
        _json([r.to_dict() for r in results])
    else:
        print(doctor.render(results, verbose=a.verbose))
    if a.report:
        path = doctor.write_report(results, Path.cwd(), B)
        print(S.ok(f"Report written to {path}. It stays on this computer; attach it to a bug report if you wish."))
    return 1 if any(r.status == "fail" and r.critical for r in results) else 0


def cmd_repair(a) -> int:
    from .system import doctor, repair

    root = Path(a.root)
    runner = util.Runner(log=print)
    plans = []
    what = a.what or "auto"
    if what == "auto":
        results = doctor.Doctor(root, B).run()
        failing = {r.name for r in results if r.status == "fail"}
        print(doctor.render(results))
        if not failing:
            print(S.ok("Nothing to repair."))
            return 0
        if "Package manager" in failing:
            plans.append(repair.packages_plan(root, runner, refresh=True))
        if "Bootloader" in failing or "Kernel" in failing:
            plans.append(repair.boot_plan(root, runner, B))
        if {"GPU", "Vulkan", "AI backend"} & failing:
            plans.append(repair.gpu_plan(root, runner, B, user=os.environ.get("SUDO_USER")))
        if "Desktop" in failing:
            print(S.warn(f"Desktop problems: run `{B.cli} reset-desktop` as your user."))
    elif what == "packages":
        plans.append(repair.packages_plan(root, runner, refresh=not a.no_update))
    elif what == "boot":
        plans.append(repair.boot_plan(root, runner, B))
    elif what == "all":
        plans += [repair.packages_plan(root, runner), repair.boot_plan(root, runner, B),
                  repair.gpu_plan(root, runner, B, user=os.environ.get("SUDO_USER"))]
    if not plans:
        return 0
    _confirm_or_exit("\n\n".join(p.describe() for p in plans), a.yes, "Carry out these repairs?")
    _need_root("repair the system")
    errors = []
    for p in plans:
        errors += p.execute()
    if errors:
        for e in errors:
            print(S.fail(e))
        return 1
    print(S.ok("Repairs complete. Run the doctor again to confirm."))
    return 0


def cmd_repair_gpu(a) -> int:
    from .system import repair

    runner = util.Runner(log=print)
    plan = repair.gpu_plan(Path(a.root), runner, B, safe=a.safe, keep_overrides=not a.recommended,
                           user=os.environ.get("SUDO_USER"))
    _confirm_or_exit(plan.describe(), a.yes, "Apply this graphics configuration?")
    _need_root("repair graphics drivers")
    errors = plan.execute()
    if errors:
        print(S.fail("\n".join(errors)))
        return 1
    print(S.ok("Graphics drivers repaired. Reboot to load them."))
    return 0


def cmd_reset_desktop(a) -> int:
    from .system import repair

    if os.geteuid() == 0:
        print(S.fail("Run reset-desktop as the user whose desktop should be reset (without sudo)."))
        return 1
    plan = repair.desktop_plan(Path.home(), B)
    _confirm_or_exit(plan.describe(), a.yes, "Reset your desktop?")
    errors = plan.execute()
    if errors:
        print(S.fail("\n".join(errors)))
        return 1
    print(S.ok("Desktop reset. Log out and back in (or run `hyprctl reload`)."))
    return 0


def cmd_rescue(a) -> int:
    from .system import repair

    if not repair.is_live_system(B):
        print(S.fail("rescue is for the live ISO: it mounts an installed system and repairs it from outside."))
        return 1
    _need_root("mount and repair an installed system")
    found = repair.find_installed(B)
    if not found:
        print(S.fail("No installed system found."))
        return 1
    for i, f in enumerate(found, 1):
        print(f"  {i}. {f['device']} ({f['fstype']}, {f['size']})")
    choice = found[int(a.index) - 1] if a.index else found[0]
    passphrase = ""
    if choice["encrypted"]:
        import getpass

        passphrase = getpass.getpass(f"Passphrase for {choice['device']}: ")
    runner = util.Runner(log=print)
    target = Path(f"/mnt/{B.id}-rescue")
    repair.mount_installed(repair.sanitize_device(choice["device"]), target, runner, passphrase)
    try:
        plans = [repair.packages_plan(target, runner, refresh=False), repair.boot_plan(target, runner, B)]
        _confirm_or_exit("\n\n".join(p.describe() for p in plans), a.yes, "Repair the installed system?")
        for p in plans:
            p.execute()
    finally:
        repair.unmount_installed(target, runner)
    print(S.ok("Done. Remove the installation medium and reboot."))
    return 0


# ---------------------------------------------------------------------------
# setup tasks, installer, iso, welcome
# ---------------------------------------------------------------------------


def cmd_setup(a) -> int:
    from .ai import tools
    from .tasks import TaskQueue

    queue = TaskQueue(B, Path.home())
    if a.action == "status":
        tasks = queue.load()
        if not tasks:
            print("No setup tasks.")
        for t in tasks:
            print(f"{t.status:<8} {t.label}" + (f"  ({t.error})" if t.error else ""))
        return 0
    pending = queue.pending()
    if not pending:
        return 0
    if a.background:
        from .installer.steps import is_online

        if not is_online():
            return 0
    runner = util.Runner(log=None if a.background else print)
    ctx = tools.UserContext.current(runner)
    failed = queue.run(ctx, log=(lambda m: None) if a.background else print,
                       progress=None if a.background else (lambda tid, d, t: _progress_printer(tid)(d, t)))
    for t in [t for t in queue.load() if t.status == "done" and t.kind == "tool"]:
        _install_desktop_entry(t.params["tool"])
    if any(t.kind == "hypernix" and t.status == "done" for t in queue.load()):
        _install_desktop_entry("hypernix")
    if a.background and util.which("notify-send"):
        msg = "Setup finished." if not failed else f"{len(failed)} setup task(s) failed; open Welcome to retry."
        subprocess.call(["notify-send", "-a", B.name, B.name, msg])
    return 1 if failed else 0


def cmd_installer(a) -> int:
    exe = Path(f"/usr/bin/{B.id}-installer")
    args = []
    if a.config:
        args += ["--config", a.config]
    if a.dry_run:
        args.append("--dry-run")
    if exe.exists():
        os.execv(str(exe), [str(exe), *args])
    from .installer import main as installer_main

    return installer_main.main(args)


def cmd_iso(a) -> int:
    if a.action == "info":
        info = Path(f"/etc/{B.id}/iso-build.json")
        if info.exists():
            print(info.read_text())
            return 0
        print("Not running from the live ISO.")
        return 1
    if not paths.is_source_checkout():
        print(S.fail(f"`{B.cli} iso {a.action}` works in a checkout of the distribution's source: "
                     f"git clone {B.get('DISTRO_GIT_URL')}"))
        return 1
    script = paths.DATA_ROOT / ("build.sh" if a.action == "build" else "tests/qemu/run.sh")
    return subprocess.call([str(script), *a.args])


def cmd_welcome(a) -> int:
    exe = f"{B.id}-welcome"
    if util.which(exe):
        os.execvp(exe, [exe])
    print(S.fail(f"{exe} is not installed (sudo pacman -S {B.id}-welcome)."))
    return 1


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=B.cli, description=f"{B.pretty_name} system tool.")
    p.add_argument("--version", action="version", version=f"{B.cli} {__version__} ({B.pretty_name})")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    s = sub.add_parser("system", help="what this system is and how it is set up")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_system)

    s = sub.add_parser("hardware", help="detected hardware and the recommended configuration")
    s.add_argument("--json", action="store_true")
    s.add_argument("--root", default="/", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_hardware)

    s = sub.add_parser("gpu", help="graphics drivers: detect, configure, status")
    s.add_argument("action", choices=["detect", "plan", "configure", "status"], nargs="?", default="status")
    s.add_argument("--driver", action="append", metavar="SLOT=STACK", help="override the driver for one GPU")
    s.add_argument("--recommended", action="store_true", help="drop earlier overrides and use the recommendation")
    s.add_argument("--compute", dest="compute", action="store_true", default=None, help="install CUDA/ROCm toolkits")
    s.add_argument("--no-compute", dest="compute", action="store_false")
    s.add_argument("--json", action="store_true")
    s.add_argument("-y", "--yes", action="store_true")
    s.add_argument("--root", default="/", help="configure a mounted system instead of this one")
    s.set_defaults(func=cmd_gpu)

    s = sub.add_parser("surface", help="Microsoft Surface kernel")
    s.add_argument("action", choices=["status", "enable", "disable"], nargs="?", default="status")
    s.add_argument("--secure-boot", action="store_true", help="also install the Secure Boot MOK key package")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(func=cmd_surface)

    s = sub.add_parser("update", help="update packages, AUR, Flatpak, desktop and AI tools")
    s.add_argument("--check", action="store_true", help="only list updates (exit 100 if any)")
    s.add_argument("-y", "--yes", action="store_true", help="do not ask pacman/yay questions")
    s.add_argument("-v", "--verbose", action="store_true")
    s.add_argument("--desktop-only", action="store_true", help="only refresh the desktop configuration")
    for src in ("aur", "flatpak", "desktop", "gpu", "ai"):
        s.add_argument(f"--no-{src}", action="store_true")
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("install", help="install features (office, docker, plasma, claude-code, ...) or packages")
    s.add_argument("names", nargs="+")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(func=cmd_install)

    s = sub.add_parser("ai", help="AI assistants, HyperNix and Claude Code")
    s.add_argument("action", choices=["status", "install", "remove", "launch", "backend", "runtime", "update"],
                   nargs="?", default="status")
    s.add_argument("tool", nargs="?", choices=["hypernix", "hermis", "openclaw", "claude-code", "local-model"])
    s.add_argument("--backend", default="", help="override the acceleration backend (cuda, rocm, xpu, vulkan, cpu)")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(func=cmd_ai)

    s = sub.add_parser("model", help="local AI models")
    s.add_argument("action", choices=["list", "recommend", "installed", "info", "install", "add", "remove", "default", "serve"],
                   nargs="?", default="list")
    s.add_argument("id", nargs="?")
    s.add_argument("--hf", metavar="OWNER/REPO", help="add: Hugging Face repository")
    s.add_argument("--file", help="add: GGUF file in the repository")
    s.add_argument("--url", help="add: https URL of a GGUF file")
    s.add_argument("--path", help="add: local GGUF file")
    s.add_argument("--hypernix", metavar="ID", help="add: HyperNix model identifier")
    s.add_argument("--name")
    s.add_argument("--context", type=int, default=8192)
    s.add_argument("--default", action="store_true", help="make it the default model")
    s.add_argument("--foreground", action="store_true", help="serve: run in the foreground (used by the service)")
    s.add_argument("--stop", action="store_true")
    s.add_argument("--status", action="store_true")
    s.add_argument("--json", action="store_true")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(func=cmd_model)

    s = sub.add_parser("doctor", help="diagnose problems")
    s.add_argument("-v", "--verbose", action="store_true")
    s.add_argument("--json", action="store_true")
    s.add_argument("--report", action="store_true", help="also write a support bundle to the current directory")
    s.add_argument("--root", default="/", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("repair", help="fix packages, booting and drivers")
    s.add_argument("what", nargs="?", choices=["auto", "packages", "boot", "all"])
    s.add_argument("--no-update", action="store_true", help="packages: do not run a full upgrade")
    s.add_argument("--root", default="/", help="repair a mounted system")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(func=cmd_repair)

    s = sub.add_parser("repair-gpu", help="re-detect GPUs and reinstall the right drivers")
    s.add_argument("--safe", action="store_true", help="fall back to open-source drivers")
    s.add_argument("--recommended", action="store_true", help="ignore earlier manual driver choices")
    s.add_argument("--root", default="/")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(func=cmd_repair_gpu)

    s = sub.add_parser("reset-desktop", help="restore the default desktop configuration (backs up yours)")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(func=cmd_reset_desktop)

    s = sub.add_parser("rescue", help="live ISO: mount an installed system and repair it")
    s.add_argument("index", nargs="?")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(func=cmd_rescue)

    s = sub.add_parser("setup", help="setup tasks that need the network (AI tools, models)")
    s.add_argument("action", choices=["status", "resume"], nargs="?", default="status")
    s.add_argument("--background", action="store_true")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("installer", help="start the installer (graphical, or unattended with --config)")
    s.add_argument("--config")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_installer)

    s = sub.add_parser("iso", help="build or test the ISO (source checkout), or show live ISO info")
    s.add_argument("action", choices=["build", "test", "info"], nargs="?", default="info")
    s.add_argument("args", nargs=argparse.REMAINDER)
    s.set_defaults(func=cmd_iso)

    s = sub.add_parser("welcome", help="open the welcome wizard")
    s.set_defaults(func=cmd_welcome)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    # `<id>-gpu detect` is `<cli> gpu detect`.
    prog = Path(sys.argv[0]).name
    if prog.endswith("-gpu"):
        argv = ["gpu", *argv]
    a = parser.parse_args(argv)
    if not getattr(a, "func", None):
        parser.print_help()
        return 0
    try:
        return int(a.func(a) or 0)
    except KeyboardInterrupt:
        print()
        return 130
    except util.CommandError as exc:
        print(S.fail(str(exc)), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
