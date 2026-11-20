# llama-server-vulkan

llama.cpp's Vulkan server with two changes for Intel Arc Alchemist (A-series, DG2) cards:

1. **`intel-alchemist-coopmat.patch`** turns on KHR cooperative matrices (XMX matrix
   cores) for Alchemist discrete GPUs on Mesa, and gives them smaller matmul tiles.
   Upstream leaves matrix cores off on these cards because its Xe1 tiles (32x32 per
   subgroup) spill hundreds of registers per shader, which made them much slower.
   With 16x16 per subgroup at SIMD8 the shaders compile without spills.
2. **Mesa from the [kisak PPA](https://launchpad.net/~kisak/+archive/ubuntu/kisak-mesa)**
   instead of Ubuntu 26.04's.

Published as `ghcr.io/bmrowe/llama-server-vulkan-unraid:latest` by
`.github/workflows/build-llama-server-vulkan.yml`. It checks daily and rebuilds only
when the official `server-vulkan` image moves to a new llama.cpp commit, kisak
publishes a new Mesa, or the patch changes. It builds the same commit as the
official image, so a build that upstream got through is known to compile. If the
patch stops applying, the build fails and `:latest` stays on the last good image.

## Measurements (Arc A380, Qwen3-VL-4B Q4_K_M + mmproj F16, flash attention, f16 KV)

`llama bench` pp768/tg64, tokens/s:

| Setup | Prompt | Generation |
|---|---|---|
| Ubuntu Mesa 26.0.8, matrix cores off | 364 | 27.1 |
| kisak Mesa 26.2.7, matrix cores off | 370 | 33.2 |
| kisak Mesa, matrix cores on, upstream Xe1 tiles | 133 | 34.3 |
| kisak Mesa, matrix cores on, this patch | 377 | 34.8 |

Server request with three 500x500 images (image encoding + prompt, median):
5.29 s with matrix cores off, 3.80 s with this patch. The gain comes from the F16
vision encoder; quantized matmul only ties the integer dot-product path.

Per-shader spill counts came from `INTEL_DEBUG=cs` with `MESA_SHADER_CACHE_DISABLE=true`.
`test/` holds the test-only patch used to find the tiles (env and file overrides).
