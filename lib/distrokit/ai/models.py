"""Local model catalogue, hardware-based recommendations and downloads.

Recommendations are advice, never limits: every catalogue model and any
custom model can be chosen regardless of what the hardware suggests.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tomllib
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .. import paths, util
from ..hardware.report import HardwareReport

GB = 10**9
GiB = 2**30
HF = "https://huggingface.co"

# Memory not available to models: the desktop's own VRAM use, and the part of
# system RAM the OS and applications need.
DESKTOP_VRAM_RESERVE = 0.6 * GiB
RAM_FRACTION_FOR_MODELS = 0.6
RUNTIME_OVERHEAD = 0.4 * GiB


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    category: str
    params_b: float
    quant: str
    repo: str
    file: str
    size_bytes: int
    kv_gb_8k: float
    context: int
    license: str
    description: str
    hypernix_id: str = ""
    active_params_b: float = 0.0
    mmproj: str = ""
    mmproj_size_bytes: int = 0

    @property
    def download_bytes(self) -> int:
        return self.size_bytes + self.mmproj_size_bytes

    def memory_bytes(self, context: int = 8192) -> int:
        """Estimated memory to run the model with ``context`` tokens."""
        kv = self.kv_gb_8k * GiB * (context / 8192)
        return int(self.size_bytes * 1.03 + self.mmproj_size_bytes + kv + RUNTIME_OVERHEAD)

    @property
    def url(self) -> str:
        return f"{HF}/{self.repo}/resolve/main/{urllib.parse.quote(self.file)}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["download_bytes"] = self.download_bytes
        d["download"] = util.human_bytes(self.download_bytes)
        d["memory_8k"] = util.human_bytes(self.memory_bytes())
        return d


@dataclass(frozen=True)
class Catalog:
    categories: dict[str, dict[str, str]]
    models: tuple[Model, ...]

    def get(self, model_id: str) -> Model | None:
        return next((m for m in self.models if m.id == model_id), None)

    def by_category(self, category: str) -> list[Model]:
        return sorted((m for m in self.models if m.category == category), key=lambda m: m.size_bytes)

    def search(self, text: str) -> list[Model]:
        words = text.lower().split()
        return [m for m in self.models if all(w in f"{m.id} {m.name} {m.category} {m.description}".lower() for w in words)]


def load_catalog(path: Path | None = None) -> Catalog:
    path = path or paths.data("ai", "models", "catalog.toml")
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    known = set(Model.__dataclass_fields__)
    models = []
    seen = set()
    for entry in raw.get("model", []):
        unknown = set(entry) - known
        if unknown:
            raise ValueError(f"catalog entry {entry.get('id')}: unknown fields {sorted(unknown)}")
        m = Model(**entry)
        if m.id in seen:
            raise ValueError(f"duplicate catalog id {m.id}")
        if m.category not in raw["categories"]:
            raise ValueError(f"{m.id}: unknown category {m.category}")
        if not m.file.endswith(".gguf"):
            raise ValueError(f"{m.id}: only GGUF files are supported")
        seen.add(m.id)
        models.append(m)
    return Catalog(raw["categories"], tuple(models))


# ---------------------------------------------------------------------------
# Hardware budget and recommendations
# ---------------------------------------------------------------------------


@dataclass
class Budget:
    backend: str  # cuda | rocm | vulkan | xpu | cpu
    gpu_name: str
    vram_bytes: int
    vram_estimated: bool
    gpu_budget: int  # memory usable by models on the GPU
    ram_bytes: int
    cpu_budget: int  # system RAM usable by models
    shared_memory: bool  # integrated GPU using system RAM

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["vram"] = util.human_bytes(self.vram_bytes) if self.vram_bytes else ""
        d["gpu_budget_h"] = util.human_bytes(self.gpu_budget)
        d["cpu_budget_h"] = util.human_bytes(self.cpu_budget)
        return d


def budget(report: HardwareReport, backend: str) -> Budget:
    gpu = report.best_compute_gpu
    ram = report.memory.total_bytes
    cpu_budget = int(ram * RAM_FRACTION_FOR_MODELS)
    if gpu is None or backend == "cpu":
        return Budget("cpu", "", 0, False, 0, ram, cpu_budget, False)
    if gpu.kind == "integrated":
        # Integrated GPUs allocate from system RAM (GTT/shared memory): the
        # budget is shared with the CPU rather than added to it.
        shared = max(int(ram * 0.5), gpu.vram_bytes)
        return Budget(backend, gpu.display_name, gpu.vram_bytes, False, shared, ram, cpu_budget, True)
    vram = gpu.vram_bytes
    reserve = DESKTOP_VRAM_RESERVE if report.topology.primary and report.topology.primary.slot == gpu.slot else 0
    return Budget(backend, gpu.display_name, vram, gpu.vram_source == "estimate",
                  max(0, int(vram * 0.95 - reserve)), ram, cpu_budget, False)


@dataclass
class Fit:
    model: Model
    placement: str  # gpu | offload | cpu | too-large
    memory_bytes: int
    note: str

    @property
    def usable(self) -> bool:
        return self.placement != "too-large"

    def to_dict(self) -> dict[str, Any]:
        d = self.model.to_dict()
        d.update({"placement": self.placement, "memory_bytes": self.memory_bytes, "note": self.note,
                  "usable": self.usable})
        return d


def fit(model: Model, b: Budget, context: int = 8192) -> Fit:
    need = model.memory_bytes(context)
    moe = model.active_params_b and model.active_params_b < model.params_b / 3
    if b.backend != "cpu" and not b.shared_memory and b.gpu_budget:
        if need <= b.gpu_budget:
            return Fit(model, "gpu", need, "Runs entirely on the GPU.")
        if need <= b.gpu_budget + b.cpu_budget:
            note = ("Mixture-of-experts: runs well with experts in system RAM."
                    if moe else "Part of the model runs from system RAM; expect slower replies.")
            return Fit(model, "offload", need, note)
        return Fit(model, "too-large", need, "Needs more memory than this machine has.")
    total = max(b.gpu_budget, b.cpu_budget) if b.shared_memory else b.cpu_budget
    if need <= total:
        where = "integrated GPU" if b.shared_memory else "CPU"
        speed = "" if (model.active_params_b or model.params_b) <= 9 or moe else " Large for this machine; replies will be slow."
        return Fit(model, "cpu" if not b.shared_memory else "gpu", need, f"Runs on the {where}.{speed}")
    return Fit(model, "too-large", need, "Needs more memory than this machine has.")


# (label, smallest, largest) parameter counts, in billions.
BRACKETS = (("1B–4B", 1, 4), ("7B–14B", 7, 14), ("20B–32B", 20, 32), ("70B+", 70, 120))


def _q4_need(params_b: float) -> float:
    return params_b * 0.62 * GiB + (0.15 * params_b**0.5) * GiB + RUNTIME_OVERHEAD


@dataclass
class Recommendation:
    budget: Budget
    lines: list[str]
    defaults: dict[str, str]  # category -> suggested model id
    fits: list[Fit]
    low_memory: bool
    headline: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget": self.budget.to_dict(),
            "lines": self.lines,
            "defaults": self.defaults,
            "fits": [f.to_dict() for f in self.fits],
            "low_memory": self.low_memory,
            "headline": self.headline,
        }


def recommend(report: HardwareReport, backend: str, catalog: Catalog | None = None) -> Recommendation:
    catalog = catalog or load_catalog()
    b = budget(report, backend)
    lines: list[str] = []
    if b.shared_memory:
        # One pool of system memory, whichever processor runs the model.
        gpu_pool, total_pool = 0, max(b.gpu_budget, b.cpu_budget)
    else:
        gpu_pool, total_pool = b.gpu_budget, b.gpu_budget + b.cpu_budget
    fully = [label for label, lo, _ in BRACKETS if gpu_pool and _q4_need(lo) <= gpu_pool]
    for label, lo, _hi in BRACKETS:
        if label in fully:
            if label == "1B–4B" and len(fully) > 1:
                continue
            lines.append(f"{label} quantized")
        elif _q4_need(lo) <= total_pool:
            if gpu_pool:
                lines.append(f"Selected larger models ({label}) with CPU/RAM offloading"
                             if lo >= 70 or not fully else f"{label} quantized with CPU/RAM offloading")
            else:
                lines.append(f"{label} quantized" + (" (slow on CPU)" if lo >= 20 else ""))
    if not lines:
        lines.append("Lightweight models (under 2B parameters)")
    fits = [fit(m, b) for m in catalog.models]
    defaults: dict[str, str] = {}
    for cat in catalog.categories:
        options = [f for f in fits if f.model.category == cat and f.usable]
        preferred = [f for f in options if f.placement in ("gpu", "cpu")] or options
        if b.backend == "cpu" or b.shared_memory:
            # On CPUs, speed tracks active parameters: stay small by default.
            preferred = [f for f in preferred if (f.model.active_params_b or f.model.params_b) <= 9] or preferred[:1]
        if preferred:
            defaults[cat] = max(preferred, key=lambda f: f.model.size_bytes).model.id
    low = b.ram_bytes < 12 * GiB and (b.backend == "cpu" or b.shared_memory)
    if low:
        lines = ["Low memory: lightweight models (up to ~4B parameters) are recommended"]
        for cat in catalog.categories:
            small = [f for f in fits if f.model.category == cat and f.usable and f.model.params_b <= 4.5]
            if small:
                defaults[cat] = max(small, key=lambda f: f.model.size_bytes).model.id
    if b.backend == "cpu":
        head = f"No GPU acceleration available; {util.human_bytes(b.ram_bytes)} RAM for CPU inference."
    elif b.shared_memory:
        head = f"{b.gpu_name} shares system memory ({util.human_bytes(b.ram_bytes)} RAM)."
    else:
        head = f"{b.gpu_name}: {b.vram_bytes / GiB:g} GB VRAM" + (" (estimated)" if b.vram_estimated else "")
    return Recommendation(b, lines, defaults, fits, low, head)


# ---------------------------------------------------------------------------
# Custom models
# ---------------------------------------------------------------------------

_REPO_RE = re.compile(r"^[A-Za-z0-9][\w.-]*/[\w.-]+$")


@dataclass
class CustomModel:
    source: str  # huggingface | url | path | hypernix
    repo: str = ""
    file: str = ""
    url: str = ""
    path: str = ""
    hypernix_id: str = ""
    name: str = ""
    context: int = 8192
    size_bytes: int = 0
    # For "path": copy the file into the model directory instead of using it
    # where it is (the installer sets this: a file on the live system or a USB
    # stick is gone after the reboot).
    copy: bool = False

    def validate(self) -> list[str]:
        errors = []
        if self.source == "huggingface":
            if not _REPO_RE.match(self.repo):
                errors.append("Repository must look like owner/name.")
            if not self.file.endswith(".gguf"):
                errors.append("Model file must be a .gguf file from that repository.")
        elif self.source == "url":
            u = urllib.parse.urlparse(self.url)
            if u.scheme != "https" or not u.netloc:
                errors.append("Model URL must be an https:// link.")
            if not u.path.endswith(".gguf"):
                errors.append("Model URL must point to a .gguf file.")
        elif self.source == "path":
            p = Path(os.path.expanduser(self.path))
            if not p.is_file():
                errors.append(f"{self.path} does not exist.")
            elif p.suffix != ".gguf":
                errors.append("Local model must be a .gguf file.")
        elif self.source == "hypernix":
            if not re.match(r"^[\w.:/-]+$", self.hypernix_id):
                errors.append("Enter a HyperNix model name, e.g. qwen3-8b.")
        else:
            errors.append(f"Unknown model source {self.source!r}.")
        if not 512 <= self.context <= 1_048_576:
            errors.append("Context must be between 512 and 1,048,576 tokens.")
        return errors

    @property
    def id(self) -> str:
        base = self.file or Path(self.url or self.path).name or self.hypernix_id
        return re.sub(r"[^a-z0-9.-]+", "-", base.lower().removesuffix(".gguf")).strip("-") or "custom"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Hugging Face metadata and downloads
# ---------------------------------------------------------------------------


def _open(url: str, timeout: float = 30, headers: dict[str, str] | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": "distrokit-model-manager/1.0", **(headers or {})})
    token = os.environ.get("HF_TOKEN")
    if token and urllib.parse.urlparse(url).netloc.endswith("huggingface.co"):
        req.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(req, timeout=timeout)


def hf_file_info(repo: str, file: str, timeout: float = 20) -> dict[str, Any]:
    """{'size': bytes, 'sha256': hex or ''} from the Hub's tree API."""
    folder = str(Path(file).parent) if "/" in file else ""
    url = f"{HF}/api/models/{repo}/tree/main" + (f"/{urllib.parse.quote(folder)}" if folder else "")
    with _open(url, timeout) as resp:
        entries = json.load(resp)
    for entry in entries:
        if entry.get("path") == file:
            lfs = entry.get("lfs") or {}
            return {"size": int(lfs.get("size") or entry.get("size") or 0), "sha256": lfs.get("oid", "")}
    raise FileNotFoundError(f"{file} not found in {repo}")


