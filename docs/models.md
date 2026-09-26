# Local AI models

Models run on your computer through [llama.cpp](https://github.com/ggml-org/llama.cpp)
(GGUF files). Nothing large is ever downloaded without showing its size, the
memory it needs, and the free space.

## Recommendations

```bash
nexora model recommend
```

The recommendation comes from your GPU's memory (VRAM, or shared memory on
integrated GPUs) and RAM. For example, 16 GB of RAM with an 8 GB GPU gives:

```
Recommended local models:
- 7B–14B quantized
- 20B–32B quantized
- Selected larger models (70B+) with CPU/RAM offloading
```

These are **informational**: you can pick any model; the manager shows for
each whether it runs entirely on the GPU, with part offloaded to RAM (slower),
on the CPU, or needs more memory than the machine has.

## The catalogue

Defined in [`ai/models/catalog.toml`](../ai/models/catalog.toml), with exact
file sizes; downloads are verified against Hugging Face's SHA-256.

| Model | Category | Download | Memory (8k context) | Licence |
|---|---|---|---|---|
| Qwen3 0.6B | lightweight | 610 MiB | 1.9 GiB | Apache-2.0 |
| Qwen3 1.7B | lightweight | 1 GiB | 2.4 GiB | Apache-2.0 |
| Llama 3.2 3B Instruct | lightweight | 1.9 GiB | 3.2 GiB | Llama 3.2 Community |
| Qwen3 4B Instruct 2507 | general | 2.3 GiB | 4 GiB | Apache-2.0 |
| Qwen3 8B | general | 4.7 GiB | 6.4 GiB | Apache-2.0 |
| Gemma 3 12B | general | 6.8 GiB | 10.6 GiB | Gemma Terms |
| Qwen3 30B-A3B Instruct 2507 | general | 17.3 GiB | 19 GiB | Apache-2.0 |
| Llama 3.3 70B Instruct | general | 39.6 GiB | 43.9 GiB | Llama 3.3 Community |
| Qwen2.5 Coder 7B / 14B / 32B | coding | 4.4 / 8.4 / 18.5 GiB | 5.4 / 10.6 / 21.5 GiB | Apache-2.0 |
| Qwen3 Coder 30B-A3B | coding | 17.3 GiB | 19 GiB | Apache-2.0 |
| DeepSeek R1 Distill Qwen 7B / 14B | reasoning | 4.4 / 8.4 GiB | 5.4 / 10.6 GiB | MIT |
| gpt-oss 20B / 120B | reasoning | 11.3 / 59 GiB | 12.4 / 61.8 GiB | Apache-2.0 |
| Qwen3 32B | reasoning | 18.4 GiB | 21.5 GiB | Apache-2.0 |
| Qwen2.5 VL 3B / 7B | vision | 3 / 5.6 GiB | 3.8 / 6.7 GiB | Qwen Research / Apache-2.0 |
| Gemma 3 4B / 27B (vision) | vision | 3.1 / 16.2 GiB | 4.7 / 21.3 GiB | Gemma Terms |

Mixture-of-experts models (the *A3B* ones, gpt-oss) run well even when they
do not fit in VRAM, because only a few experts are active per token.

## Installing models

In the installer's *Model* page, the Welcome wizard, or the AI launcher's
*Models* tab — or:

```bash
nexora model list                        # the catalogue, with what fits
nexora model install qwen3-8b            # download (resumable), verify, register
nexora model default qwen3-8b
nexora model installed
nexora model remove qwen3-8b
```

In the installer you can choose to download **now** (while installing) or
**after the first login** (the download then runs in the background once you
are online; the Welcome wizard shows progress).

### Custom models

Any GGUF model can be added:

```bash
nexora model add --hf unsloth/Qwen3-14B-GGUF --file Qwen3-14B-Q4_K_M.gguf   # Hugging Face repo + file
nexora model add --url https://example.org/model.gguf                        # direct https link
nexora model add --path ~/Downloads/model.gguf                               # a local file (used in place)
nexora model add --hypernix qwen3-8b                                         # a HyperNix model id
nexora model add ... --name "My model" --context 32768 --default
```

For Hugging Face, omit `--file` in the model manager to list the repository's
GGUF files with their sizes. In the installer, a local GGUF path (for example
on a USB stick) is **copied** into the new system, since the stick will be gone
after the reboot.

## Serving

```bash
nexora model serve          # start the local server (user service nexora-llm.service)
nexora model serve --stop
nexora model serve --status
```

The server listens on `http://127.0.0.1:8081` (OpenAI-compatible API under
`/v1`), uses the GPU when the llama.cpp build supports it, and is not started
at boot unless you enable it: `systemctl --user enable --now nexora-llm`.

llama.cpp builds: `llama.cpp-vulkan` (any GPU, prebuilt in the distribution
repository) is the default; `llama.cpp-cuda` and `llama.cpp-hip` are faster on
NVIDIA/AMD but are long builds: `nexora ai runtime --backend cuda`.
Settings (port, context) are in [`ai/runtime/llama-server.toml`](../ai/runtime/llama-server.toml).
