# llama-server on an Intel Arc A380 as a Frigate GenAI backend

What is actually deployed, why, and the measurements behind each decision.

**There is no custom image here.** The deployed container is upstream's own
prebuilt `ghcr.io/ggml-org/llama.cpp:server-vulkan`, driven entirely by runtime
flags. A custom SYCL image was written for this and then discarded — see
[Why not SYCL](#why-not-sycl), which is the most expensive lesson in this file.

Measured 2026-07-29 on: Unraid, i5-13500, 128 GB RAM, Intel Arc A380 (6 GB,
186 GB/s), `/dev/dri/renderD129`. Frigate at `192.168.1.5`, llama-server at
`192.168.1.2`.

---

## Result

Real Frigate events, `qwen3-vl:4b-instruct` Q4_K_M with a native F16 mmproj.
Steady state, **n=11 sampled after ~17 hours and ~5,900 requests**:

| | Ollama (before) | llama-server + Vulkan (now) |
|---|---|---|
| **per event** | **~20.4s** | **6.3s mean** (5.6 – 7.4) |
| prefill | 73 tok/s (14,345 ms) | **99 tok/s mean** (82 – 110), ~5.5s |
| generation | 14.0 tok/s | **23.2 tok/s mean** (21 – 26), ~0.8s |
| image tokens | 1024, forced | ~512 (floor), 535–553 total |
| output tokens | 80 (capped) | 17–22, natural stop |
| vision tower VRAM | 3,382 MiB | 797 MiB |
| total VRAM | ~6,475 MiB — 692 **over** the card | ~3,950 MiB, fits |
| cold start | 39.3s | 4.6s |

**Prefill is 87% of the time** (~5.5s of 6.3s). Descriptions come back at only
17–22 tokens under Frigate's own prompt, so generation is nearly free and the
token budget is not a useful lever. `--image-min-tokens` is the only one that
would move the number materially.

Run-to-run spread on prefill is ±14% (82–110 tok/s) with the image token count
essentially constant, which points at contention rather than the model —
`frigate.detector` shares this GPU. See [Two easy wins](#two-easy-wins).

> Earlier revisions of this file quoted 111 tok/s prefill, 25.5 tok/s generation
> and 5.4–5.7s per event. Those came from **two** hand-run requests on an
> otherwise idle box and were the best samples, not the typical ones. The table
> above is production traffic. Treat any two-sample measurement on this hardware
> as an upper bound.

### Warm-up inflates the first request by ~30%

The first request after a container start measured 85.7 tok/s prefill; every
request after it measured ~111 tok/s. Vulkan compiles pipelines lazily on first
use, and `graphs reused` climbs across requests (149 → 166 → 179). **Discard the
first request after any restart** — it is not representative. An early conclusion
that "Vulkan is 13% slower than SYCL on prefill" was an artifact of exactly this;
warm Vulkan prefill (111 tok/s) beats the SYCL figure (100 tok/s).

---

## The three problems this fixed

### 1. Ollama hardcodes `--image-min-tokens 1024` and won't expose it

qwen3-vl uses `patch_size` 16 with `spatial_merge_size` 2, so one token covers a
32x32 pixel region and 1024 tokens implies a ~1024x1024 image. Frigate sends
175x175 thumbnails, so every event upscaled ~34x in pixel count and ran the
vision transformer over interpolated pixels — ~14s of the ~20s per event.

First-run-only sweep:

| `--image-min-tokens` | prefill | wall clock | output quality |
|---|---|---|---|
| 1024 | 14,345 ms (73 tok/s) | 17.1s | "white sedan", committed |
| **512** | ~8,000 ms | 8.3s | "white SUV" x3, consistent, committed on colour |
| 256 | ~3,300 ms | 4.6–7.1s | hedged colour every run, flip-flopped SUV/sedan |

512 is the chosen value. llama.cpp warns that Qwen-VL wants >=1024 tokens for
*grounding* tasks; Frigate does captioning, and 512 held up.

Body-type ground truth was never established — the car is ~120x50 px even in the
full snapshot — so treat "SUV vs sedan" as **unresolved, not a regression**. The
real signal at 512 over 256 was confidence and run-to-run consistency.

**`--image-min-tokens` is a floor, not a cap.** A 1280x720 snapshot used 926
tokens regardless of the setting, because its native count already exceeds the
floor. This tuning only helps small images. If anyone sets Frigate's
`use_snapshot: True` it does nothing and the analysis needs redoing.
(`use_snapshot` defaults to `False` — confirmed in Frigate's schema.)

### 2. Ollama's packed GGUF promotes the vision tower to F32

Ollama ships qwen3-vl as one blob. Its patched server logs
`handle_qwen3vl_clip: detected Ollama-format qwen3vl GGUF used as mmproj;
translating`, then 51 `compat tensor transform: op=F16->F32 promote` operations —
a 3,382 MiB vision tower against 797 MiB for a native mmproj GGUF, which put the
card 692 MiB over its budget.

**Negative result worth preserving:** fixing the overcommit did *not* improve
generation (15.3 → 16.0 tok/s is noise). The hypothesis was Level Zero VMM paging
to host memory. It wasn't that. Keep the native GGUF for prefill and fast start,
not as a generation fix.

### 3. Frigate's `num_ctx` was silently overriding the server

`provider_options.options.num_ctx` won over `OLLAMA_CONTEXT_LENGTH`. At 1024,
with a 1024-token image plus prompt plus `num_predict: 80`, Ollama truncated from
the **front** of the prompt — which on a VLM discards image tokens. Descriptions
were generated from partially thrown-away images, with nothing in the log to say
so.

Structurally impossible now: Frigate's `llamacpp` provider *reads* context from
the server and logs what it negotiated.

---

## Why not SYCL

`ghcr.io/ggml-org/llama.cpp:server-intel` **cannot run this workload at all.** It
ships IGC 2.34.4 and compute-runtime 26.18.38308.1.

**With flash attention** (required for quantized KV), IGC fails to JIT-compile the
kernel and the process dies with exit 139:

```
IGC: Internal Compiler Error: Interrupt request sent to the program
Exception caught at file:/app/ggml/src/ggml-sycl/ggml-sycl.cpp, line:5236
Error OP FLASH_ATTN_EXT
```

Line 5236 is the `catch (sycl::exception&)` in `ggml_sycl_compute_forward`.
**`--flash-attn auto` does not avoid this** — `supports_op` accepts the op, then
the compiler fails later. It has to be explicitly `off`.

**With `--flash-attn off`**, quantized KV becomes unavailable and the non-FA
attention path materializes the full KQ matrix, which exhausts the card:

```
level_zero backend failed with error: 38 (UR_RESULT_ERROR_OUT_OF_HOST_MEMORY)
Error OP MUL
```

Despite the name, UR maps failed device-side USM allocations onto
`OUT_OF_HOST_MEMORY`. There is 128 GB of host RAM and no container memory limit —
this is VRAM exhaustion.

So: crash with FA, out of memory without it. The `ollama-sycl` image in this repo
*does* compile the FA kernel (it pins IGC 2.36.3 / compute-runtime 26.22.38646.4),
so a custom image with a newer IGC would likely work. Not worth building, because
Vulkan is faster anyway.

Also relevant if you ever revisit SYCL: upstream's Dockerfile flags a **known 26.x
compute-runtime multi-GPU issue**
([llama.cpp#21747](https://github.com/ggml-org/llama.cpp/issues/21747),
[compute-runtime#921](https://github.com/intel/compute-runtime/issues/921)) with
25.40.35563.10 as the documented fallback. This box has two Intel GPUs (iGPU +
A380), so it is squarely in scope.

### The generation ceiling was not bandwidth

Generation sat at ~16 tok/s across four SYCL configurations — ~21% of what
186 GB/s allows, ~1.7 ms/layer over 36 layers. The theory was per-kernel launch
overhead rather than a bandwidth limit. Vulkan hit 25.5 tok/s immediately and logs
`graphs reused = 179`, which is exactly the graph-capture mechanism SYCL's
`GGML_SYCL_ENABLE_GRAPH` was supposed to provide but reported as `0` at runtime.
**Launch overhead was the answer.** Still only ~33% of theoretical, so headroom
remains.

---

## Unraid template

One container, replacing the old `ollama-sycl` one in place.

| Field | Value |
|---|---|
| Name | `llama-server` |
| Repository | `ghcr.io/ggml-org/llama.cpp:server-vulkan` |
| Network Type | `Custom : br0` |
| Fixed IP | `192.168.1.2` |
| Port | `8080` → `8080` |
| Extra Parameters | `--device=/dev/dri/renderD129` |

`renderD129` is the A380; `renderD128` is the i5's iGPU. Never pass both.

Port fields are **cosmetic on `br0`** — macvlan gives the container its own IP and
Unraid publishes nothing. It listens on `192.168.1.2:8080` directly. Set them
correctly anyway so they don't mislead you later.

### Paths

| Container path | Host path | Mode |
|---|---|---|
| `/models` | `/mnt/user/appdata/llama-models` | Read Only |
| `/root/.cache` | `/mnt/user/appdata/llama-server/cache` | Read/Write |

The leading slash on `/models` matters. `.models` is relative and mounts at
`/app/.models`, so `--model /models/...` won't exist and the container dies during
load. `/root/.cache` holds mesa's shader cache — see the warm-up note above.

### Variables

Only `TZ` is needed. No `ONEAPI_DEVICE_SELECTOR`, `ZES_ENABLE_SYSMAN`,
`SYCL_CACHE_PERSISTENT` or `GGML_SYCL_*` — all SYCL-specific and inert here.

**`LLAMA_ARG_*` variables are live.** Upstream's arg parser reads 138 of them via
`set_env`, so a leftover `LLAMA_ARG_FIT=off` really does pass `--fit off`. That one
is harmless alongside an explicit `-c`, but audit anything in this namespace.
`LLAMA_ARG_HOST=0.0.0.0` is already set in the image.

### Post Arguments

```
--model /models/Qwen3-VL-4B-Instruct-Q4_K_M.gguf --mmproj /models/mmproj-F16.gguf --alias qwen3-vl --device Vulkan0 --image-min-tokens 512 -c 4096 -np 1 --cache-type-k q8_0 --cache-type-v q8_0 --flash-attn on -b 512 -ub 512 --port 8080
```

Post Arguments replace the image's `CMD`, so `--port` has to be repeated here.

| Flag | Reason |
|---|---|
| `--image-min-tokens 512` | **The big one.** See problem 1. Ollama hardcodes 1024; this cut ~8s per event. |
| `--mmproj mmproj-F16.gguf` | Native vision tower, 797 MiB vs Ollama's F32-promoted 3,382 MiB. |
| `--device Vulkan0` | `#define GGML_VK_NAME "Vulkan"` plus the device index. `SYCL0` for the SYCL backend. |
| `--alias qwen3-vl` | **Load-bearing.** Frigate validates `model:` against `/v1/models` and fails init silently on mismatch. |
| `-c 4096` | Server-side only now, no client override to undercut it. ~545 tokens actually used. |
| `--cache-type-k/v q8_0` | 306 MiB KV at 4096. Requires flash attention. |
| `--flash-attn on` | Required for quantized KV, and without it the card OOMs. |
| `-np 1` | One request at a time; concurrency buys nothing here. |
| `-b 512 -ub 512` | Matches the image token count, so a thumbnail encodes in one batch. |

Vulkan reports **6088 MiB** total where SYCL reported **5783 MiB** — different heap
accounting. The "692 MiB over" figure was computed against the SYCL number.

---

## Frigate

```yaml
genai:
  default:
    provider: llamacpp
    base_url: http://192.168.1.2:8080
    model: qwen3-vl
    provider_options:
      max_tokens: 100
      temperature: 0.2
      repeat_penalty: 1.05
    roles:
      - descriptions
      - chat
```

Confirm it took with this log line:

```
frigate.genai.plugins.llama_cpp  INFO: llama.cpp model 'qwen3-vl' initialized — context: 4096, vision: True, audio: False, tools: True, reasoning: False
```

The provider initializes **lazily on first use**, not at startup — its absence
right after a restart means nothing.

Verified against Frigate's source rather than assumed:

- **`provider: llamacpp`**, not `openai`. A dedicated plugin that reads
  llama-server's `timings`, auto-detects context from `/v1/models` or `/props`, and
  computes image token counts.
- **`provider_options` is spread flat** into the chat/completions payload
  (`payload.update(provider_opts)`), so keys must be OpenAI/llama.cpp names.
  `num_predict` → **`max_tokens`**.
- **`timeout_seconds` is not a Frigate option at any nesting level** — zero
  occurrences in the config schema, the manager, or any provider. The timeout is
  hardcoded to 120s in `GenAIClient.__init__`. The
  `WARN invalid option provided option=timeout_seconds` seen previously came from
  *Ollama's server*, not Frigate.
- **Omit `num_ctx`.** The provider negotiates it. The Frigate-side override is
  `context_size`, which is stripped from the payload before sending.
- `keep_alive` and `think` are Ollama-only and would be sent as junk fields.
- **Prompts live under `objects.genai`**, not the top-level `genai:` block:
  `objects.genai.prompt` and `objects.genai.object_prompts`.
  `objects.genai.enabled` is what actually triggers generation, separately from the
  provider config.

Frigate's default prompt is behaviour-focused ("rather than describing its
appearance") and yields 15–19 token responses, so `max_tokens: 100` never binds. A
generic "describe the vehicle" prompt produces verbose markdown that runs straight
into the cap — if you customise it, ask for one plain sentence.

`objects.genai.debug_save_thumbnails: true` writes out exactly what is being sent.

---

## Models

```bash
cd /tmp && BASE=https://huggingface.co/unsloth/Qwen3-VL-4B-Instruct-GGUF/resolve/main && wget -c "$BASE/Qwen3-VL-4B-Instruct-Q4_K_M.gguf" && wget -c "$BASE/mmproj-F16.gguf" && mkdir -p /mnt/user/appdata/llama-models && mv Qwen3-VL-4B-Instruct-Q4_K_M.gguf mmproj-F16.gguf /mnt/user/appdata/llama-models/
```

Sizes: 2,497,282,336 and 836,180,640 bytes (797.4 MiB — matches the vision tower
figure exactly, which is a useful integrity check).

Stage through `/tmp` and `mv`. Writing directly to `/mnt/user` measured 1.0 MB/s
against 4.9 MB/s to `/dev/null` — parity read-modify-write on the FUSE share costs
~5x. The `mv` is one large sequential write, which parity handles far better than
wget's incremental chunks. `/tmp` is RAM-backed and there is 128 GB.

### Do not "upgrade" the quantization — Q6_K was measured and rejected

Q4_K_M is not a memory compromise, it is the fast option. Q6_K fits comfortably
(4,694 MiB measured, 1,285 MiB still free) and is **30% slower per event**:

| | Q4_K_M | Q6_K |
|---|---|---|
| weights | 2,382 MiB | 3,153 MiB |
| VRAM (measured) | 4,109 MiB | 4,694 MiB |
| prefill | 111 tok/s | 92 tok/s |
| generation | 25.5 tok/s | **13.0 tok/s** |
| per event | 5.4–5.7s | 7.1–7.6s |

Generation nearly halved for 32% more weight. Scaling generation by model size
predicts ~19 tok/s and is wrong, because that assumes a bandwidth-bound device —
the same assumption the SYCL-vs-Vulkan result already disproved. This GPU is
dequant- and launch-bound, so **quant format complexity costs more than file
size does**. Q6_K's unpacking is more expensive per byte and its Vulkan kernels
are less optimized here.

Corollary: don't reason about VRAM headroom as though it converts into quality.
Anything above Q4_K_M needs measuring, not estimating. Untested but likely
governed by the same effect: Q5_K_M, and the `IQ*`/`UD-*` variants.

Bigger models are worse for a different reason. The 8B only fits at IQ2/IQ3
(its vision tower alone is 1,109 MiB vs 797), and prefill — already ~4.9s of the
~5.5s budget — scales with parameter count, so expect roughly double.

---

## Verification

```bash
docker logs llama-server 2>&1 | grep -E "Vulkan|A380|model loaded|listening"
```

```bash
docker logs llama-server 2>&1 | grep -E "launch_slot_|prompt eval time|release:"
```

Per-request timings; each event is a new `task N`. Prefill token count should be
**~535–556** (≈512 image + text). If it reads ~1056, `--image-min-tokens` didn't
take. If it's much higher than ~556, Frigate is sending multiple frames per event
and prefill scales with each — `objects.genai.send_triggers` is the knob.

This build does **not** log `task.n_tokens`; it logs `n_tokens` on the `release:`
line and token counts on `prompt eval time`.

```bash
docker run --rm --device=/dev/dri/renderD129 ghcr.io/ggml-org/llama.cpp:server-vulkan --list-devices
```

Confirms the exact device string. Its "free memory" is **not** cross-process — run
against a live server it still reports a near-idle card, so it cannot measure
residency. This kernel's i915 doesn't export `mem_info_*` in sysfs either, so
there is no easy global VRAM counter on this box.

### Testing by hand

**Unraid's host shell cannot reach `br0` containers** — not llama-server at `.2`,
not Frigate at `.5`. `docker logs` works from the host; anything over HTTP has to
come from another machine. From a Mac on the LAN:

```bash
EID=$(curl -s "http://192.168.1.5:5000/api/events?limit=1" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4); curl -s "http://192.168.1.5:5000/api/events/$EID/thumbnail.jpg" -o /tmp/thumb.jpg; ls -la /tmp/thumb.jpg
```

```bash
{ printf '{"model":"qwen3-vl","max_tokens":100,"temperature":0.2,"messages":[{"role":"user","content":[{"type":"text","text":"Describe the vehicle in one sentence."},{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,'; base64 < /tmp/thumb.jpg | tr -d '\n'; printf '"}}]}]}'; } > /tmp/req.json; curl -s -w '\n=== %{time_total}s ===\n' http://192.168.1.2:8080/v1/chat/completions -H 'Content-Type: application/json' --data-binary @/tmp/req.json -o /tmp/resp.json; tr ',' '\n' < /tmp/resp.json | grep -E 'prompt_n|prompt_per_second|predicted_n|predicted_per_second'
```

Streaming base64 into the file rather than through a shell variable avoids quoting
and length problems. `req.json` should be ~11 KB; ~220 bytes means the image
didn't make it in, and the server will log
`failed to decode buffer as either image/audio/video`.

Neither `python3` nor `jq` is on Unraid; `base64`, `dd`, `tr` and `awk` are.

### Benchmarking rules

**Never benchmark the same image twice in a row.** Prompt caching makes run 2 skip
prefill entirely and report a fabricated speedup — observed 8.25s then 2.22s for
identical input. Use a different thumbnail every time (`?limit=5`, pick a
different `id`).

**Discard the first request after a container restart** — pipeline compilation
inflates it ~30%.

Only first-run-on-a-fresh-image numbers mean anything for Frigate, where every
event is a new image.

---

## Open questions

**Generation is at 23.2 tok/s, ~30% of theoretical.** Up from ~21% on SYCL, but
still short. `graphs reused` confirms graph capture is active, so the next
suspects are dequant cost and occupancy on a 128-EU part — consistent with the
Q6_K result above.

**Prefill is the dominant cost** (~5.5s of 6.3s, 87%). `--image-min-tokens 256`
would roughly halve it, at the run-to-run consistency cost documented above. It's
the main remaining lever, and it's a quality trade rather than a free win.

**The prompt cache never hits and is pure overhead.** Every request logs
`making room for prompt cache entry, removing oldest entry (size = ~43 MiB)`,
because each Frigate event is a unique image so a cached prefix can never match.
`--cache-ram 0` disables it (`-cram`, `0` = disable, `-1` = unlimited). This is
host RAM, not VRAM, so the win is bounded — untested, and worth an A/B rather
than assuming.

### Two easy wins

**Move Frigate's detector off the A380.** `intel_gpu_top` shows
`frigate.detector`, `frigate.embeddings` and `python3` sharing card1 with
llama-server. They only hold ~110 MiB, but the ±14% prefill spread suggests
contention matters more than the memory does. The i5-13500's iGPU (card0 /
`renderD128`) is idle.

**`-c 2048` instead of 4096.** Requests use ~580 of the context, so this reclaims
~153 MiB of KV for nothing. Already applied above.

**A custom SYCL image with IGC 2.36.3+ and graph capture is untested.** It would
have to beat 111 tok/s prefill and 25.5 tok/s generation to justify any build
infrastructure.

**oneAPI 2026.x is still unavailable as a container image**, but 2025.3.x tags
*do* exist (2025.3.0/1/2) — an earlier survey concluding 2025.2.2 was newest was
wrong. Intel's GPU APT repo is not a shortcut to newer drivers either: as of
2026-06 its `unified` component carries compute-runtime 25.18.33578.15 /
level-zero 1.21.9 / GMM 22.7.2, all *older* than the GitHub releases.
