"""GPU manager: driver selection, hybrid setup and applying a plan."""

import pytest

from distrokit import boot, util
from distrokit.branding import load as load_branding
from distrokit.gpu import apply as gpu_apply
from distrokit.gpu import build_plan
from distrokit.gpu import status as gpu_status


def test_nvidia_modern_single_gpu(machine):
    _, r = machine("rtx4080_desktop")
    plan = build_plan(r, kernels=["linux"])
    assert [c.stack for c in plan.choices] == ["nvidia-open"]
    # Only the stock kernel: the prebuilt module package, no DKMS, no headers.
    assert "nvidia-open" in plan.packages and "nvidia-open-dkms" not in plan.packages
    assert "linux-headers" not in plan.packages
    assert plan.env["LIBVA_DRIVER_NAME"] == "nvidia"
    assert "nvidia_drm.modeset=1" in plan.kernel_params
    assert plan.drop_kms_hook and "nvidia_drm" in plan.initramfs_modules
    assert "nvidia-suspend.service" in plan.services
    assert plan.compute_backend == "cuda"
    assert not plan.aur_packages
    assert "cuda" not in plan.all_packages  # compute toolkits are opt-in


def test_nvidia_dkms_for_extra_kernels(machine):
    _, r = machine("rtx4080_desktop")
    plan = build_plan(r, kernels=["linux", "linux-lts"], compute=True)
    assert "nvidia-open-dkms" in plan.packages
    assert {"linux-headers", "linux-lts-headers"} <= set(plan.packages)
    assert {"cuda", "cudnn"} <= set(plan.compute_packages)


def test_no_nvidia_packages_without_nvidia(machine):
    for name in ("rx7900xtx_desktop", "surface_pro7", "qemu_vm", "rembrandt_laptop"):
        _, r = machine(name)
        plan = build_plan(r, compute=True)
        assert not any(p.startswith(("nvidia", "lib32-nvidia", "cuda")) for p in plan.all_packages), name
        # ...and they are removed if a previous configuration left them behind.
        assert {"nvidia-open", "nvidia-utils", "cuda"} <= set(plan.conflicts), name


def test_amd_rocm_is_opt_in_and_only_when_supported(machine):
    _, r = machine("rx7900xtx_desktop")
    assert build_plan(r).compute_packages == []
    plan = build_plan(r, compute=True)
    assert "rocm-hip-runtime" in plan.compute_packages
    assert plan.compute_backend == "rocm"
    assert "HSA_OVERRIDE_GFX_VERSION" not in plan.env  # gfx1100 is native


def test_hybrid_intel_nvidia_pascal(machine):
    _, r = machine("hybrid_gtx1080_laptop")
    plan = build_plan(r, kernels=["linux"])
    roles = {c.vendor: (c.role, c.stack) for c in plan.choices}
    assert roles == {"intel": ("primary", "intel"), "nvidia": ("offload", "nvidia-580xx")}
    # The 580 legacy branch comes from the AUR (or the distribution repo).
    assert "nvidia-580xx-dkms" in plan.aur_packages
    assert "linux-headers" in plan.packages
    assert "nvidia-prime" in plan.packages
    # No NVIDIA-only globals on a hybrid system: the iGPU drives the desktop.
    assert "LIBVA_DRIVER_NAME" not in plan.env and "__GLX_VENDOR_LIBRARY_NAME" not in plan.env
    assert plan.env["AQ_DRM_DEVICES"] == "/dev/dri/nexora-primary-card:/dev/dri/nexora-offload-card"
    assert 'KERNELS=="0000:00:02.0"' in plan.udev_rules and 'KERNELS=="0000:01:00.0"' in plan.udev_rules
    # Pascal has no fine-grained runtime power management.
    assert not any("DynamicPowerManagement" in m for m in plan.modprobe)


def test_kepler_uses_nouveau(machine):
    _, r = machine("kepler_desktop")
    plan = build_plan(r)
    assert [c.stack for c in plan.choices] == ["nouveau"]
    assert not any(p.startswith("nvidia") for p in plan.all_packages)
    assert any("NVK" in n for n in plan.notes)


def test_override_is_respected(machine):
    _, r = machine("rtx4080_desktop")
    slot = r.gpus[0].slot
    plan = build_plan(r, overrides={slot: "nouveau"})
    assert plan.choices[0].stack == "nouveau" and plan.choices[0].recommended == "nvidia-open"
    assert "nvidia-open" in plan.conflicts
    with pytest.raises(ValueError):
        build_plan(r, overrides={slot: "amdgpu"})


def test_multilib_optional(machine):
    _, r = machine("rtx4080_desktop")
    plan = build_plan(r, multilib=False)
    assert not any(p.startswith("lib32-") for p in plan.all_packages)


def test_apply_writes_config_in_target_root(machine, tmp_path):
    _, r = machine("hybrid_gtx1080_laptop")
    target = tmp_path / "target"
    target.mkdir()
    branding = load_branding()
    plan = build_plan(r)
    log = []
    runner = util.Runner(dry_run=False, log=log.append)
    changed = gpu_apply.write_files(plan, target, branding, runner)
    env = (target / "etc/nexora/gpu.env").read_text()
    assert "AQ_DRM_DEVICES=" in env
    assert (target / "etc/udev/rules.d/80-nexora-gpu.rules").is_file()
    mk = (target / "etc/mkinitcpio.conf.d/20-nexora-gpu.conf").read_text()
    assert "MODULES+=(nvidia nvidia_modeset nvidia_uvm nvidia_drm)" in mk
    assert "nvidia_drm.modeset=1" in boot.read_cmdline(target, branding)
    assert "kernel command line" in changed
    # Re-applying the same plan changes nothing.
    assert gpu_apply.write_files(plan, target, branding, runner) == []


def test_apply_dry_run_records_commands(machine, tmp_path):
    _, r = machine("rtx4080_desktop")
    runner = util.Runner(dry_run=True)
    gpu_apply.apply(build_plan(r), root=tmp_path, runner=runner)
    cmds = [" ".join(c) for c in runner.recorded]
    assert any(c.startswith(f"arch-chroot {tmp_path} pacman -S") and "nvidia-open" in c for c in cmds)
    assert any("mkinitcpio -P" in c for c in cmds)
    assert not (tmp_path / "etc/nexora/gpu.env").exists()  # dry run writes nothing


def test_status_render(machine):
    root, r = machine("rtx4080_desktop")
    statuses = gpu_status.gather(r, root)
    text = gpu_status.render(statuses, util.Style(False))
    assert "Vendor  NVIDIA" in text.replace(":", "") or "Vendor" in text
    assert statuses[0].status == "Not configured"
    assert any("missing packages" in p for p in statuses[0].problems)
    assert any("running nouveau" in p for p in statuses[0].problems)