def hf_list_gguf(repo: str, timeout: float = 20) -> list[dict[str, Any]]:
    with _open(f"{HF}/api/models/{repo}/tree/main?recursive=1", timeout) as resp:
        entries = json.load(resp)
    return [
        {"file": e["path"], "size": int((e.get("lfs") or {}).get("size") or e.get("size") or 0)}
        for e in entries
        if e.get("type") == "file" and e["path"].endswith(".gguf")
    ]


ProgressFn = Callable[[int, int], None]


def download(url: str, dest: Path, expected_size: int = 0, sha256: str = "", progress: ProgressFn | None = None,
             chunk: int = 4 * 2**20) -> Path:
    """Download with resume support and integrity checks.

    The file is written to ``<dest>.part`` and renamed only after its size
    and (when known) SHA-256 match.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with _open(url, 60, headers) as resp:
        status = getattr(resp, "status", 200)
        if have and status != 206:
            have = 0  # server ignored the range; start over
        total = expected_size or int(resp.headers.get("Content-Length", 0)) + have
        mode = "ab" if have else "wb"
        with part.open(mode) as out:
            done = have
            while True:
                block = resp.read(chunk)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if progress:
                    progress(done, total)
    size = part.stat().st_size
    if expected_size and size != expected_size:
        raise IOError(f"download incomplete: {size} of {expected_size} bytes (run again to resume)")
    if sha256:
        h = hashlib.sha256()
        with part.open("rb") as fh:
            for block in iter(lambda: fh.read(8 * 2**20), b""):
                h.update(block)
        if h.hexdigest() != sha256.lower():
            part.unlink()
            raise IOError(f"checksum mismatch for {dest.name}; the partial file was removed")
    os.replace(part, dest)
    return dest


def check_space(directory: Path, needed: int) -> tuple[bool, int]:
    probe = directory
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    return free >= needed * 1.05, free


# ---------------------------------------------------------------------------
# Installed models (per user)
# ---------------------------------------------------------------------------


class Registry:
    """Installed models and the default one, in ~/.config/<id>/models.json.

    ``home`` is the user's home as the user sees it; ``root`` is where that
    filesystem is mounted in this process (the installer writes into /mnt).
    Paths recorded in the registry are always the user-visible ones.
    """

    def __init__(self, distro_id: str, home: Path | None = None, root: Path | str = "/"):
        self.home = Path(home or Path.home())
        self.root = Path(root)
        self.models_dir = paths.user_data_dir(distro_id, self.home) / "models"
        self.path = paths.user_config_dir(distro_id, self.home) / "models.json"

    def host(self, path: Path) -> Path:
        """Where a user-visible path lives from this process's point of view."""
        return self.root / str(path).lstrip("/") if str(self.root) != "/" else path

    def load(self) -> dict[str, Any]:
        data = util.read_json(self.host(self.path), None) or {}
        data.setdefault("default", "")
        data.setdefault("models", {})
        return data

    def save(self, data: dict[str, Any]) -> None:
        util.write_json(self.host(self.path), data)

    def add(self, model_id: str, entry: dict[str, Any], make_default: bool = False) -> None:
        data = self.load()
        data["models"][model_id] = entry
        if make_default or not data["default"]:
            data["default"] = model_id
        self.save(data)

    def remove(self, model_id: str) -> dict[str, Any] | None:
        data = self.load()
        entry = data["models"].pop(model_id, None)
        if data["default"] == model_id:
            data["default"] = next(iter(data["models"]), "")
        self.save(data)
        return entry

    def set_default(self, model_id: str) -> None:
        data = self.load()
        if model_id not in data["models"]:
            raise KeyError(model_id)
        data["default"] = model_id
        self.save(data)

    def default(self) -> tuple[str, dict[str, Any]] | None:
        data = self.load()
        mid = data["default"]
        if mid and mid in data["models"]:
            return mid, data["models"][mid]
        return None


