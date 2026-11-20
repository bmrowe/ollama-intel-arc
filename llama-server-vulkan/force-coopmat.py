"""Add an opt-in GGML_VK_FORCE_COOPMAT switch to llama.cpp's Vulkan backend.

Upstream enables KHR cooperative matrices (matrix cores) on Intel only for
Xe2/Xe3, citing regressions on Arc A770 (Alchemist/DG2). This patch keeps that
default and lets a container opt in with GGML_VK_FORCE_COOPMAT=1, so the same
image can be benchmarked with matrix cores on and off.
"""
import sys

path = sys.argv[1]
src = open(path, encoding="utf-8").read()

anchor = (
    "    case VK_VENDOR_ID_INTEL:\n"
    "        // Only allowing Xe2/Xe3 GPU and integrated Xe GPUs at the moment"
)
if src.count(anchor) != 1:
    sys.exit(f"force-coopmat: expected exactly one Intel coopmat gate in {path}, found {src.count(anchor)}")

patched = src.replace(
    anchor,
    "    case VK_VENDOR_ID_INTEL:\n"
    '        if (getenv("GGML_VK_FORCE_COOPMAT") != nullptr) {\n'
    "            return true;\n"
    "        }\n"
    "        // Only allowing Xe2/Xe3 GPU and integrated Xe GPUs at the moment",
)
open(path, "w", encoding="utf-8").write(patched)
print("force-coopmat: patched", path)
