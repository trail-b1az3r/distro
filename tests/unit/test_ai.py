"""AI layer: model catalogue and recommendations, acceleration backends,
downloads, the model registry, setup tasks and per-user tool installs."""

import functools
import hashlib
import http.server
import json
import threading
from pathlib import Path

import pytest

from distrokit import util
from distrokit.ai import backends, models, tools
from distrokit.branding import load as load_branding
from distrokit.gpu.plan import build_plan
from distrokit.tasks import Task, TaskQueue, queue_for_install

GiB = 2**30


def test_catalogue_is_consistent():
    cat = models.load_catalog()
    ids = [m.id for m in cat.models]
    assert len(ids) == len(set(ids)) >= 15
    for m in cat.models:
        assert m.category in cat.categories, m.id
        assert "/" in m.repo and m.file.endswith(".gguf") and m.size_bytes > 100 * 2**20, m.id
        assert m.params_b > 0 and m.context >= 4096 and m.license, m.id
        assert bool(m.mmproj) == bool(m.mmproj_size_bytes), m.id
        assert m.url.startswith("https://huggingface.co/") and " " not in m.url
    assert {"general", "coding"} <= set(cat.categories)


def backend_for(machine, name, compute=True):
    _root, report = machine(name)
    plan = build_plan(report, compute=compute)
    return report, backends.select(report, plan)


@pytest.mark.parametrize("name, backend, torch", [
    ("rtx4080_desktop", "cuda", "cu128"),
    ("hybrid_gtx1080_laptop", "cuda_legacy", "cu126"),
    ("kepler_desktop", "vulkan", "cpu"),
    ("qemu_vm", "cpu", "cpu"),
])
def test_backend_selection(machine, name, backend, torch):
    _report, be = backend_for(machine, name)
    assert be.name == backend
    assert be.torch_index.endswith(torch)
    assert be.llama_package == ("llama.cpp" if backend == "cpu" else "llama.cpp-vulkan")


def test_backend_override_and_validation(machine):
    _root, report = machine("rtx4080_desktop")
    plan = build_plan(report)
    assert backends.select(report, plan, "cpu").name == "cpu"
    with pytest.raises(ValueError, match="unknown backend"):
        backends.select(report, plan, "tpu")


def test_recommendations_scale_with_hardware(machine):
    big, be = backend_for(machine, "rtx4080_desktop")
    rec = models.recommend(big, be.name)
    assert rec.headline.startswith("NVIDIA") and "16 GB VRAM" in rec.headline
    assert any("7B–14B" in line for line in rec.lines)
    assert set(rec.defaults) >= {"general", "coding"}
    defaults = {f.model.id: f for f in rec.fits}
    assert all(defaults[mid].usable for mid in rec.defaults.values())

    vm, be = backend_for(machine, "qemu_vm")
    rec = models.recommend(vm, be.name)
    assert rec.headline.startswith("No GPU acceleration")
    chosen = [defaults_fit for defaults_fit in rec.fits if defaults_fit.model.id in rec.defaults.values()]
    assert all((f.model.active_params_b or f.model.params_b) <= 9 for f in chosen)  # small on CPU


def test_fit_placement():
    m = models.Model("x", "X", "general", 8, "Q4_K_M", "a/b", "x.gguf", 5 * GiB, 1.0, 32768, "MIT", "")
    gpu = models.Budget("cuda", "GPU", 16 * GiB, False, 14 * GiB, 32 * GiB, 20 * GiB, False)
    small_gpu = models.Budget("cuda", "GPU", 4 * GiB, False, 3 * GiB, 32 * GiB, 20 * GiB, False)
    cpu_tiny = models.Budget("cpu", "", 0, False, 0, 4 * GiB, 2 * GiB, False)
    assert models.fit(m, gpu).placement == "gpu"
    assert models.fit(m, small_gpu).placement == "offload"
    assert models.fit(m, cpu_tiny).placement == "too-large"


