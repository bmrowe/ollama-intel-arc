# llama-server-vulkan

llama.cpp's official Vulkan server image, rebuilt with one opt-in change for
Intel Arc Alchemist (A-series, DG2) cards:

- `GGML_VK_FORCE_COOPMAT=1` turns on KHR cooperative matrices (XMX matrix
  cores), which upstream leaves off for pre-Xe2 Intel GPUs. Unset, the image
  behaves exactly like upstream.

Two tags are published by `.github/workflows/build-llama-server-vulkan.yml`:

| Tag | Mesa |
|---|---|
| `ghcr.io/bmrowe/llama-server-vulkan-unraid:mesa-ubuntu` | Ubuntu's packaged Mesa |
| `ghcr.io/bmrowe/llama-server-vulkan-unraid:mesa-kisak` | Latest stable Mesa from the kisak PPA |

Check what the backend sees with `/app/llama bench ... -p 16 -n 0 -r 1`: the
`ggml_vulkan` line reports `matrix cores: KHR_coopmat` when the switch is on.
