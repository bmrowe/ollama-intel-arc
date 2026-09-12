# Hybrid CPU+GPU MoE on an i5-13500 + Arc A380

Running a 35B mixture-of-experts model that does not fit in 6 GB of VRAM, by
keeping attention on the A380 and the routed experts in system RAM.

> ⛔ **Retired 2026-09-12 — llama-server is no longer deployed.** The Frigate GenAI
> backend was reverted to the `ollama` container (`uberchuckie/ollama-intel-gpu:dev`,
> `qwen2.5vl:3b`) on **192.168.1.2:11434**, as one variable in the reset investigation.
> `llama-server` is `Exited`, and the 35B described here has not been the running model
> since **2026-08-16**, when it was rolled back to the dense 4B. See
> **[crash-analysis-2026-09-12.md](crash-analysis-2026-09-12.md)** for why, the measured
> reset history, and what has to hold before this can be reinstated.
>
> Kept for its **analysis and measurements**, which remain load-bearing. Everything here
> describing the live deployment — the container, `192.168.1.2:8080`, model paths, Frigate
> and Mealie wiring — is historical.

**This replaced the 4B in place.** One model now serves Frigate, Mealie and chat
on `192.168.1.2:8080`. The 4B-era doc is [README.md](README.md); this supersedes
its deployment section but not its analysis. Rollback args are
[below](#rollback).

Same principle as before: no custom image. Upstream's prebuilt
`ghcr.io/ggml-org/llama.cpp:server-vulkan`, driven entirely by configuration.

Measured 2026-08-02 on: Unraid, i5-13500, 128 GB DDR4-3200, Intel Arc A380,
`/dev/dri/renderD129`. llama.cpp build `11924d4c1 (10223)`.

**Deployment reconciled against the running container 2026-08-12, re-verified
2026-08-14.** [Deployment](#deployment) is the live values.

> **2026-08-14: the [MTP swap](#the-mtp-swap) was executed and rolled back.** Six
> restarts, every one verified against `drm-total-local0`, no fence timeouts, no
> lockup. Production is back on `HauhauCS` + `-ncmoe 38`, within 7.5 MiB of where it
> started. **It does not pay** — the draft context costs 782 MiB and the `UD-` quant
> is ~10% slower, so MTP nets parity while costing abliteration. Several
> recommendations in this file are withdrawn as a result; each is annotated in
> place. Start at
> [The 2026-08-14 MTP experiment](#the-2026-08-14-mtp-experiment--measured-and-it-does-not-pay).

> ⚠ **The deployed config differs from the tuning recommendations below on
> purpose.** The Unraid host hard-locked twice (Aug 4, Aug 10) from VRAM
> exhaustion, and four settings — `-ub 512`, `q8_0` KV, `-np 1`, `-ncmoe 38` — are
> the fix. **The configuration this file's tuning sections recommend is the one
> that crashed the box.** Read
> [Deployed vs. measured](#deployed-vs-measured--this-is-a-crash-fix-not-drift)
> before changing anything.
>
> **There is no config freeze.** An earlier revision of this block declared one
> until ~Aug 24; it was retired on 2026-08-14 and the calendar is not a
> protection. The rule that actually carries the risk is **one variable per
> restart, with `drm-total-local0` checked after every one** — each delta stays
> attributable and each step individually reversible. See
> [the retired freeze note](#the-freeze-retired).
>
> Every performance number in this file was taken on the pre-crash config and has
> not been re-baselined.

---

## Result

> Measured on the 2026-08-02 configuration. The container has since drifted —
> `-ub 512`, `-t 12`, `-np 1`, q8_0 KV — and **has not been re-baselined.** Treat
> these as the reference point the drift should be measured against, not as
> current throughput.
>
> **Partially re-baselined 2026-08-14 (text only).** Generation on the deployed
> config is **12.48 t/s, best of 8** — neither the 12.5 headline nor the 13.07 q8_0
> probe reproduced, and both were single samples. Contention from Frigate spreads
> throughput ~9%, so **never compare single samples**; take at least five. The
> per-event and prefill figures below are still un-re-baselined.

`Qwen3.6-35B-A3B` abliterated — **`HauhauCS`, imatrix Q4_K_M**, with its own
matched mmproj. All 40 layers of routed experts on the CPU.

| workload | per call | shape |
|---|---|---|
| **Frigate** | **7.41s** | prefill 85%, ~295 tokens (283 image) |
| **chat** | ~36s/turn | generation 83%, 5–8s to first token |
| **Mealie** | ~96s | generation 76%, image capped at 2048 tokens |

| | 4B (previous) | 35B unified |
|---|---|---|
| Frigate per event | 6.3s | **7.41s** |
| prefill | 99 t/s | ~46 t/s |
| generation | 23.2 t/s | **12.5 t/s** |
| image tokens | 556 | 283 |
| duty cycle @ **42 ev/hr peak** | ~7.3% | **~8.6%** |

Only 18% slower per event than the 4B, for a model 9x its size.

> **The `~347 ev/hr` figure this file was built on is wrong.** Measured from
> Frigate's own API over 24h on 2026-08-12: **287 events, 273 described, mean
> 12/hr, peak 42/hr** (09:00–10:00). That is **8.3x** lower, and it collapses
> every duty-cycle number here. See [Event rate](#event-rate-the-real-numbers).
> The per-event latencies are unaffected — only the rate they are multiplied by.

### Quant choice: imatrix Q4_K_M, not K_P

Three abliterated builds were tried. `HauhauCS` wins on all three axes that matter:

| | quant | template | mmproj |
|---|---|---|---|
| Unsloth (base, not abliterated) | `UD-` dynamic | correct | separate |
| prithivMLmods | **plain Q4_K_M, no imatrix** | **208-byte stub** | none in GGUF repo |
| **HauhauCS** | **imatrix Q4_K_M** | **correct, 7764 B** | **matched, included** |

Measured head-to-head against prithivMLmods on identical images: prefill identical
(283 tokens, ~45 t/s), generation identical (12.48 vs 12.72 t/s — noise). The only
difference under a *loose* prompt was verbosity (35 vs 30 output tokens); under
the production prompt both produce ~10–15 and the gap disappears. So imatrix
quality is free here.

**Do not take the K_P quants.** They are 5–15% larger, and generation is
bandwidth-bound on expert reads — 5–15% more bytes on exactly the bottleneck path,
for ~12.5 -> ~11.4 t/s. The parent README's Q6_K result also warns that unusual
quant formats cost more than file size predicts on this hardware, and K_P's CPU
dequant path is less likely to be as optimised as stock Q4_K_M's AVX-VNNI kernels.

Text-only throughput, measured during tuning before vision was added:

| | start | tuned |
|---|---|---|
| generation | 10.48 t/s | **15.19 t/s** (MTP) |
| prefill (4K) | 85.67 t/s | **109.06 t/s** |

**MTP is not in the deployed config.** It was ruled out on the belief that
`--mmproj` and MTP are mutually exclusive, as is `-np > 1`, and to dodge
[llama.cpp#22867](https://github.com/ggml-org/llama.cpp/issues/22867), where
MTP + vision corrupts slot positions and OOMs.

> **That reasoning is now stale — re-test it.** See
> [MTP + vision is fixed upstream](#mtp--vision-is-fixed-upstream).

### Prefill collapses on short prompts

The most counter-intuitive result here, and the reason Frigate is expensive:

| prompt | prefill |
|---|---|
| 283 tokens (Frigate) | **~46 t/s** |
| 556 tokens | ~51 t/s |
| 4096 tokens | **109 t/s** |

Same model, same flags, 2.4x spread. At 283 tokens each of the 256 experts sees
~9 tokens; at 4096 it sees ~128. Fine-grained MoE is at its worst on short
prompts, which is exactly what Frigate sends. **Do not quote the 109 t/s figure
for image workloads.**

---

## The number that governs everything

**Active expert bytes per token**, not model file size. With experts on CPU,
generation speed is set by how much expert weight is read per token, and that is
determined by routing granularity:

| model | layers | experts | top-k | active | **MB/token** |
|---|---|---|---|---|---|
| **Qwen3.6-35B-A3B** | 40 | 256 | 8 | 3.1% | **604** |
| Gemma 4 26B-A4B | 30 | 128 | 8 | 6.3% | 856 |
| GPT-OSS 20B | 24 | 32 | 4 | 12.5% | 1266 |

GPT-OSS 20B is the smallest download and the **slowest of the three here** — it
reads 2.1x more expert weight per token than the 35B because it is coarse-grained.
Derivation for Qwen: `8 experts x 3 matrices x 2048 hidden x 512 moe_intermediate
= 25.2M params/layer x 40 layers = 1.007B active x ~0.6 B/param (Q4_K_M)`.

Corollary, tested against Kimi K3 (2.8T total, **104B active**, ~540 GB at the
smallest quant): total parameters are irrelevant, active parameters are
disqualifying. K3 would read ~55 GB/token — about 0.4 t/s if it fit, which it
does not.

Qwen3.6-35B-A3B also wins on KV: it is a **hybrid linear-attention model** (full
attention only every 4th layer, `num_key_value_heads: 2`, `head_dim: 256`), so KV
is ~20 KB/token — ~400 MB at 32K context.

---

## Measured hardware ceilings

### CPU bandwidth is ~20 GB/s, not the ~40 GB/s the spec implies

Dense `Qwen3-VL-4B-Q4_K_M` (2.32 GiB) at `-ngl 0`, which reads all weights per
token and works as a STREAM proxy:

| `-t` | pp512 | tg128 |
|---|---|---|
| 4 | 57.13 | 7.59 |
| 6 | 64.66 | 7.53 |
| 8 | 67.51 | 7.66 |
| 10 | 69.36 | 8.03 |
| **14** | **74.67** | **8.07** |

`8.07 x 2.32 GiB = ~20.1 GB/s` — **39% of the 51.2 GB/s theoretical**. RAM is
confirmed at a *configured* 3200 MT/s (`dmidecode -t 17`), so this is not a
downclock; the likely cause is a 2T command rate from 8 ranks (4x dual-rank DIMMs)
on 2 channels.

**Generation is flat across thread count** (+7% over a 3.5x sweep) — it is
bandwidth-bound. Prompt processing scales properly. Use `-t 14`.

**Do not pin to P-cores.** An early prediction that E-cores would act as barrier
stragglers, and that `--cpuset-cpus=0,2,4,6,8,10` (6 P-cores) would win, was
**wrong** — it costs ~7% tg and ~14% pp against `-t 14`. P-cores are `0-11`,
E-cores `12-19` (`/sys/devices/cpu_core/cpus`).

### MoE expert gather runs at ~6.5–7.4 GB/s, a third of sequential

The real ceiling, and the price of fine-grained routing — 8 discontiguous slices
per matrix per layer, scattered across 19 GB.

| config | tg128 | implied CPU-side bandwidth |
|---|---|---|
| `-ngl 99 -ncmoe 40` (experts on CPU) | 10.76 | 604 MB x 10.76 = **6.5 GB/s** |
| `-ngl 0` (everything on CPU) | 5.90 | ~1.25 GB x 5.90 = **7.4 GB/s** |

The two agree, which is what makes this the ceiling rather than an artifact.
The property that makes this model fast on paper (3.1% active) is the same one
that hurts locality.

---

## Tuning, in order of what it was worth

### `-ub 2048` — +27% prefill on long prompts, and it crashed the box

> ⛔ **Do not apply this.** `-ub 2048` adds **1.0–1.5 GiB of compute buffers**, and
> it is the largest single contributor to the VRAM exhaustion that hard-locked the
> host on Aug 4 and Aug 10. Deployed value is **512** and must stay there. The
> measurements below are real; the recommendation is withdrawn. See
> [Deployed vs. measured](#deployed-vs-measured--this-is-a-crash-fix-not-drift).
>
> Note also what the table below already showed and this section under-read at the
> time: `-ub 4096` **OOMed outright** at 4,068,474,880 bytes. `-ub 2048` was not
> comfortably inside the envelope, it was one step from the edge — on a card whose
> total is 5.945 GiB.

llama-bench defaults to `-b 2048 -ub 512`, far too small for CPU+GPU MoE. At
`-ub 512` with 8-of-256 routing each expert sees ~16 tokens per batch — GEMV cost
for GEMM-sized weight reads. At `-ub 2048` it is ~64.

`-p 4096 -n 0 -r 1 -ncmoe 38`:

| `-ub` | pp4096 | 4K prompt |
|---|---|---|
| 512 | 85.67 | 47.8s |
| 1024 | 102.99 | 39.8s |
| **2048** | **109.06** | **37.6s** |
| 4096 | OOM (4,068,474,880 B) | — |

Diminishing hard (+20%, then +5.9%). **`-b` alone does nothing** — raising it
2048 -> 4096 with `-ub` fixed changed 86.09 -> 85.67. `-b` is the logical batch
chopped into `-ub`-sized physical batches; the physical batch sets the GEMM shape.

Note this barely helps Frigate, whose prompts are ~283 tokens.

### MTP — +43% generation, ruled out for vision, now unblocked

> ⚠ **The +43% does not survive contact with the model that has the head.** Measured
> 2026-08-14: MTP delivers +16.6% at default sampling on the `UD-` build, and the
> `UD-` build is ~10% slower to begin with, so the net against `HauhauCS` is
> **parity**. The 0.823 acceptance below also did not reproduce — the best observed
> was 0.620, fully greedy, and acceptance falls with temperature. See
> [The 2026-08-14 MTP experiment](#the-2026-08-14-mtp-experiment--measured-and-it-does-not-pay).
> The numbers below are real; read them as a delta on `UD-`, not as a gain over the
> deployed config.

The MTP head ships inside the `-MTP-GGUF` files as `blk.40.nextn.*` and is
**silently discarded** without `--spec-type draft-mtp` (logged as
`model has unused tensor blk.40.nextn.eh_proj.weight -- ignoring`). When it loads
you get `common_speculative_init_result: creating MTP draft context` and a
`draft acceptance` line per request.

| `--spec-draft-n-max` | tg | acceptance | mean len |
|---|---|---|---|
| off | 10.60 | — | — |
| **2** | **15.19** | **0.823** | 2.65 |
| 4 | 14.25 | 0.648 | 3.59 |

**Deeper is worse.** At n-max 4 acceptance collapses to 65% and `tg_3s` dips to
~10.7 mid-generation. On a bandwidth-bound CPU-MoE setup a *rejected* draft token
costs the same expert reads as an accepted one, so acceptance rate matters more
than draft depth.

**MTP does not cost prefill**: 109.17 t/s over 5302 tokens with it on, against
109.06 without.

A prediction that MTP would only return 1.1–1.3x (on the theory that expert reads
scale with the union of experts routed across the draft window) was **too
pessimistic**. Consecutive tokens in fluent text route to heavily overlapping
experts, so the union grows far slower than worst case.

This is the single biggest thing given up for vision, and **it hurts chat most** —
chat generates ~314 tokens/turn where Frigate generates ~25. Re-check after
llama.cpp updates; upstream wording is "not *yet* supported".

#### MTP + vision is fixed upstream

Checked 2026-08-12. **The whole chain of MTP+vision bugs is closed**, all fixed
before the deployed build:

| issue | what | closed |
|---|---|---|
| [#22867](https://github.com/ggml-org/llama.cpp/issues/22867) | slot position corruption + OOM — *the one cited above* | 2026-05-10 |
| [#23233](https://github.com/ggml-org/llama.cpp/issues/23233) | crash evaluating images with MTP on Qwen3.6 | 2026-05-29 (via [#23643](https://github.com/ggml-org/llama.cpp/pull/23643)) |
| [#23371](https://github.com/ggml-org/llama.cpp/issues/23371) | MTP+vision OOM during mmproj restore | 2026-05-20 |

#22867's closing comment is a direct confirmation on this workload: MTP with
multimodal input working after the fix. The deployed build (`11924d4c1`, ~Aug 2)
postdates all three.

Current `master` shows **no mutual exclusion**: `common/arg.cpp` resolves `mmproj`
and `mtp` sidecars side by side, and the server README lists `draft-mtp` under
`--spec-type` with no vision caveat.

**And the second blocker removed itself.** MTP needs a single slot, and the
deployed config has already drifted to `N_PARALLEL 1`.

So the +43% is plausibly available now, on the config as it stands:

```
LLAMA_ARG_SPEC_TYPE        draft-mtp
LLAMA_ARG_SPEC_DRAFT_N_MAX 2
```

#### But the deployed model has no MTP head

Checked 2026-08-12 against the GGUF tensor table. **`HauhauCS` does not ship
`blk.40.nextn.*`.** Layers run 0–39 and stop:

```bash
dd if=/mnt/cache/appdata/llama-models/<model>.gguf bs=1M count=32 2>/dev/null \
  | tr -c '[:print:]' '\n' | grep -E 'nextn|blk\.39\.' | sort -u
```

Returns the full `blk.39.*` set — attention, `ffn_*_exps`, `ffn_*_shexp` — and no
`nextn`. **Always include a known-present tensor as a positive control**; an empty
result otherwise cannot be distinguished from a broken pipeline.

**`strings` is not installed on Unraid** (no binutils, same as `jq` and `python3`).
`tr -c '[:print:]' '\n'` is the substitute. An earlier attempt with `strings`
returned `0` and looked like a clean negative — it was an empty pipe.

Tensor names live in the GGUF header, so 32 MB is enough; there is no need to read
21 GB.

So MTP costs a **model swap**, not a config change. Surveying every GGUF in
`/models`:

```bash
for f in /mnt/cache/appdata/llama-models/*.gguf; do
  printf '%-72s %s\n' "$(basename "$f")" \
    "$(dd if="$f" bs=1M count=32 2>/dev/null | tr -c '[:print:]' '\n' | grep -c nextn)"
done
```

| file | `nextn` |
|---|---|
| **`Qwen3.6-35B-A3B-UD-Q4_K_M.gguf`** | **5** |
| `Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf` | 0 |
| `qwen3.6-35b-a3b-uncensored-aggressive-q4_k_m.gguf` | 0 |
| the two 4B files, all three mmproj files | 0 |

**The Unsloth build has the head and is already on disk**, as is its projector
`mmproj-Qwen3.6-35B-F16.gguf`. Confirms the [gotcha](#gotchas): the filename omits
`-MTP` and only the repo name says so.

### The MTP swap

> ⛔ **Done, measured, and rolled back on 2026-08-14. Do not repeat it.** The draft
> context costs **782 MiB**, and the `UD-` quant generates ~10% slower than
> `HauhauCS`, so MTP's gain buys nothing but parity — at default sampling it
> measured **13.08 against 12.48**, and it costs abliteration. Full numbers in
> [The 2026-08-14 MTP experiment](#the-2026-08-14-mtp-experiment--measured-and-it-does-not-pay).
>
> The procedure below is still correct, and the staged approach it describes is what
> made the rollback safe. It is the *conclusion* that is withdrawn.

Everything needed is local — no download. It is the [rollback to
Unsloth](#to-the-unsloth-35b) plus two variables:

| Key | Value |
|---|---|
| `LLAMA_ARG_MODEL` | `/models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` |
| `LLAMA_ARG_MMPROJ` | `/models/mmproj-Qwen3.6-35B-F16.gguf` |
| `LLAMA_ARG_SPEC_TYPE` | `draft-mtp` |
| `LLAMA_ARG_SPEC_DRAFT_N_MAX` | `2` |

`N_PARALLEL` must stay `1` — already true. `ALIAS` stays `qwen3-vl`, so **no
Frigate or Mealie config changes**.

| | gain | cost |
|---|---|---|
| Unsloth `UD-Q4_K_M` + MTP | ~10% per event (measured), `UD-` layer-aware quant, up to +43% generation | **loses abliteration** |

**The abliteration loss is the real decision**, and it is not a performance
question — the uncensored build was chosen deliberately. If that matters, the
alternative is an abliterated build that ships the MTP head, which has not been
looked for. `n-max 2` is the measured optimum; 4 was worse.

#### Remaining caveats

- **The measured +43% was text-only, at `-np 1`, without `--mmproj` loaded.** Draft
  acceptance on Frigate's ~25-token outputs is a different regime from the fluent
  prose it was measured on, and Frigate is prefill-dominated anyway (85%) — MTP
  does not touch prefill. **Chat is where this pays**, at 83% generation.
- Fixed upstream is not the same as fixed on Vulkan with experts on CPU. Watch
  `dmesg -T` for fence timeouts on the first image after enabling it.
- Confirm it actually loaded: `common_speculative_init_result: creating MTP draft
  context` on startup, and a `draft acceptance` line per request. Without them the
  head is **silently discarded** as `model has unused tensor blk.40.nextn.*`.

### `-ncmoe` — worth 3.4%. Not worth tuning.

> **Verdict confirmed 2026-08-14, magnitude revised down.** On the deployed q8_0
> config, `38` vs `40` is **~1%** (12.48 best-of-8 vs 12.33 best-of-3, overlapping
> distributions) and each layer is worth **506 MiB**, confirmed three times. So
> `-ncmoe 40` is the cheap way to buy a gigabyte of headroom, not a 3.4% sacrifice.
> The sweep below was taken on the pre-crash config with f16 KV and its absolute
> numbers do not transfer.

`-ngl 99 -t 14`, default `-ub`:

| `-ncmoe` | expert layers on GPU | tg128 |
|---|---|---|
| 40 | 0 | 10.76 |
| 38 | 2 | 10.67 |
| 36 | 4 | 10.99 |
| 34 | 6 | 11.13 |
| 32 | — | OOM (914,882,564 B) |

Moving 15% of expert traffic from 20 GB/s RAM to 186 GB/s VRAM returned **+3.4%**
where bandwidth math predicts ~13%. Saved reads and added per-layer round-trips
roughly cancel at the margin.

**Set it to 40 and stop thinking about it.** The 3.4% is worth less than the
~966 MB of headroom, which the `-ub 2048` compute buffer and 32K of KV both want.

### The GPU is worth 1.89x — keep it

An early reading of the flat `-ncmoe` sweep as "sync dominates, the GPU is
contributing nothing" was **wrong**, and the `-ngl 0` control disproved it:
**5.90 t/s CPU-only against 11.13 hybrid**.

Worth noting *why* the hybrid split works better here than the specs suggest: the
A380 achieves ~53 GB/s effective (23.2 t/s on the 4B, ~30% of its 186 GB/s), so it
is only ~2.6x the CPU rather than the ~9x the spec sheets imply. A launch-bound
GPU and a gather-bound CPU are unusually well matched.

---

## Deployment

**Replaces the `llama-server` container in place** — same name, same `br0` IP
`192.168.1.2`, same image. Two containers were considered and rejected: MoE base
residency is ~2.5 GB (from the `-ncmoe 32` OOM boundary) and the 4B vision
container measured 3,950 MiB, which is ~6.2 GB against a **5,479 MiB** budget.
They cannot coexist on this card.

**Everything is environment variables.** llama.cpp reads 138 `LLAMA_ARG_*` vars;
CLI args override them, so mixing the two hides which is live.

This table is the **container as actually running**, captured from the Unraid
`docker run` on 2026-08-12. Six values differ from the measured optima in the
tuning sections above — see [Deployed vs. measured](#deployed-vs-measured) for
which, and why that matters.

| Key | Value |
|---|---|
| `LLAMA_ARG_MODEL` | `/models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf` |
| `LLAMA_ARG_MMPROJ` | `/models/mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-f16.gguf` |
| `LLAMA_ARG_CHAT_TEMPLATE_KWARGS` | `{"enable_thinking":false}` |
| `LLAMA_ARG_ALIAS` | `qwen3-vl` |
| `LLAMA_ARG_DEVICE` | `Vulkan0` |
| `LLAMA_ARG_N_GPU_LAYERS` | `99` |
| `LLAMA_ARG_N_CPU_MOE` | `38` |
| `LLAMA_ARG_THREADS` | `14` |
| `LLAMA_ARG_LOAD_MODE` | `none` |
| `LLAMA_ARG_IMAGE_MIN_TOKENS` | `256` |
| `LLAMA_ARG_IMAGE_MAX_TOKENS` | `1024` |
| `LLAMA_ARG_CTX_SIZE` | `32768` |
| `LLAMA_ARG_N_PARALLEL` | `1` |
| `LLAMA_ARG_FLASH_ATTN` | `on` |
| `LLAMA_ARG_BATCH` | `2048` |
| `LLAMA_ARG_UBATCH` | `512` |
| `LLAMA_ARG_CACHE_TYPE_K` | `q8_0` |
| `LLAMA_ARG_CACHE_TYPE_V` | `q8_0` |
| `LLAMA_ARG_CACHE_RAM` | `-1` |
| `LLAMA_ARG_JINJA` | `1` |
| `LLAMA_ARG_PORT` | `8080` |
| `TZ` | `America/Chicago` |

Extra Parameters: `--device=/dev/dri/renderD129 --restart unless-stopped`

Post Arguments: `--reasoning off`

| Container path | Host path | Mode |
|---|---|---|
| `/models` | `/mnt/cache/appdata/llama-models` | Read Only |
| `/root/.cache` | `/mnt/cache/appdata/ollama-sycl-test/cache` | Read/Write |

**Both volumes are on `/mnt/cache`, not `/mnt/user`** — the parent README documents
`/mnt/user` paths from the 4B era. `/mnt/cache` bypasses the FUSE share and its
parity read-modify-write, so it is the better choice; the README's staging advice
(write to `/tmp`, then `mv`) is about `/mnt/user` and does not apply here.

The shader cache still lives under the old `ollama-sycl-test` directory. Harmless —
it is just a path — but it is not where anyone would look for it.

**Names that are not a simple uppercase of the flag** — these are the ones that
will silently no-op if you guess: `-np` is `N_PARALLEL`, `-b` is `BATCH` (not
`BATCH_SIZE`), `-ub` is `UBATCH` (not `UBATCH_SIZE`), `-ngl` is `N_GPU_LAYERS`,
`-c` is `CTX_SIZE`. Get the authoritative list with:

```bash
docker run --rm ghcr.io/ggml-org/llama.cpp:server-vulkan --help 2>&1 | grep -B1 "env: LLAMA_ARG"
```

**`LLAMA_ARG_JINJA` must be `1`, not empty.** It is a boolean; an empty value is
ambiguous.

**A wrong variable name produces no error.** The server starts happily on
defaults — experts on GPU, 4096 context, no vision — and looks healthy. Always
verify after editing:

```bash
curl -s http://192.168.1.2:8080/props | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('alias      :', repr(d.get('model_alias')))
print('template   :', len(d.get('chat_template','')), '| enable_thinking:', 'enable_thinking' in d.get('chat_template',''))
print('slots      :', d.get('total_slots'), '| n_ctx/slot:', d.get('default_generation_settings',{}).get('n_ctx'))
print('modalities :', d.get('modalities'))
print('model      :', d.get('model_path'))"
```

Expect `'qwen3-vl'` (**`repr()` is deliberate — it exposes a trailing space**,
which would break Frigate's model validation silently), **1 slot x 32768**,
`vision: True`, and a template with an `enable_thinking` branch.

**Template length is build-specific — do not assert 7764.** That is `HauhauCS`'s
value; the Unsloth `UD-` build measured **8057** and is equally correct. The
durable checks are `enable_thinking: True` (a 208-byte stub has no such branch,
see [the template defect](#the-chat-template-defect)) and the
[behavioural test](#verify-it-every-time). A byte count only distinguishes a stub
from a real template — it cannot validate one build against another.

### Check VRAM after every restart

**This is the measurement that predicts whether the box stays up.** Both hard
lockups happened within seconds of a container start, because that is when VRAM is
allocated. Run it on the Unraid host after any config change:

```bash
grep -h drm-total-local0 /proc/$(pgrep -f llama-server | head -1)/fdinfo/* 2>/dev/null | sort -u
head -3 /sys/kernel/debug/dri/1/i915_gem_objects
```

| | expected |
|---|---|
| `drm-total-local0` | **4,468,620 KiB** (4,364 MiB) |
| card total | **6,088 MiB** |
| free | **~1,724 MiB**, or ~1,630 after Frigate's ~101 MiB |

Verified unchanged 2026-08-12 after the `THREADS 14` restart — exact to the KiB.

A second `drm-total-local0: 0` line is a normal idle fd; take the non-zero one.
**Only `local0` reflects card residency.** `drm-total-system0` (~18.8 GB, visible
in `i915_gem_objects` as the shrinkable-objects byte count) is the mmap'd model
registered with the Vulkan device and stays flat across config changes — it misled
an earlier revision of the crash analysis into blaming GTT spill.

Anything materially above ~4.5 GiB means a change enlarged the card footprint.
Below ~600 MiB free is the danger zone the lockups came from.

### Why each setting

| | |
|---|---|
| `N_GPU_LAYERS 99` + `N_CPU_MOE 38` | Everything to GPU, then 38 of 40 layers of routed experts back to CPU. Attention, router, norms and KV stay on the card. |
| `ALIAS qwen3-vl` | **Unchanged from the 4B on purpose.** Frigate validates `model:` against `/v1/models` and fails init silently on mismatch. Zero client config changes in either direction. |
| `IMAGE_MIN_TOKENS 256` | 283 image tokens vs 556 at 512. ~8.7s/event vs ~13.6s. |
| `IMAGE_MAX_TOKENS 1024` | **Prevents a GPU hang.** See [crash](#gpu-hang-on-large-images). |
| `LOAD_MODE none` | Replaces the deprecated `--no-mmap`. No page faults mid-request. |
| `CACHE_RAM -1` | Prompt caching **on** — the inverse of the 4B config. Useless for Frigate (every image unique), but it saves chat ~100s per turn. See [chat](#chat-profile). |
| `FLASH_ATTN on` | Required for the quantized KV now in use. |

---

## Deployed vs. measured — this is a crash fix, not drift

> ⚠ **The crash narrative below is superseded by
> [`crash-analysis-2026-08-16.md`](crash-analysis-2026-08-16.md).** The four load-bearing
> settings stay — they are correct and they did eliminate the fence timeouts. But the
> timestamps and the failure mode are wrong: **Aug 4 was ~06:39–06:44, not 04:02, and
> Aug 10 was ~13:11, not 10:32** (both were read off syslog going quiet, which on an idle
> box means nothing). The box did not hard-lock — it **warm-reset and rebooted itself** in
> 3–8 minutes with `AC BACK` on `Always Off`. A third reset followed on **Aug 16 ~19:28**,
> a week after this fix, with zero GPU errors. And the Docker Auto Update claim below is
> unsupported: metrics show the box running normally through 04:10 on Aug 4.

Six deployed values differ from what the tuning sections above call optimal.
**Four of them are a deliberate stability fix and must not be reverted.**

The Unraid host **hard-locked twice** — Aug 4 04:02 and Aug 10 10:32 — with no
shutdown sequence and no kernel output. Root cause: **VRAM exhaustion on the
A380**, from a config that sat at 5.46–5.96 GiB against a 5.945 GiB card.
Full evidence in `crash-analysis-2026-08-10.md` (syslog Apr 22–Aug 10, Unraid
diagnostics, and an Eaton 5PX power log proving the box drew 255–345 W throughout
the outage — it hung, it did not lose power).

**The crashing configuration is the one the tuning sections above recommend:**
`-ub 2048`, f16 KV, `-np 2`, ctx 32768.

| component | size (crashing config) |
|---|---|
| KV cache, **f16** @ 32k | 2.500 GiB |
| mmproj (f16 vision tower) | 0.838 GiB |
| non-expert weights | 1.539 GiB |
| less `token_embd` + `output` (CPU-resident) | −0.420 GiB |
| compute buffers **@ ubatch 2048** | +1.0 – 1.5 GiB |
| **total** | **5.46 – 5.96 GiB** vs a **5.945 GiB** card |

The escalating fence timeouts in [GPU hang](#gpu-hang-on-large-images) were the
survivable form of the same failure — 5 on Jul 22, 7 on Aug 2, then hard lockups:

```
Jul 22 14:08  Fence expiration time out i915-0000:03:00.0:llama-server  (x5)
Jul 30 19:44  (x3)    Jul 30 19:49  (x4)
Aug  2 17:38  (x7)    Aug  2 17:39  segfault in libggml-cpu-alderlake.so
Aug  4 04:02  >>> hard lockup <<<
Aug 10 10:32  >>> hard lockup <<<
```

### The four settings that are load-bearing

| Setting | Was | Now | Why it changed |
|---|---|---|---|
| `UBATCH` | 2048 | **512** | Compute buffers at `-ub 2048` are **+1.0–1.5 GiB**, the single largest swing item. **Reverting this re-creates the crash.** Costs −27% prefill on long prompts and near-nothing on Frigate's ~283-token ones. |
| `CACHE_TYPE_K/V` | f16 | **`q8_0`** | Halves KV from 2.500 GiB to ~1.25 GiB at 32K. The earlier "predicted to hurt on a dequant-bound card" reasoning was a **performance** prediction; this is a **stability** requirement and outranks it. A text-only probe measured 13.07 t/s against the documented 12.5, so the predicted cost has not shown up. |
| `N_PARALLEL` | 2 | **1** | Fewer slots, less KV. Also a **precondition for MTP**. Cost: a Frigate event can queue behind a ~96s Mealie import. |
| `N_CPU_MOE` | 40 | **38** | **`40` was a no-op.** The model has 40 layers, indices 0–39, so `-ncmoe 40` (and the earlier `48`) put every expert on the CPU anyway — the parameter was never engaged. `38` genuinely places 2 expert layers on the card, *spending* headroom the other three fixes freed. |

`-ncmoe 38` measures **4.26 GiB `drm-total-local0`, 1630 MiB free** — against a
predicted 4.466 GiB, a **0.06% error**, which is what makes the accounting model
above trustworthy rather than a guess.

| `-ncmoe` | expert layers on GPU | local0 | free |
|---|---|---|---|
| **38 (current)** | 2 | **4.26 G** | **1630 MiB** |
| 37 | 3 | 4.75 G | ~1132 MiB |
| 36 | 4 | 5.23 G | ~634 MiB |
| 35 | 5 | 5.72 G | ~136 MiB — too tight |

**36 is the practical floor**, worth ~2% decode per layer. Note this supersedes the
[`-ncmoe` sweep](#-ncmoe--worth-34-not-worth-tuning) above, whose 32-and-below OOM
boundary was measured with f16 KV.

Do not quantize KV below `q8_0`: `q4_0` saves 0.625 GiB, buys exactly one expert
layer (~2%), and costs real accuracy on a vision model.

### The two that are not explained by the crash fix

| Setting | Was | Now | Status |
|---|---|---|---|
| `THREADS` | 14 → 12 | **14 again** | **Resolved 2026-08-12.** Had drifted to 12 for unknown reasons; restored. CPU-only, no VRAM effect, so this was safe to change during the freeze. Cost of 12 was only ~3–4% prefill and ~0% generation, interpolated from the [thread sweep](#cpu-bandwidth-is-20-gbs-not-the-40-gbs-the-spec-implies) (10 → 69.36/8.03, 14 → 74.67/8.07). **Do not confuse `-t 12` with the P-core pinning result** — that was `--cpuset-cpus` restricting the container to *6* logical CPUs, a cgroup restriction, not a thread count. |
| `IMAGE_MAX_TOKENS` | 2048 | **1024** | Not in the crash-fix table, but consistent with it: it bounds submission size. Costs OCR detail on Mealie. Leave it. |

**Changing `THREADS` cannot cause a lockup.** The failure mechanism is VRAM
exhaustion; thread count cannot touch VRAM. That is why it was safe to change
while the four load-bearing settings stayed put.

### The freeze, retired

**Retired 2026-08-14. Recorded for the reasoning, not as guidance.**

`crash-analysis-2026-08-10.md` closes with the reason it was proposed:

> Crash cadence was two per fortnight; clean through ~Aug 18 is one interval,
> ~Aug 24 is two. **Avoid further config changes until then — each one resets the
> clock.**

The fix landed Aug 10, and the argument at the time was that every tuning
suggestion in this file should wait for the uptime window — including the
[MTP swap](#the-mtp-swap), on the grounds that a draft context is an unmeasured
VRAM allocation. The allocation turned out to be measurable in one restart
(**782 MiB**), which is exactly why the argument did not hold.

> **Superseded 2026-08-14.** The freeze was broken deliberately, at 4 days clean —
> less than the 6d 6h crash interval, so uptime alone proved nothing either way. The
> justification was that the freeze protects a *measurement*, while the box is
> protected by *headroom*, and headroom is directly observable in 30 seconds. Six
> restarts, `drm-total-local0` checked after every one, no fence timeouts, no
> lockup — and the accounting model predicted each result to within 0.5%.
>
> **The rule that carried the risk was one variable per restart**, not the calendar.
> The staged sequence — model swap, then `-ncmoe`, then MTP — is what made each
> delta attributable and each step individually reversible. Keep that rule; the
> uptime clock is the weaker of the two protections.

Three other open items from that analysis, none of them config changes to
llama-server:

- **Exclude `llama-server` from Docker Auto Update.** It restarted the container
  unattended at 04:00 and directly triggered the Aug 4 lockup.
- **Remote syslog now works.** It previously pointed at `192.168.1.198` — the box
  itself — which is why both crashes end mid-line. Now goes to a Debian LXC at
  `192.168.1.195`. netconsole, watchdog and hung-task detection are all compiled
  out of Unraid's kernel, so this is the best capture available.
- **The `xe` driver is available** (`/sys/kernel/config/xe/`). If fence timeouts
  return: `i915.force_probe=!56a5 xe.force_probe=56a5`.

### `--reasoning off` is back in Post Arguments

The [thinking trap](#the-thinking-trap) section measured `--reasoning off` as the
*worse* of the two fixes — 100 output tokens of markdown, `finish=length`, length
instructions ignored — and chose `LLAMA_ARG_CHAT_TEMPLATE_KWARGS` instead.

Both are now set at once. `--reasoning off` is a CLI arg and
`CHAT_TEMPLATE_KWARGS` an env var, and llama.cpp treats `--reasoning` as the
*replacement* for the deprecated kwargs path, so which one governs the template is
not obvious from the config.

**Verified benign, 2026-08-12.** With both set, at `max_tokens: 100` and the
production prompt:

```
finish  : stop
out tok : 15
content : 'The person is typing on a keyboard while looking at a computer screen.'
```

15 tokens and `finish=stop` — the good outcome, matching the
`CHAT_TEMPLATE_KWARGS`-only result (~29–41 tokens) rather than the
`--reasoning off`-only failure (100 tokens, `finish=length`, markdown). **The env
var is winning.** No think tags in `content`, no `reasoning_content`.

So the deprecated path still governs even with `--reasoning off` present, and
having both set costs nothing. Two caveats: this was a **text-only** probe, and
the outcome depends on a precedence order that upstream could change in either
direction on any update. Re-run after llama.cpp upgrades.

Test at `max_tokens: 100`, not 30 — Frigate's real value. At 30 a runaway
generation and a concise one both look like they stopped early.

---

## The 2026-08-14 MTP experiment — measured, and it does not pay

**The [MTP swap](#the-mtp-swap) was executed end-to-end and rolled back.** Six
restarts, all verified against `drm-total-local0`. No fence timeouts, no lockup.
**Production ended exactly where it started** — `HauhauCS`, `-ncmoe 38`, within
7.5 MiB (0.17%) of the pre-experiment footprint.

Read this before acting on any MTP or `UD-` recommendation above; several of them
are wrong.

### What was measured

Every restart, in order. All throughput is the same 200-token text prompt.

| # | config | `drm-total-local0` | MiB | generation |
|---|---|---|---|---|
| — | **start:** HauhauCS, `-ncmoe 38` | 4,484,596 KiB | 4,379 | — |
| 1 | UD-, `-ncmoe 38` | 5,073,112 KiB | 4,954 | — |
| 2 | UD-, `-ncmoe 40` | 4,046,924 KiB | 3,952 | 11.22 |
| 3 | UD-, `-ncmoe 40`, **MTP n-max 2** | 4,848,112 KiB | 4,734 | 13.08 |
| 4 | HauhauCS, `-ncmoe 40` | 3,446,672 KiB | 3,366 | 12.28 (n=3) |
| 5 | **end:** HauhauCS, `-ncmoe 38` | 4,476,896 KiB | 4,372 | **12.48 best of 8** |

### The MTP draft context costs 782 MiB

The number [the swap section](#the-mtp-swap) called an unmeasured allocation.
Restart 2 → 3 is the isolated cost: **+801,188 KiB = +782 MiB**.

That is more than a bare MoE layer (~480 MB), so the layer-40 head's experts land
**on the card** — `-ncmoe 40` covers layers 0–39, not 40 — *and* the draft context
carries its own allocation on top. If MTP is ever revisited, try `-ncmoe 41` to
push the head's experts to CPU.

### MTP works. It just starts from further back.

MTP is real and it loaded correctly — `draft_n` and `draft_n_accepted` appear in
the `/v1/chat/completions` `timings` object, which is a better liveness check than
grepping startup logs:

| | generation | acceptance |
|---|---|---|
| UD-, no MTP | 11.22 | — |
| UD- + MTP | **13.08** | 0.547 |

**+16.6% — genuine, and entirely eaten by the quant.** The `UD-` build generates
~10% slower than `HauhauCS` (11.22 against 12.48), for exactly the reason
[the K_P quants were rejected](#quant-choice-imatrix-q4_k_m-not-k_p): a
layer-aware quant is larger per token, and generation is bandwidth-bound on expert
reads. MOE.md predicted "~12.5 → ~11.4" for K_P; `UD-` measured 11.22.

So MTP spends its entire gain climbing back to parity:

| config | generation | abliterated | free VRAM |
|---|---|---|---|
| HauhauCS `-ncmoe 38` | **12.48** | **yes** | ~1,615 MiB |
| UD- + MTP `-ncmoe 40` | 13.08 @ temp 1.0 | no | ~1,253 MiB |

The `UD-` file is also **575 MiB fatter on the card** at the same `-ncmoe`
(restart 1 vs. start) — the layer-aware quant bumps exactly the non-expert tensors
that live on the GPU.

### Acceptance is temperature-dependent, and 0.823 does not reproduce

Same model, same prompt, `-ncmoe 40`, n-max 2:

| temperature | acceptance | generation |
|---|---|---|
| 0.0 | **0.620** | **14.69** |
| 0.7 | 0.555 | 13.79 |
| 1.0 (server default) | 0.547 | 13.08 |

The [MTP table](#mtp--43-generation-ruled-out-for-vision-now-unblocked) reports
**0.823** at n-max 2. Nothing here comes close; the best case is 0.620 fully
greedy. That table's sampling settings are undocumented, and given the dependence
above they are load-bearing — **treat 0.823 as unreproduced.**

**This is why the swap fails on its own rationale.** The case for MTP was that
*chat* is where it pays, at 83% generation. Chat runs at default sampling, which
is where MTP measured **13.08 against HauhauCS's 12.48** — inside the noise band.
Frigate does see a gain at low temperature, but Frigate is 85% *prefill*, and
**MTP does not touch prefill**.

Without MTP, temperature has no effect on throughput at all — sampling does not
change bytes read per token. Only the speculative path is sensitive to it.

### `-ncmoe 38` vs `40` is ~1%, not 6%

An intermediate reading of this experiment claimed `-ncmoe 40` cost 6%. **That was
wrong**, and it came from comparing against the single 13.07 t/s probe below rather
than a fresh measurement.

| | best | median | n |
|---|---|---|---|
| `-ncmoe 38` | 12.48 | 12.24 | 8 |
| `-ncmoe 40` | 12.33 | 12.27 | 3 |

Distributions overlap almost entirely. The original
[sweep's verdict](#-ncmoe--worth-34-not-worth-tuning) — not worth tuning — stands.

Two low outliers at `-ncmoe 38` (11.36, 11.48) against six samples of 12.0–12.5 are
**Frigate contention, not the setting**. Any single-sample throughput comparison on
this box is worthless; take at least five.

### The per-layer VRAM cost is 506 MiB, confirmed three times

| transition | freed | per layer |
|---|---|---|
| UD-, 38 → 40 | 1,026,188 KiB | 501 MiB |
| HauhauCS, 40 → 38 | 1,030,224 KiB | 503 MiB |
| doc's earlier sweep | — | ~490 MiB |

**This makes `-ncmoe 40` the way to buy headroom**, at ~1% throughput rather than
the 3.4% the old sweep implied. It is how you would pay for
`IMAGE_MAX_TOKENS 2048` if [Mealie's OCR](#open-questions) ever matters.

`-ncmoe 36` and below remain off the table — see
[the ceiling](#the-four-settings-that-are-load-bearing). At 506 MiB/layer, `36`
lands at ~595 MiB free (the lockup zone) and `34` **exceeds the card outright**.

### The 13.07 / 12.5 t/s baselines do not reproduce

Best of eight on the identical config, same day, is **12.48**. Neither the 12.5
headline nor the 13.07 q8_0 probe was reachable. Both were single samples; given
the contention spread above, that is probably sufficient explanation. **12.48 is
the current reference point** for `HauhauCS` + `-ncmoe 38` + q8_0 KV.

### What was not tested

**Every measurement above is text-only.** MTP was never exercised with an image, so
[the vision caveat](#remaining-caveats) is still open — upstream fixed MTP+vision,
but not verified here on Vulkan with experts on CPU.

### If MTP is revisited

The prize is unchanged but needs a different file: **an abliterated 35B-A3B that
ships the `nextn` head.** That would put MTP's +16–31% on top of the faster base
quant instead of spending it to reach parity. Surveying for one is the prerequisite;
`HauhauCS` does not ship it and `UD-` costs abliteration.

---

## The thinking trap

**Qwen3.6 defaults to reasoning mode, and it silently destroys Frigate.**

The chat template emits `<|im_start|>assistant\n<think>\n` unless `enable_thinking`
is explicitly false. Frigate sends `max_tokens: 100`, the model spends all 100 on
reasoning, and the response is:

```
"finish_reason": "length"
"content": ""
"reasoning_content": "The user wants a one-sentence description of the ..."
```

**Empty description, HTTP 200, nothing in the log.** Same failure class as the
`num_ctx` truncation in the parent README.

Two fixes were tried and **both official-looking ones failed**:

| attempt | result |
|---|---|
| `--reasoning-budget 0` | **No effect.** Thinking stayed on. Measured across two restarts. |
| `--reasoning off` | Reasoning off, but **output balloons to 100 tokens of markdown** and ignores length instructions. |
| **`LLAMA_ARG_CHAT_TEMPLATE_KWARGS={"enable_thinking":false}`** | **Works.** ~29–41 tokens, `finish=stop`. |

The `--reasoning off` result is the nasty one. llama.cpp *deprecates*
`--chat-template-kwargs` in favour of it and prints a warning on every start — but
the replacement produces worse output on this template. Same prompt, same image:

| | output |
|---|---|
| `--reasoning off` | **100 tok, `finish=length`**, markdown breakdown |
| `LLAMA_ARG_CHAT_TEMPLATE_KWARGS` | 41 tok, `finish=stop`, one sentence |

**Ignore the deprecation warning.** Deprecated-and-working beats current-and-broken.

### Verify it, every time

Sends **no** `chat_template_kwargs` — simulating exactly what Frigate and Mealie
send. Run from a Mac on the LAN; `br0` is unreachable from the Unraid shell.

```bash
curl -s -m 120 http://192.168.1.2:8080/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"qwen3-vl","max_tokens":30,"messages":[{"role":"user","content":"Say hello."}]}' | python3 -c "
import json,sys
m=json.load(sys.stdin)['choices'][0]['message']
c=m.get('content') or ''; r=m.get('reasoning_content') or ''
if not c and r: print('BROKEN - reasoning consumed the budget:', repr(r[:60]))
elif '<think>' in c: print('BROKEN - think tags leaking into content:', repr(c[:80]))
elif c: print('OK - clean content:', repr(c))
else: print('BROKEN - empty response')"
```

Checking only that `content` is non-empty is **not sufficient** — a broken
template puts `<think>` tags inside `content` and passes that test.

---

## The chat template defect

**Check this on every model swap.** Third-party single-file GGUF uploads
frequently ship a **stub chat template**. prithivMLmods' build embeds a
**208-byte** bare ChatML loop — no `enable_thinking` branch, no vision markers,
no tool calling. The correct one is ~7,764 bytes.

Symptoms: `LLAMA_ARG_CHAT_TEMPLATE_KWARGS` silently does nothing, and `<think>`
tags leak into `content` (`'<think>\n\n</think>\n\nThe object — a white SUV...'`).
Frigate would store that verbatim as the description.

HauhauCS ships the correct template embedded, so **`LLAMA_ARG_CHAT_TEMPLATE_FILE`
is not needed with the current model.** If a future build regresses, fetch the
template from the matching safetensors repo:

```bash
cd /tmp && wget -c "https://huggingface.co/prithivMLmods/Qwen3.6-35B-A3B-Uncensored-Aggressive/resolve/main/chat_template.jinja" -O qwen36-uncensored.jinja && mv qwen36-uncensored.jinja /mnt/cache/appdata/llama-models/
```

Then set `LLAMA_ARG_CHAT_TEMPLATE_FILE=/models/qwen36-uncensored.jinja`. Templates
are interchangeable across these builds since they share a base model.

Check with the `/props` command above: **7764 and `enable_thinking: True`**.
If it says 208, you need the file.

---

## GPU hang on large images

> **The root cause in this section was wrong.** It reads the fence timeouts as a
> submission-size problem — "not VRAM". The later
> [crash analysis](#deployed-vs-measured--this-is-a-crash-fix-not-drift), which has
> a VRAM accounting model validated to 0.06%, identifies **VRAM exhaustion** as the
> cause of the whole escalating series, ending in two hard lockups. Large images
> were a *trigger* — they inflate the compute buffer — on a card already at 99% of
> capacity.
>
> The distinction matters: capping image tokens treats a symptom, while `-ub 512`
> and `q8_0` KV address the cause. Keep the cap, but do not rely on
> `IMAGE_MAX_TOKENS ≤ UBATCH` as the safety invariant — **headroom in
> `drm-total-local0` is the real one.** The observations below are accurate; the
> mechanism is not.

**A large enough image hangs the A380 and kills the container.** Root cause is a
single Vulkan submission exceeding i915's fence timeout — not VRAM, not a
llama.cpp position bug.

Signature, from `dmesg -T`:

```
17:37:04  Fence expiration time out i915-0000:03:00.0:llama-server[3823208]
17:37:24  Fence expiration time out  (again)
17:37:49  segfault in libggml-cpu-alderlake.so
```

The GPU hangs first; the segfault ~45s later is the aftermath of a lost context.
**`docker logs` shows nothing** — the process dies mid-request with no error, so
dmesg is the only place the cause appears:

```bash
dmesg -T | grep -i -E "fence expiration|segfault|killed process" | tail -20
```

Trigger was a Mealie recipe photo producing **4,015 image tokens**, split across
two KV insertions (2048 + 1967) because it exceeded `-ub 2048`.

**Fence timeouts also occur without crashing** — there are entries from Jul 30
benchmarking runs that recovered. So "it did not crash" is not evidence the GPU
is happy; check dmesg after any new large-image workload.

### The fix

`LLAMA_ARG_IMAGE_MAX_TOKENS` bounds submission size. `--image-min-tokens` is a
**floor** and does nothing here; the max is the only cap.

**The invariant is `IMAGE_MAX_TOKENS ≤ UBATCH`** — that is what keeps an image to a
single submission. Both sides of it have since changed; see
[the interaction](#the-one-to-look-at-first--ub-512-with-a-1024-token-image-cap).

| value | | at `-ub 2048` |
|---|---|---|
| 1024 | **current** | verified safe, 972-token image, ~96s Mealie import |
| 2048 | measured best | still single-chunk, 2x the OCR detail |
| >2048 | | splits across ubatches — crash territory |

Deployed is 1024 against `-ub 512`, which **violates the invariant** — a
1024-token image splits 512+512. Smaller submissions than the original crash, so
probably fine, but unverified.

1024 is also the minimum llama.cpp warns Qwen-VL wants for grounding tasks
([#16842](https://github.com/ggml-org/llama.cpp/issues/16842)), so capping *at*
1024 sits on the wrong side of that line for OCR work. 2048 is the ceiling of the
safe range.

**Image size is otherwise an unbounded input to a shared service** — any client
could take down Frigate and chat with one photo. The cap is a correctness
requirement, not tuning. `--restart unless-stopped` covers the residual case.

Related upstream issues: [#21550](https://github.com/ggml-org/llama.cpp/issues/21550)
(server crashes on large images), [#19929](https://github.com/ggml-org/llama.cpp/issues/19929)
(vision output irrelevant at certain batch sizes),
[#17172](https://github.com/ggml-org/llama.cpp/discussions/17172) (4K images).

---

## Frigate configuration

Two settings on the Frigate side matter more than anything tuned here.

### Event rate: the real numbers

Everything downstream of this was wrong for a while, so it goes first.

Measured 2026-08-12 from `/api/events` over a full 24 hours:

| | |
|---|---|
| events in 24h | **287** |
| with descriptions | **273** (95%) |
| mean rate | **12/hr** |
| **peak hour** | **42/hr** (09:00 and 10:00) |
| quiet hours | 00:00–05:00 and 21:00 have zero |

**Not ~347/hr.** Where that figure came from is unknown and it has not been
reproduced; it may have counted all tracked objects rather than the genai-filtered
subset, or come from an unusually busy window. Either way, **use 42/hr peak** for
any headroom calculation, and re-measure rather than trusting either number:

```bash
curl -s "http://192.168.1.5:5000/api/events?limit=3000&after=$(python3 -c 'import time;print(int(time.time()-86400))')" | python3 -c "
import json,sys,datetime as dt,collections
evs=json.load(sys.stdin)
desc=sum(1 for e in evs if (e.get('data') or {}).get('description') or e.get('description'))
print(f'events 24h: {len(evs)}   described: {desc}   mean: {len(evs)/24:.1f}/hr')
h=collections.Counter(dt.datetime.fromtimestamp(e['start_time']).hour for e in evs)
for k in sorted(h): print(f'  {k:02d}:00  {\"#\"*min(h[k],60)} {h[k]}')
print('PEAK:', max(h.values()) if h else 0, '/hr')"
```

### `use_snapshot` — the case against it has collapsed

**`use_snapshot: true` more than doubles per-event cost.** That part held up.
Measured on a real 1280x720 snapshot:

| | thumbnail (175x175) | snapshot (1280x720) |
|---|---|---|
| image tokens | 283 | **959** |
| prefill | ~6.5s | **20.7s** |
| **per event** | **8.72s** | **21.5s** |
| duty cycle @ 347 ev/hr *(assumed)* | ~84% | ~207% |
| **duty cycle @ 42 ev/hr *(measured)*** | **~10%** | **~25%** |

**The 207% never existed.** At the real peak rate, snapshots cost ~25% duty cycle —
comfortable. The previous conclusion, "on this hardware it is thumbnails or
nothing", was an artifact of an event rate 8.3x too high.

This inverts the recommendation. The card has ~75% idle headroom at peak, and
image quality is the main lever on description quality:

| option | image tokens | per event | duty @ 42/hr |
|---|---|---|---|
| current: thumbnail, `IMAGE_MIN_TOKENS 256` | 283 | 7.41s | **8.6%** |
| thumbnail, `IMAGE_MIN_TOKENS 512` | 556 | ~13.6s | **15.9%** |
| **`use_snapshot: true`** | 959 | 21.5s | **25.1%** |

All three fit **on time**. Time is not the binding constraint.

> **Do not act on this yet, and do not reach for `-ub 2048` to do it.** Duty cycle
> measures *GPU seconds*, and the resource that hard-locked this box twice is
> *VRAM*. They are different budgets, and only one of them was ever tight. See
> [Deployed vs. measured](#deployed-vs-measured--this-is-a-crash-fix-not-drift).
>
> The good news is that image tokens are processed in `-ub`-sized chunks, so a
> 959-token snapshot at `-ub 512` should not enlarge the compute buffer — the
> hypothesis is that snapshots are VRAM-neutral and this is affordable. **That is
> a hypothesis, not a measurement.** Verify against `drm-total-local0` before and
> after, and only after the uptime window closes.

Trade to watch: burst behaviour. Duty cycle is an hourly average, and events
arrive in clusters — a car in the driveway fires several within a minute. At 21.5s
each with `N_PARALLEL 1`, a burst of four queues for ~86s. Acceptable for
descriptions that are read later, not for anything realtime.

### The prompt controls generation cost

Measured across three thumbnails, mean output tokens:

| prompt | output |
|---|---|
| "…describe the behavior … in one sentence." | **100** (hits the cap) |
| "…in one short sentence of at most 12 words…" | 31.7 |
| **"…under 15 words. Do not describe the setting or background."** | **11.3** |

Word limits alone did almost nothing. The clause that works is **"do not describe
the setting or background"**.

```yaml
objects:
  genai:
    enabled: true
    use_snapshot: false
    prompt: "What is the {label} doing? Answer in one plain sentence under 25 words. Do not describe the setting or background."
```

Measured with this exact prompt on the deployed model: **7.41s per event**, output
10–15 tokens. 25 words rather than 15 buys back some description quality for
almost nothing, now that generation is cheap.

> **The deployed prompt is not this one.** Production descriptions on 2026-08-12
> read like *"A white SUV is visible at the top of a paved driveway. The v…"* —
> which describes the setting, the exact thing the winning clause forbids, and runs
> well past 25 words. So either `objects.genai.prompt` was changed or an
> `object_prompts` entry shadows it. **The 7.41s/event baseline assumes 10–15
> output tokens and does not describe what is running.** Dump the live config:
>
> ```bash
> curl -s "http://192.168.1.5:5000/api/config" | python3 -c "
> import json,sys
> c=json.load(sys.stdin)
> print(json.dumps(c.get('objects',{}).get('genai',{}), indent=2)[:900])"
> ```
>
> Worth deciding rather than fixing by reflex: at ~8.6% duty cycle the verbosity is
> affordable, and richer descriptions may be what you want. The problem is that it
> is undocumented drift, not that it is slow.

This is also why the model comparison above used a *loose* prompt and still
showed only a 5% spread — **a constrained prompt collapses the difference between
builds.** Benchmark model swaps with the production prompt or the numbers will
mislead you.

---

## Workload profiles

The three clients have opposite shapes. Optimising for one can pessimise another.

| | prefill | generation | dominated by |
|---|---|---|---|
| **Frigate** | 6.1s (283 tok) | 2.4s (~30 tok) | **prefill, 72%** |
| **chat** | 5–8s (~350 tok) | ~30s (~314 tok) | **generation, 83%** |
| **Mealie** | 23.5s (972 tok) | 73.0s (795 tok) | **generation, 76%** |

### Chat profile

Six consecutive turns, context 4,802 -> 6,510 tokens:

| ctx depth | prefilled | pp t/s | out | total |
|---|---|---|---|---|
| 4,802 | 400 | 69.4 | 347 | 38.6s |
| 5,479 | 340 | 53.1 | 319 | 36.5s |
| 6,510 | 367 | 61.6 | 262 | 31.1s |

**`CACHE_RAM -1` is doing enormous work here.** `f_sim_best = 0.92–0.94` LCP
similarity means only ~350 tokens get prefilled against a 6,500-token context.
Without it every turn would re-prefill the whole history: **~108s instead of ~6s.**
The parent README's null result for caching applies *only* to Frigate, where every
image is unique — do not generalise it.

Prefill degrades with context depth (69.4 t/s at 4.8K, 48.8 at 6.2K) as the new
tokens attend over a deeper KV cache. Starting a fresh chat resets it.

### Mealie profile

~96s per import at the 1024 cap: 23.5s prefill (972 image tokens) + 73.0s
generating ~795 tokens. Not latency-critical, but **do not compare it to Frigate
numbers** — different shape entirely.

---

## Rollback

Both prior models are still on disk. Rollback is a variable swap and a restart;
`ALIAS` stays `qwen3-vl` so **no Frigate or Mealie config changes in either
direction**.

### To the Unsloth 35B (no longer recommended)

> **Downgraded 2026-08-14.** It is still a valid rollback target, but it is not a
> free upgrade. Measured against `HauhauCS` on the deployed config: **~10% slower
> generation** (11.22 vs 12.48 t/s) and **+575 MiB on the card** at the same
> `-ncmoe`, both from the layer-aware quant. Its template measured **8057 bytes**,
> not 7764 — correct, just different. Take it only for the `nextn` head, and see
> [why that no longer pays](#the-2026-08-14-mtp-experiment--measured-and-it-does-not-pay).

Same architecture, dynamic quantization, ships a full chat template. Drop
`LLAMA_ARG_CHAT_TEMPLATE_FILE` entirely — its embedded template is correct.

```
LLAMA_ARG_MODEL   /models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
LLAMA_ARG_MMPROJ  /models/mmproj-Qwen3.6-35B-F16.gguf
```

Measured ~10% faster per Frigate event than the abliterated build (8.75s vs 9.57s
at the time), entirely from being less verbose (~25 output tokens vs ~33) — the
`UD-` quant is layer-aware where the abliterated one is a plain Q4_K_M.

### To the 4B

Captured 2026-08-02 immediately before the 35B replaced it. **These are the args
that were actually running**, which differ from what
[README.md](README.md#post-arguments) documents — the deployed container had
drifted to `-c 8192` and picked up `--cache-ram 0`.

```
--model /models/Qwen3-VL-4B-Instruct-Q4_K_M.gguf --mmproj /models/mmproj-F16.gguf --alias qwen3-vl --device Vulkan0 --image-min-tokens 512 -c 8192 -np 1 --cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on -b 512 -ub 512 --port 8080 --cache-ram 0
```

Baseline to compare against: **6.3s per event**, 99 t/s prefill, 23.2 t/s
generation, n=11 production sample.

---

## Gotchas

- **`strings` is not installed on Unraid.** No binutils, same as `jq` and
  `python3`. Use `tr -c '[:print:]' '\n'` to pull strings out of a binary. It fails
  as `command not found` *inside a pipe*, so the next stage sees an empty stream
  and a `grep -c` reports `0` — indistinguishable from a real negative. **Put a
  known-present pattern in every binary grep** so an empty pipeline is visible.
- **GGUF tensor names live in the header.** `dd bs=1M count=32` is enough to
  enumerate them; never scan the whole 21 GB.
- **`llama-bench` is not in `:server-vulkan`.** That stage copies only `llama` and
  `llama-server`. Use `:full-vulkan` with `--entrypoint /app/llama-bench`.
- **`--no-mmap` is a server flag, not a bench flag.** `llama-bench` uses
  `-lm, --load-mode <none|mmap|mlock|mmap+mlock|dio>`.
- **Mount `/root/.cache` into benchmark containers too.** Without it Mesa
  recompiles every Vulkan pipeline from scratch on every run — single-threaded,
  and it looks exactly like a hang (~20–50% CPU, no output for minutes).
  `--progress` distinguishes the two.
- **`llama-bench` defaults to `-t 6`.** Always pass `-t 14`.
- **`--list-devices` suppresses `load_backend:` lines**, so it cannot confirm the
  CPU variant. Use `system_info:` from a real run — expect `AVX_VNNI = 1` and
  `libggml-cpu-alderlake.so`.
- **`docker logs` on a busy container rotates the startup banner away.**
- **Slot-level KV reuse is independent of `CACHE_RAM`.** A repeated prompt logs
  `selected slot by LCP similarity, f_sim_best = 1.000` and prefills only the
  delta, so back-to-back A/B requests are **not comparable on prefill** even with
  caching disabled. Cost me two invalid samples in a five-image run. Generation is
  unaffected.
- **`find_slot: non-consecutive token position` is normal for vision** — image and
  text tokens interleave with gaps. It is only a problem when accompanied by a
  fence timeout.
- **`/tmp` is RAM-backed.** Staging a 21 GB download there costs 21 GB of the 128.
- **The web UI is served gzip-only.** `curl http://192.168.1.2:8080/` returns
  HTTP 415 `Error: gzip is not supported by this browser`; use `--compressed`.
  Real browsers are fine. Chat history lives in browser IndexedDB (Dexie), not on
  the server.
- **Unsloth filenames carry a `UD-` prefix and omit `-MTP`** — the MTP head is
  inside the file, only the repo name says so.
- **mmproj filenames start with `mmproj-`, not the model name.** A glob like
  `mv Qwen3.6-*-Aggressive-*.gguf` moves the model and silently leaves the
  projector behind. The failure is at least loud —
  `failed to open GGUF file ... (No such file or directory)` then
  `exiting due to model loading error` — but with `--restart unless-stopped` it
  presents as a crash loop of identical stack traces.
- **A 21 GB model takes ~14s to load** with `LOAD_MODE none`, plus longer on a
  cold file. `/health` returns 503 until it finishes; do not conclude failure
  from an early 503.

---

## Investigated and closed

**Mesa / XMX is a dead end.** The device line reports `matrix cores: none`, and
ANV has exposed `VK_KHR_cooperative_matrix` on Gfx9+ (including DG2) since Mesa
24.0 — but **it is emulated on the shader cores, not running on XMX hardware**
([Phoronix](https://www.phoronix.com/news/Intel-ANV-Cooperative-Matrix)). A newer
Mesa would at best swap `none` for a slow emulation path. Not worth a custom image.

**MXFP4 on the GPU.** The device line reports `fp4: 0` — no native FP4. Combined
with the Q6_K result, any MXFP4 tensor on the card is a bad bet. (This does *not*
rule out MXFP4 experts on the CPU — see open questions.)

**Router mode / two models.** llama.cpp has `--models-dir` + `--models-max 1`
hot-swapping, but model load is ~12–16s and Frigate fires an event every ~10s, so
any chat use would thrash the vision model out of VRAM continuously.

**Image generation.** The VL model is image-*in*, text-out. Diffusion is dense
compute, so the CPU-offload trick that makes this whole setup work does not
transfer — 128 GB of RAM buys nothing there, and 6 GB of VRAM is the hard limit.

**Dense models of any size are disqualified — this is the standing answer.**
Checked 2026-08-14 against `Qwen3.8-27B` (`num_hidden_layers 64`,
`hidden_size 5120`, `intermediate_size 17408`, **no MoE fields**). FFN alone is
`3 x 5120 x 17408 x 64 = 17.1B params`, every one read per token: **~16 GB/token
against the 604 MB this setup is built on**, or ~1.5 t/s once the card is full.
Frigate would go 7.4s → ~30s per event and chat ~36s → ~3.5 min.

This is the [Kimi K3 corollary](#the-number-that-governs-everything) in miniature —
total parameters are irrelevant, **active** parameters are disqualifying, and a
dense 27B has 27B active. Note that the KV is *not* the problem: `Qwen3.8-27B` is
the same hybrid linear-attention family (`full_attention_interval: 4`,
`num_key_value_heads: 4`), so KV would be ~2x the current model's, which is fine.
The dense FFN is the whole story.

**Triage rule: if the name has no `-A<n>B` suffix, stop.** Qwen tags active
parameters explicitly — `Qwen3.8-2.4T-A95B` does, `Qwen3.8-27B` does not. Same for
`Qwen3.6-27B` variants (including the `-MTP-GGUF` builds, which are tempting and
still dense) and `Muse-Glimmer-30B`. Confirm with `config.json`: no `num_experts`
means no.

---

## Open questions

**`LLAMA_ARG_FIT` may be worth 15%.** Removing the stale `LLAMA_ARG_FIT=off`
(which the parent README calls "harmless") coincided with generation going
**11.0 -> 12.7 t/s** across three identical requests — real and reproducible, but
the startup log contains no fit/offload output, so **the cause is unverified**.
Clean A/B: add it back, re-measure, remove again.

**`Qwen3.6-35B-A3B-MXFP4_MOE.gguf` is untested — and it is now the leading
candidate.** At `N_CPU_MOE 40` the GPU never touches an expert tensor, so `fp4: 0`
is irrelevant to the MoE weights — and MXFP4's ~4.25 bpw against Q4_K_M's ~4.8
means **~534 MB/token instead of 604**, ~13% less traffic on the exact path that
bottlenecks.

With MTP [rejected on economics](#the-2026-08-14-mtp-experiment--measured-and-it-does-not-pay),
this is the only remaining lever on generation that does not require new hardware —
and 2026-08-14 established that quant choice moves throughput ~10% in *both*
directions, so the mechanism is real. It is also the cheap test: one model swap,
one `drm-total-local0` read, five throughput samples. **Take at least five** — the
contention spread on this box is ~9%, wide enough to invent or hide a 13% effect.

**Mealie accuracy at the 2048 cap is unverified.** The 1024 run completed but the
extraction was never checked against the source photo. Quantities, units, oven
temps and times are what degrade first when image resolution drops, and they fail
plausibly rather than obviously.

**Frigate duty cycle is ~8.6% at the measured 42/hr peak**, not the ~71% this file
long assumed. There is roughly 75% idle headroom at the busiest hour. The open
question is no longer how to protect it but **what to spend it on** — snapshots,
`IMAGE_MIN_TOKENS 512`, or a second camera are all affordable now. See
[use_snapshot](#use_snapshot--the-case-against-it-has-collapsed).

**K_P quants are untested.** `HauhauCS` ships Q4_K_P through Q8_K_P, claimed at
"1–2 quant levels of quality uplift" for 5–15% more size. Rejected on bandwidth
grounds without measuring — worth an A/B if chat or Mealie quality ever matters
more than Frigate throughput, since the harness makes it a 10-minute test.

**CORS is `*` with no API key**, which llama.cpp warns about on every start. Any
web page you visit can reach `192.168.1.2:8080` from your browser. `--api-key`
would close it, but Frigate's `llamacpp` provider may not support an auth header —
unverified.

**`--spec-draft-n-max 3` — now moot for a different reason.** n-max 2 was measured
2026-08-14 and the whole MTP path was rejected on economics, not depth. Acceptance
at n-max 2 was only 0.55–0.62, and the existing table already shows acceptance
collapsing as depth grows, so 3 would be worse. **Only worth revisiting if an
abliterated build with the `nextn` head turns up.**

**MTP + vision is still untested.** Every 2026-08-14 measurement was text-only. If
MTP is ever retried, this is the gap — upstream fixed it, but not verified here on
Vulkan with experts on CPU.

**Text generation re-baselined 2026-08-14; per-event figures still are not.**
Generation on the deployed config is **12.48 t/s, best of 8** — the 12.5 and 13.07
figures were single samples and neither reproduced. Still outstanding: the
**7.41s/event** Frigate figure and all prefill numbers, which were taken on the
configuration that crashed the box. Sampling `docker logs` for real events is
read-only and changes nothing, so there is no reason not to do it.

**Uptime clock restarted 2026-08-14.** Six restarts that day reset it; clean
through ~Aug 20 is one crash interval (6d 6h), ~Aug 27 is two. See
[the retired freeze note](#the-freeze-retired) for why headroom, not
the calendar, is the real protection.

**`crash-analysis-2026-08-10.md` is not in this repo.** It is cited four times
above — for the lockup timeline, the VRAM accounting model, the power log, and the
freeze rationale — and none of it is reproducible without the file. If it only
exists on the Unraid box, pull it in.

**Resolved: Frigate is fine.** A 13.5-minute stretch with zero requests on
2026-08-12 looked alarming against the assumed ~347 ev/hr. It was a quiet evening
hour — the real rate is 12/hr mean, and 18:00–19:00 had 7 events. 95% of events
carry descriptions. Nothing was broken.

The diagnostic that actually answered it was Frigate's API, not either container's
logs — **`docker logs <name>` prints `No such container` to stderr, so
`2>&1 | grep` renders a missing container and a quiet one identical.** Check
`docker ps` first, or use the API.

**Every `pp` number here is depressed ~10–15%** by Frigate (~174% CPU) and seven
`go2rtc` containers holding roughly 2 of 14 cores permanently. Generation is
bandwidth-bound and largely immune; prefill is compute-bound and is not.