@pytest.mark.parametrize("fields, error", [
    ({"source": "huggingface", "repo": "nope", "file": "a.gguf"}, "owner/name"),
    ({"source": "huggingface", "repo": "a/b", "file": "a.bin"}, ".gguf"),
    ({"source": "url", "url": "http://x/a.gguf"}, "https://"),
    ({"source": "url", "url": "https://x/a.zip"}, ".gguf"),
    ({"source": "path", "path": "/nonexistent.gguf"}, "does not exist"),
    ({"source": "hypernix", "hypernix_id": "bad id"}, "HyperNix"),
    ({"source": "huggingface", "repo": "a/b", "file": "a.gguf", "context": 100}, "Context"),
    ({"source": "ftp"}, "Unknown model source"),
])
def test_custom_model_validation(fields, error):
    errors = models.CustomModel(**fields).validate()
    assert any(error in e for e in errors), errors


def test_custom_model_ids():
    assert models.CustomModel("huggingface", repo="a/b", file="sub/Qwen3-8B-Q4_K_M.gguf").id == "sub-qwen3-8b-q4-k-m"
    assert models.CustomModel("url", url="https://x/y/My.Model.gguf").id == "my.model"
    assert models.CustomModel("hypernix", hypernix_id="qwen3:8b").id == "qwen3-8b"


class _Files(http.server.SimpleHTTPRequestHandler):
    """Static files with Range support (enough for resume tests)."""

    def log_message(self, *args):
        pass

    def send_head(self):
        rng = self.headers.get("Range")
        path = Path(self.translate_path(self.path))
        if not rng or not path.is_file():
            return super().send_head()
        start = int(rng.split("=")[1].split("-")[0])
        data = path.read_bytes()
        self.send_response(206)
        self.send_header("Content-Length", str(len(data) - start))
        self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        self.end_headers()
        import io

        return io.BytesIO(data[start:])


@pytest.fixture
def server(tmp_path, monkeypatch):
    for var in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "www"
    root.mkdir()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Files, directory=str(root)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield root, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_download_resumes_and_verifies(server, tmp_path):
    root, base = server
    blob = bytes(range(256)) * 4096  # 1 MiB
    (root / "m.gguf").write_bytes(blob)
    sha = hashlib.sha256(blob).hexdigest()
    dest = tmp_path / "models" / "m.gguf"
    dest.parent.mkdir()
    (dest.parent / "m.gguf.part").write_bytes(blob[:300_000])  # an interrupted earlier download
    seen = []
    models.download(f"{base}/m.gguf", dest, len(blob), sha, lambda d, t: seen.append((d, t)))
    assert dest.read_bytes() == blob and not (dest.parent / "m.gguf.part").exists()
    assert seen[0][0] > 300_000 and seen[-1] == (len(blob), len(blob))

    bad = tmp_path / "models" / "bad.gguf"
    with pytest.raises(IOError, match="checksum mismatch"):
        models.download(f"{base}/m.gguf", bad, len(blob), "0" * 64)
    assert not bad.exists() and not (bad.parent / "bad.gguf.part").exists()


def test_registry_and_local_model_copy_into_target_root(tmp_path):
    b = load_branding()
    target = tmp_path / "mnt"
    home = Path("/home/alex")
    reg = models.Registry(b.id, home, target)
    src = tmp_path / "usb" / "Tiny-Q4.gguf"
    src.parent.mkdir()
    src.write_bytes(b"GGUF" * 1000)
    custom = models.CustomModel("path", path=str(src), copy=True)
    dest = models.install_custom_model(custom, reg, make_default=True)
    # The registry records the path the user will see; the file is in the target.
    assert dest == home / f".local/share/{b.id}/models/tiny-q4/Tiny-Q4.gguf"
    assert (target / str(dest).lstrip("/")).read_bytes() == src.read_bytes()
    assert reg.default() == ("tiny-q4", reg.load()["models"]["tiny-q4"])
    reg.add("other", {"name": "Other", "path": "/x.gguf"})
    assert reg.default()[0] == "tiny-q4"
    reg.remove("tiny-q4")
    assert reg.default()[0] == "other"
    with pytest.raises(KeyError):
        reg.set_default("missing")


