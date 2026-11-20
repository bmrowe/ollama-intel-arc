"""TEST ONLY patch for the A380 matrix-core investigation. Adds two env switches to
llama.cpp's Vulkan backend so tile shapes can be tried without rebuilding:

  GGML_VK_FORCE_COOPMAT=1          use KHR cooperative matrices on pre-Xe2 Intel
  GGML_VK_L_WARPTILE=a,b,...       override the large f16/f32 matmul warptile (11 values)
  GGML_VK_L_WARPTILE_MMQ=a,b,...   override the large quantized matmul warptile (11 values)

Warptile order (mul_mm.comp spec constants): BLOCK_SIZE, BM, BN, BK, WM, WN, WMITER,
TM, TN, TK, WARP (WARP is also the required subgroup size). Workgroup denominators
follow BM/BN. Overrides are printed to stderr when applied.
"""
import sys

path = sys.argv[1]
src = open(path, encoding="utf-8").read()


def replace_once(text, old, new, what):
    if text.count(old) != 1:
        sys.exit(f"test-tuning-patch: expected one {what} in {path}, found {text.count(old)}")
    return text.replace(old, new)


src = replace_once(
    src,
    "    case VK_VENDOR_ID_INTEL:\n        // Only allowing Xe2/Xe3 GPU and integrated Xe GPUs at the moment",
    "    case VK_VENDOR_ID_INTEL:\n"
    '        if (getenv("GGML_VK_FORCE_COOPMAT") != nullptr) {\n'
    "            return true;\n"
    "        }\n"
    "        // Only allowing Xe2/Xe3 GPU and integrated Xe GPUs at the moment",
    "Intel coopmat gate",
)

override = r'''
        // [test patch] warptile overrides for tuning experiments
        {
            auto parse_tile = [](const char * s, std::vector<uint32_t> & out) -> bool {
                std::vector<uint32_t> v;
                std::string str(s);
                size_t pos = 0;
                while (pos <= str.size()) {
                    size_t c = str.find(',', pos);
                    if (c == std::string::npos) {
                        c = str.size();
                    }
                    v.push_back((uint32_t) std::stoul(str.substr(pos, c - pos)));
                    pos = c + 1;
                }
                if (v.size() != out.size()) {
                    std::cerr << "ggml_vulkan: ignoring warptile override with " << v.size() << " values, need " << out.size() << std::endl;
                    return false;
                }
                out = v;
                return true;
            };
            if (const char * s = getenv("GGML_VK_L_WARPTILE_MMQ")) {
                if (parse_tile(s, l_warptile_mmq)) {
                    l_mmq_wg_denoms = { l_warptile_mmq[1], l_warptile_mmq[2], 1 };
                    l_align = l_warptile_mmq[3];
                    std::cerr << "ggml_vulkan: l_warptile_mmq override " << s << std::endl;
                }
            }
            if (const char * s = getenv("GGML_VK_L_WARPTILE")) {
                if (parse_tile(s, l_warptile)) {
                    l_wg_denoms = { l_warptile[1], l_warptile[2], 1 };
                    std::cerr << "ggml_vulkan: l_warptile override " << s << std::endl;
                }
            }
            if (getenv("GGML_VK_PRINT_WARPTILES")) {
                auto pr = [](const char * n, const std::vector<uint32_t> & t) {
                    std::cerr << "ggml_vulkan: " << n << " =";
                    for (auto x : t) { std::cerr << " " << x; }
                    std::cerr << std::endl;
                };
                pr("l_warptile", l_warptile);
                pr("l_warptile_mmq", l_warptile_mmq);
                pr("m_warptile", m_warptile);
                pr("m_warptile_mmq", m_warptile_mmq);
            }
        }

        const bool use_cm1_int = device->coopmat_int_support &&'''

src = replace_once(src, "\n        const bool use_cm1_int = device->coopmat_int_support &&", override, "use_cm1_int anchor")
open(path, "w", encoding="utf-8").write(src)
print("test-tuning-patch: patched", path)
