#!/usr/bin/env python3
"""Trim llama.cpp's .devops/vulkan.Dockerfile for this image's build.

- ccache, with a BuildKit cache mount (id ccache-server) that the workflow
  carries between runs with buildkit-cache-dance.
- One CPU backend for the i5-13500 (the alderlake feature set) instead of
  the 14 x86 variants of GGML_CPU_ALL_VARIANTS.
- Only the targets the server image ships: llama (llama-app, which also
  carries bench, quantize, perplexity...), llama-server and the two backends.

Every edit must match exactly once, so an upstream Dockerfile change fails
the build here instead of silently building something else.
"""
import sys

CPU_FLAGS = ("-DGGML_CPU_ALL_VARIANTS=OFF -DGGML_SSE42=ON -DGGML_AVX=ON -DGGML_F16C=ON "
             "-DGGML_FMA=ON -DGGML_AVX2=ON -DGGML_BMI2=ON -DGGML_AVX_VNNI=ON")
TARGETS = "--target llama-app llama-server ggml-cpu ggml-vulkan"

EDITS = [
    ("RUN apt update && apt install -y git build-essential cmake wget xz-utils\n",
     "RUN apt update && apt install -y git build-essential cmake wget xz-utils ccache\n"),
    ("RUN cmake -B build -DGGML_NATIVE=OFF -DGGML_VULKAN=ON -DLLAMA_BUILD_TESTS=OFF "
     "-DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON && \\\n"
     "    cmake --build build --config Release -j$(nproc)\n",
     "RUN --mount=type=cache,id=ccache-server,target=/root/.cache/ccache \\\n"
     "    cmake -B build -DGGML_NATIVE=OFF -DGGML_VULKAN=ON -DLLAMA_BUILD_TESTS=OFF "
     f"-DGGML_BACKEND_DL=ON {CPU_FLAGS} && \\\n"
     f"    cmake --build build --config Release -j$(nproc) {TARGETS} && \\\n"
     "    ccache --show-stats\n"),
]

path = sys.argv[1]
text = open(path).read()
for old, new in EDITS:
    n = text.count(old)
    if n != 1:
        sys.exit(f"slim-dockerfile: expected 1 match, found {n}:\n{old}")
    text = text.replace(old, new)
open(path, "w").write(text)
print("slim-dockerfile: applied", len(EDITS), "edits")