def install_catalog_model(model: Model, registry: Registry, progress: ProgressFn | None = None,
                          make_default: bool = False, verify: bool = True) -> Path:
    ok, free = check_space(registry.host(registry.models_dir), model.download_bytes)
    if not ok:
        raise IOError(f"{model.name} needs {util.human_bytes(model.download_bytes)}; only {util.human_bytes(free)} free")
    target = registry.models_dir / model.id / model.file
    sha = hf_file_info(model.repo, model.file)["sha256"] if verify else ""
    download(model.url, registry.host(target), model.size_bytes, sha, progress)
    entry: dict[str, Any] = {"name": model.name, "path": str(target), "context": min(model.context, 8192),
                             "source": f"hf:{model.repo}/{model.file}", "category": model.category}
    if model.mmproj:
        mm = registry.models_dir / model.id / model.mmproj
        mm_sha = hf_file_info(model.repo, model.mmproj)["sha256"] if verify else ""
        url = f"{HF}/{model.repo}/resolve/main/{urllib.parse.quote(model.mmproj)}"
        download(url, registry.host(mm), model.mmproj_size_bytes, mm_sha, progress)
        entry["mmproj"] = str(mm)
    if model.hypernix_id:
        entry["hypernix_id"] = model.hypernix_id
    registry.add(model.id, entry, make_default)
    return target


