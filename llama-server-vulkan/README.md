# llama-server-vulkan

llama.cpp's official Vulkan server image (`ghcr.io/ggml-org/llama.cpp:server-vulkan`)
with Mesa replaced by the latest stable release from the
[kisak PPA](https://launchpad.net/~kisak/+archive/ubuntu/kisak-mesa). Nothing else
changes: same binaries, entrypoint and `LLAMA_ARG_*` variables.

Published as `ghcr.io/bmrowe/llama-server-vulkan-unraid:latest` by
`.github/workflows/build-llama-server-vulkan.yml`, which checks daily and rebuilds
only when the upstream image or the kisak Mesa version has changed.

## Why

Measured on an Intel Arc A380 (Qwen3-VL-4B Q4_K_M, flash attention on, f16 KV cache,
`llama bench` pp768/tg64):

| Mesa | Prompt (tok/s) | Generation (tok/s) |
|---|---|---|
| 26.0.8 (Ubuntu 26.04) | 364 | 27.1 |
| 26.2.7 (kisak) | 370 | 33.2 |

Forcing KHR cooperative matrices (matrix cores) on this Alchemist card made prompt
processing 4.6x slower on Mesa 26.0.8 and 2.7x slower on 26.2.7, so upstream's
default of leaving them off on pre-Xe2 Intel GPUs is kept.
