# llama-server-vulkan

llama.cpp's Vulkan server with two changes for Intel Arc Alchemist (A-series, DG2) cards:

1. **`intel-alchemist-coopmat.patch`** turns on KHR cooperative matrices (XMX matrix
   cores) for Alchemist discrete GPUs on Mesa, with three parts:
   - Smaller large and medium matmul tiles (16x16 per subgroup at SIMD8). Upstream's
     Xe1 tiles (32x32 per subgroup) spill hundreds of registers per shader, which is
     why upstream leaves matrix cores off on these cards.
   - The int8 dot-product (Q8_1) matmul pipelines are created too, so quantized types
     keep that path. Upstream only creates them when matrix cores are off, and the
     dequant-to-f16 matrix-core path is slower for quantized types on this card.
   - Those int8 pipelines stay off the large tile, as they are without matrix cores.
   - Intel's Xe flash-attention shader (`flash_attn_prefill.comp`, already written for
     Xe1's 8x8x16 matrix shape) is allowed on Alchemist discrete GPUs too. Upstream only
     enables it on integrated Xe1. It is used for prefill only (its decode shader is
     slower here than the scalar one), and also for mask-less prefill such as vision
     encoders, which otherwise fall back to the scalar shader because upstream's
     coopmat1 flash attention needs a 16x16x16 shape. `GGML_VK_DISABLE_XE_FA_DGPU=1`
     turns it off at runtime.
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
With the Xe flash-attention change on top: 3.34 s (3.88-4.05 s without it, same
session), generation unchanged; descriptions of four real camera snapshots match the
version without it. `test-backend-ops -o FLASH_ATTN_EXT` passes every case at head
sizes 64 and 128 and every mask-less case; the only failures are small precision
misses (0.0006-0.0028 vs 0.0005) in the Xe decode shader at head sizes 192-512,
which this patch does not use on discrete Alchemist.

`test-backend-ops` on the A380 (llama.cpp d3c3e242c, kisak Mesa 26.2.7): MUL_MAT and
MUL_MAT_ID pass 3762/3762. MUL_MAT perf against matrix cores off, 241 shapes: n=1-8
median 1.00x (min 0.87x), n=9-64 median 1.01x (min 0.97x), n>=128 geomean 1.72x
(min 0.98x, max 4.31x; f16 3.5x, bf16 3.0x, quantized types 0.98-1.06x).

Per-shader spill counts came from `INTEL_DEBUG=cs` with `MESA_SHADER_CACHE_DISABLE=true`.
`test/` holds the test-only patch used to find the tiles (env and file overrides).