def copy_file(src: Path, dest: Path, progress: ProgressFn | None = None, chunk: int = 16 * 2**20) -> Path:
    """Copy through a .part file, reporting progress."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    total = src.stat().st_size
    done = 0
    with src.open("rb") as fin, part.open("wb") as fout:
        while True:
            buf = fin.read(chunk)
            if not buf:
                break
            fout.write(buf)
            done += len(buf)
            if progress:
                progress(done, total)
    part.replace(dest)
    return dest


def install_custom_model(custom: CustomModel, registry: Registry, progress: ProgressFn | None = None,
                         make_default: bool = False) -> Path | None:
    errors = custom.validate()
    if errors:
        raise ValueError("; ".join(errors))
    mid = custom.id
    entry: dict[str, Any] = {"name": custom.name or mid, "context": custom.context}
    target: Path | None = None
    if custom.source == "huggingface":
        info = hf_file_info(custom.repo, custom.file)
        ok, free = check_space(registry.host(registry.models_dir), info["size"])
        if not ok:
            raise IOError(f"needs {util.human_bytes(info['size'])}; only {util.human_bytes(free)} free")
        target = registry.models_dir / mid / Path(custom.file).name
        url = f"{HF}/{custom.repo}/resolve/main/{urllib.parse.quote(custom.file)}"
        download(url, registry.host(target), info["size"], info["sha256"], progress)
        entry["source"] = f"hf:{custom.repo}/{custom.file}"
    elif custom.source == "url":
        target = registry.models_dir / mid / Path(urllib.parse.urlparse(custom.url).path).name
        download(custom.url, registry.host(target), custom.size_bytes, "", progress)
        entry["source"] = custom.url
    elif custom.source == "path":
        src = Path(os.path.expanduser(custom.path)).resolve()
        if custom.copy:
            size = src.stat().st_size
            ok, free = check_space(registry.host(registry.models_dir), size)
            if not ok:
                raise IOError(f"needs {util.human_bytes(size)}; only {util.human_bytes(free)} free")
            target = registry.models_dir / mid / src.name
            copy_file(src, registry.host(target), progress)
        else:
            target = src  # used where it is
        entry["source"] = f"file:{src}"
    elif custom.source == "hypernix":
        entry["source"] = f"hypernix:{custom.hypernix_id}"
        entry["hypernix_id"] = custom.hypernix_id
    if target is not None:
        entry["path"] = str(target)
    registry.add(mid, entry, make_default)
    return target