def test_task_queue_runs_in_order_and_survives_failures(tmp_path, monkeypatch):
    b = load_branding()
    queue = TaskQueue(b, Path("/home/alex"), tmp_path)
    added = queue_for_install(queue, assistant="both", hypernix=True, claude_code=True,
                              backend_torch_index="https://download.pytorch.org/whl/cu128", backend_env={},
                              model="qwen3-8b", custom_model=None, dots_requirements="/req.txt")
    assert [t.id for t in added] == ["desktop-venv", "hypernix", "tool:hermis", "tool:openclaw",
                                     "tool:claude-code", "model:qwen3-8b"]
    assert added[-1].size_bytes > 4 * GiB
    ran = []

    def fake_execute(task, ctx, progress):
        ran.append(task.id)
        if task.id == "tool:openclaw":
            raise RuntimeError("npm error 404\nnetwork unreachable")

    monkeypatch.setattr("distrokit.tasks.execute", fake_execute)
    ctx = tools.UserContext("alex", Path("/home/alex"), tmp_path, util.Runner(dry_run=True), b)
    failed = queue.run(ctx, only=[t.id for t in added if not t.id.startswith("model:")])
    assert ran == ["desktop-venv", "hypernix", "tool:hermis", "tool:openclaw", "tool:claude-code"]
    assert [t.id for t in failed] == ["tool:openclaw"] and failed[0].error == "network unreachable"
    status = {t.id: t.status for t in queue.load()}
    assert status["tool:claude-code"] == "done" and status["model:qwen3-8b"] == "pending"
    assert [t.id for t in queue.pending()] == ["tool:openclaw", "model:qwen3-8b"]
    queue.skip("model:qwen3-8b")
    assert [t.id for t in queue.pending()] == ["tool:openclaw"]
    saved = json.loads((tmp_path / f"home/alex/.local/state/{b.id}/setup-tasks.json").read_text())
    assert saved[0]["kind"] == "desktop_venv"


def test_tool_installs_run_as_the_user_in_the_target(tmp_path):
    b = load_branding()
    runner = util.Runner(dry_run=True)
    ctx = tools.UserContext("alex", Path("/home/alex"), tmp_path, runner, b)
    tools.install_tool(tools.load_spec("claude-code"), ctx)
    tools.install_tool(tools.load_spec("hermis"), ctx)
    tools.install_hypernix(ctx, "https://download.pytorch.org/whl/cu126", {"HSA_OVERRIDE_GFX_VERSION": "10.3.0"})
    cmds = [" ".join(c) for c in runner.recorded]
    npm = next(c for c in cmds if " npm install " in c)
    assert npm.startswith(f"arch-chroot {tmp_path} runuser -u alex -- env HOME=/home/alex")
    assert "--prefix /home/alex/.local" in npm and npm.endswith("@anthropic-ai/claude-code")
    assert any("uv tool install" in c for c in cmds)
    torch = next(c for c in cmds if "--index-url" in c)
    assert torch.endswith("--index-url https://download.pytorch.org/whl/cu126 torch")
    # Torch comes first so hypernix reuses the GPU build.
    assert cmds.index(torch) < next(i for i, c in enumerate(cmds) if c.endswith(" hypernix"))


def test_node_version_requirement():
    assert tools.satisfies("22.11.0", ">=18.0.0")
    assert not tools.satisfies("16.20.2", ">=18.0.0")
    assert tools.satisfies("20.1.0", ">=20.0.0 <23")
    assert not tools.satisfies("24.0.0", ">=20.0.0 <23")


def test_task_dataclass_roundtrip():
    t = Task("x", "tool", "X", {"tool": "hermis"})
    assert Task(**t.to_dict()) == t
