"""TEST ONLY patch for the A380 matrix-core investigation (llama.cpp Vulkan backend).

Switches (environment variables, or KEY=VALUE lines in a tuning file that is read
when the Vulkan library loads; file values override the environment, KEY= unsets):

  GGML_VK_TUNING_FILE              tuning file path (default /root/.cache/vk-tuning.env)
  GGML_VK_FORCE_COOPMAT=1          use KHR cooperative matrices on pre-Xe2 Intel
  GGML_VK_FORCE_CM1_INT=1          use the int8 cooperative-matrix path for quantized
                                   matmul (upstream: AMD RDNA3/4 only)
  GGML_VK_{L,M,S}_WARPTILE         override f16/f32 matmul warptiles (11 values)
  GGML_VK_{L,M,S}_WARPTILE_MMQ     override quantized matmul warptiles (11 values)
  GGML_VK_PRINT_WARPTILES=1        print the warptiles in use

Warptile order (mul_mm.comp spec constants): BLOCK_SIZE, BM, BN, BK, WM, WN, WMITER,
TM, TN, TK, WARP (WARP is also the required subgroup size). Workgroup denominators
follow BM/BN.
"""
import sys

path = sys.argv[1]
src = open(path, encoding="utf-8").read()


def replace_once(text, old, new, what):
    if text.count(old) != 1:
        sys.exit(f"test-tuning-patch: expected one {what} in {path}, found {text.count(old)}")
    return text.replace(old, new)


# 1. Load the tuning file into the environment when the library loads.
loader = r'''#include <cstdlib>
#include <fstream>
// [test patch] load KEY=VALUE overrides before any device is created
static const int ggml_vk_tuning_file_loaded = []() {
    const char * p = getenv("GGML_VK_TUNING_FILE");
    std::ifstream f(p ? p : "/root/.cache/vk-tuning.env");
    std::string line;
    while (std::getline(f, line)) {
        if (line.empty() || line[0] == '#') {
            continue;
        }
        size_t eq = line.find('=');
        if (eq == std::string::npos) {
            continue;
        }
        std::string k = line.substr(0, eq), v = line.substr(eq + 1);
        if (v.empty()) {
            unsetenv(k.c_str());
        } else {
            setenv(k.c_str(), v.c_str(), 1);
        }
        std::cerr << "ggml_vulkan: tuning file: " << line << std::endl;
    }
    return 0;
}();

uint32_t get_subgroup_size(const std::string &pipeline_name, const vk_device_architecture &arch) {'''
src = replace_once(src, "uint32_t get_subgroup_size(const std::string &pipeline_name, const vk_device_architecture &arch) {", loader, "get_subgroup_size definition")

# 2. Opt-in matrix cores on pre-Xe2 Intel.
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

# 3. Warptile overrides, and the int8 coopmat opt-in.
block = r'''
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
            struct tile_override { const char * env; std::vector<uint32_t> * tile; std::array<uint32_t, 3> * denoms; bool sets_align; };
            const tile_override overrides[] = {
                { "GGML_VK_L_WARPTILE",     &l_warptile,     &l_wg_denoms,     false },
                { "GGML_VK_M_WARPTILE",     &m_warptile,     &m_wg_denoms,     false },
                { "GGML_VK_S_WARPTILE",     &s_warptile,     &s_wg_denoms,     false },
                { "GGML_VK_L_WARPTILE_MMQ", &l_warptile_mmq, &l_mmq_wg_denoms, true  },
                { "GGML_VK_M_WARPTILE_MMQ", &m_warptile_mmq, &m_mmq_wg_denoms, false },
                { "GGML_VK_S_WARPTILE_MMQ", &s_warptile_mmq, &s_mmq_wg_denoms, false },
            };
            for (const auto & o : overrides) {
                if (const char * s = getenv(o.env)) {
                    if (parse_tile(s, *o.tile)) {
                        *o.denoms = { (*o.tile)[1], (*o.tile)[2], 1 };
                        if (o.sets_align) {
                            l_align = (*o.tile)[3];
                        }
                        std::cerr << "ggml_vulkan: " << o.env << " override " << s << std::endl;
                    }
                }
            }
            if (getenv("GGML_VK_PRINT_WARPTILES")) {
                auto pr = [](const char * n, const std::vector<uint32_t> & t) {
                    std::cerr << "ggml_vulkan: " << n << " =";
                    for (auto x : t) { std::cerr << " " << x; }
                    std::cerr << std::endl;
                };
                pr("l_warptile", l_warptile);
                pr("m_warptile", m_warptile);
                pr("s_warptile", s_warptile);
                pr("l_warptile_mmq", l_warptile_mmq);
                pr("m_warptile_mmq", m_warptile_mmq);
                pr("s_warptile_mmq", s_warptile_mmq);
                pr("l_warptile_mmq_cm1_int", l_warptile_mmq_cm1_int);
                std::cerr << "ggml_vulkan: coopmat_int_support=" << device->coopmat_int_support
                          << " int MxNxK=" << device->coopmat_int_m << "x" << device->coopmat_int_n << "x" << device->coopmat_int_k << std::endl;
            }
        }

        const bool use_cm1_int = device->coopmat_int_support &&
                                 (device->architecture == AMD_RDNA3 || device->architecture == AMD_RDNA4 ||
                                  getenv("GGML_VK_FORCE_CM1_INT") != nullptr);
'''
src = replace_once(
    src,
    "\n        const bool use_cm1_int = device->coopmat_int_support &&\n"
    "                                 (device->architecture == AMD_RDNA3 || device->architecture == AMD_RDNA4);\n",
    block,
    "use_cm1_int definition",
)

open(path, "w", encoding="utf-8").write(src)
print("test-tuning-patch: patched", path)
