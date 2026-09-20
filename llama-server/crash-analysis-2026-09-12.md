# Crash analysis — 2026-09-12

> ⛔ **The watch opened here FAILED on 2026-09-20, after 8 of its 30 days — see
> [`crash-analysis-2026-09-20.md`](crash-analysis-2026-09-20.md).** The evidence work below
> stands (`parity-checks.log` as the reset ledger, the five-year episodic shape, the
> retractions). Its **conclusion does not**: reverting to `ollama` did not change the reset
> rate, so the GenAI server, the GPU backend and the model are all exonerated.

**The sixth reset, and the first day the investigation produced a dated reset history
instead of a guess.** Two long-standing conclusions are retracted, one new evidence
source supersedes every other, and the deployed GenAI backend was reverted from
`llama-server` to `ollama`.

Investigated 2026-09-12. All timings local (CDT, UTC−5) unless marked.

Supersedes parts of [`crash-analysis-2026-08-16.md`](crash-analysis-2026-08-16.md) —
specifically its cadence framing and its "levers not yet pulled" ranking. The
deployment described in [`MOE.md`](MOE.md) and [`README.md`](README.md) is no longer
running.

---

## Contents

- [The event](#the-event)
- [The reset ledger — parity-checks.log](#the-reset-ledger--parity-checkslog)
- [The five-year picture](#the-five-year-picture)
- [Corrected statistics](#corrected-statistics)
- [Falsified](#falsified)
- [Retracted](#retracted)
- [The measurement problem](#the-measurement-problem)
- [The change made](#the-change-made)
- [Verified end state](#verified-end-state)
- [Watch baseline and success criteria](#watch-baseline-and-success-criteria)
- [Method notes and gotchas](#method-notes-and-gotchas)
- [Query cookbook](#query-cookbook)

---

## The event

Reset at **08:12:0x**, pinned by two independent sources that agree to within seconds:

| source | evidence |
|---|---|
| netdata (`system.cpu`, `system.io`) | last sample **08:12:00** |
| pve `pvestatd` | first `Connection timed out` **08:12:08**; `No route to host` from **08:12:45** |
| kernel | boot **08:14**; back on the LAN **08:15:24** |

Unclean: NVMe Unsafe Shutdowns **{59,69} → {60,70}**, both +1.

**Uptime was 3 d 18 h 39 m** (boot 2026-09-08 13:33), so it cleared the 3-day checkpoint
and died before the 1-week one.

**It died at idle.** Pre-crash `system.io` reads **101–168 KB/s**, CPU user ~4.1 %, RAPL
package **27.4–28.2 W** (dead on the idle baseline), UPS load 287–312 W, UPS output
118.9–119.5 V steady. No thermal, power or workload excursion. The GPU was idle too — the
last llama-server inference released **08:07:44**, four minutes eighteen seconds before the
reset. The Sep 9 parity check had completed clean (86081 s, exit 0, 0 errors), so the array
was verified going in.

Signature unchanged from all five prior events: **instantaneous reset, rails up, zero
forensic trace.** Empty `/sys/fs/pstore/`, no MCE, no WHEA, no AER (every `aer_dev_*`
counter 0), no i915/xe/drm errors, nothing in the kernel log.

---

## The reset ledger — `parity-checks.log`

**`/boot/config/parity-checks.log` is the best forensic source on this machine and it was
sitting there the whole time.** Unraid auto-starts a parity check on an unclean shutdown,
and the log records **completion time + duration**, so:

```
start  =  completion − duration  ≈  the reset moment
```

It reaches back to **2021**, survives every reboot, and outlives netdata (~2 weeks) and
the remote syslog (~4 weeks).

**Validated against the four independently pinned resets — matches to within minutes:**

| log start | pinned reset | delta |
|---|---|---|
| 2026-08-04 06:44 | 06:41 | 3 min |
| 2026-08-10 13:13 | 13:09 | 4 min |
| 2026-08-16 19:31 | 19:28 | 3 min |
| 2026-09-08 09:30 | 09:27 | 3 min |

**Classifying rows.** Pre-2025-12 rows carry an explicit `Automatic` (unclean-triggered)
vs `Scheduled` label. From 2025-12-28 the short format drops the label, so 2026 rows are
classified by matching known reset times and by the **scheduled cadence, which always
starts at 05:00** and runs roughly quarterly: 2025-12-27, 2026-03-04, 2026-06-03,
2026-09-02 are all scheduled.

### Two caveats that matter

**The ledger is lossy.** A check killed by the *next* reset writes no entry. The
Sep 7 20:20 reset is absent for exactly that reason — its check died 13 h in, at the
Sep 8 09:27 reset. So it **undercounts back-to-back resets**. But a lone reset in a quiet
stretch would have completed its check and appeared, which is what makes "zero in a quiet
era" a sound inference rather than an artifact.

**It measures something different from the NVMe counter.** NVMe Unsafe Shutdowns increment
on *any* abrupt power removal, including a hard power-cycle with the array stopped.
`parity-checks.log` only fires when the array was mounted and not cleanly unmounted — i.e.
**"crashed while running."** The two ledgers disagreeing is not an error; it is the
distinction doing its job. Prefer `parity-checks.log` for crashes.

---

## The five-year picture

Reset-triggered checks only:

| era | events | assessment |
|---|---|---|
| 2024 Jul – Dec | 6 | cluster |
| 2025 Mar – May | 7 in ~2 months | cluster |
| **2025 May 4 → 2026 Aug 4** | **ZERO** | **~15 months clean** |
| 2026 Aug 4 – Sep 12 | 6 in 39 d | cluster (current) |

**The fault is episodic — bursts separated by long clean runs.** And the 15-month clean run
happened with the A380 installed in the same slot, which exonerates both the card and the
slot. The earlier clusters line up with the **Coral dual-TPU** era, which was resolved by
removing it.

**The 2026 quiet era (May 12 – Aug 4) contains zero reset-triggered checks.** The three
NVMe Unsafe Shutdown increments in that window were therefore **not crashes** — almost
certainly hard power-cycles with the array stopped.

### Model timeline, for correlation

| date | change |
|---|---|
| 2026-07-30 | `llama-server` deployed as the Frigate GenAI backend, running `Qwen3-VL-4B` |
| 2026-08-02 | swapped in place to `Qwen3.6-35B-A3B` — the "28 GB" model (see [MOE.md](MOE.md)) |
| **2026-08-04** | **first reset**, two days later |
| 2026-08-16 | back to the dense 4B, plus `pcie_port_pm=off` and ASPM clears |
| 2026-08-16 → 09-07 | 22 clean days |
| 2026-09-07/08/12 | three resets in five days |

**Onset is tight against the 35B, but the 4B era still resets.** So neither llama-server
alone nor the big model alone is sufficient. The sharpest surviving distinction is in
[The change made](#the-change-made).

---

## Corrected statistics

With the quiet era correctly read as **zero** rather than three:

> Given 6 resets total, P(all 6 landing in the recent 37.6-day window | uniform rate)
> = (37.6 / 118.5)^6 = **0.001**

That is ~69× stronger than the **p ≈ 0.070** computed from the mistaken count of three.
**The Aug 4 onset is real.**

---

## Falsified

**DDR4-2666 — the single variable under test — is dead.** All settings verified still in
force at the moment of the reset: `pcie_port_pm=off`, `intel_idle.max_cstate=1` (ladder
POLL + C1_ACPI only), four DIMMs at `Configured Memory Speed: 2666 MT/s`, BIOS F25a
(07/29/2026). That closes the IMC / 4-dual-rank-DIMMs-at-3200-2DPC hypothesis as a
*sufficient* cause.

**Every config lever has now failed:** C-state clamp, `pcie_port_pm=off`, ASPM clears,
memory downclock, BIOS update, model size. In hindsight this was predictable — see the next
section.

---

## Retracted

### The power-transient / slot-overdraw theory

Measured the A380's board power by sampling `energy1_input` at **21 ms** while driving a
representative Frigate-shaped 516-token image prompt. First run looked alarming — idle
16.5 W, busy mean 54.9 W (99.8 % of the 55 W PL1 cap, i.e. pegged), peak **65.6 W**, which
is ~99 % of the x16 slot's ~66 W 12 V allowance on a card with **no auxiliary connector**.

**It does not hold up:**

1. **The peak is not reproducible.** A second identical run peaked at **52.0 W**. The
   "99.4 % of budget" figure rested on one unrepeatable sample.
2. **The card clamps its own transients.** Sampling `throttle_reason_*` at 21 ms during a
   burst (784 samples): **`pl4` (peak power) asserted in 1.5 %**, while `pl1`, `pl2`,
   `thermal` and `vr_tdc` asserted **never**. The card reaches its peak-power limit and
   actively limits it — which argues against it freely overdrawing the slot.
3. **`energy1_input` is not slot current.** It is the card's own board-power telemetry,
   including VRAM, fans and conversion losses, and it does not separate the 12 V rail from
   the 3.3 V rail. Comparing it to the slot's 12 V allowance was apples to oranges.
4. **75 W slot-powered cards are designed to draw 75 W.** Operating at the envelope is not
   a defect.

The derived "cap `power1_max` at 42 W" recommendation is withdrawn with it. Note also that
**`power1_max_interval` was the wrong knob** regardless: 28000 ms is Intel's standard PL1
*tau*, governing the sustained average, while the excursions are ~20 ms. Peak limiting is
PL4/ICCMAX territory, and hwmon exposes no such control here (no `power1_crit`, no
`curr1_crit`).

### The JetKVM / reset-path theory

The JetKVM is **over a year old** and now independently powered. A part that sat there ~10
months before the first reset is not what started this. The case `RESET#` lead has no
correlation behind it either, given the fault predates everything.

### "A uniform ~1.8-year fault, accelerating 2.2×"

Read off lifetime NVMe Unsafe Shutdowns (70 of 104 power cycles) and **wrong**. It averaged
64 events across 632 days, smearing the known, already-fixed Coral cluster across the whole
timeline and hiding both the 15-month clean run and the Aug 4 step change. Superseded by
[The five-year picture](#the-five-year-picture).

### The A380 PCIe link

`03:00.0` reports `2.5 GT/s x1` for both current *and* max, which looks like a catastrophic
fallback. **It is cosmetic.** The card carries an onboard Intel bridge (`01:00.0` =
`8086:4fa1`, `02:01.0`/`02:04.0` = `8086:4fa4`) exposing the GPU and its audio function on
separate downstream buses. The real host link is **`01:00.0` at 16.0 GT/s x8 — full Gen4
x8, fully negotiated.** "PCIe signal integrity on the GPU link" has no supporting evidence.

### The methodological failure behind all of it

Each of these came from fitting a mechanism to whatever had just been measured — PCIe link,
then power magnitude, then transients — and letting the newest number become the theory.
**The clustering was in the data the whole time and was persistently under-weighted in
favour of whatever could be given a decimal point.** Weight the rate structure first; only
then look for a mechanism.

---

## The measurement problem

Observed intervals: **13 h, 3 d 19 h, 6 d 6 h, 6 d 6 h, 22 d**, plus a 15-month gap.

With that spread you **cannot distinguish "fixed" from "lucky" in under ~30 days per
experiment**. Every experiment run before today was underpowered by construction — including
the DDR4-2666 test, called at 3 days on a box that had already gone 22 days clean while
broken.

```
P(zero resets in N clean days | still broken at 1 per 6.3 d):
   30 d -> 0.0085     45 d -> 0.0008     60 d -> 0.0001
```

The way out is not testing faster. It is (a) a **witness** that catches the event directly,
and (b) **swapping the most-suspected part** rather than testing it, when the part costs
less than a month of waiting.

---

## The change made

**Reverted the Frigate GenAI backend from `llama-server` to `ollama`** — restoring the
configuration that ran through the clean era rather than testing a new hypothesis.

```
llama-server   ghcr.io/ggml-org/llama.cpp:server-vulkan   -> Exited
ollama         uberchuckie/ollama-intel-gpu:dev           -> Up, 192.168.1.2:11434
```

`--device=/dev/dri/renderD129` (the dGPU), `OLLAMA_NUM_PARALLEL=1`, and **no
`OLLAMA_KEEP_ALIVE`**, so Ollama's 5-minute default applies.

### The mechanistic difference, and why it is the sharpest one left

**`ollama` unloads the model when idle. `llama-server` holds it resident 24/7.**

| | llama-server | ollama |
|---|---|---|
| model residency | **4.4 GB permanently** (`drm-resident-local0 = 4411924 KiB`) | unloaded after 5 min idle |
| GPU idle state | never leaves an elevated state — 700 MHz against a 300 MHz floor, `runtime_suspended_time = 0` | returns to idle |
| backend | Vulkan | SYCL |

This also explains the otherwise awkward fact that **model size barely mattered**: 28 GB or
4 B, both stayed resident. And it is consistent with the resets landing 4–21 minutes *after*
inference rather than during it.

**It was not LLM inference on the A380 as such** — that ran throughout the clean era under
`ollama` and, earlier, `Intel-IPEX-LLM-Ollama`.

### Accepted costs

- **Ollama 0.9.3** in this image (upstream is 0.34.0), so **Qwen3-VL will not run**. The
  model is `qwen2.5vl:3b` (3.8B Q4_K_M, 3.0 GB) — the clean-era model.
- **SYCL, not Vulkan**, so generation is slower (Vulkan measured +53 % on this card).
- runner context is `--ctx-size 2048` by default, vs llama-server's 8192; Frigate requests
  4096 via `num_ctx`.
- Audio recipe import in Mealie stays non-functional — no audio-capable model. Pre-existing:
  llama-server logged `vision: True, audio: False` for qwen3-vl too.

---

## Verified end state

### Frigate (0.18.0-rc2)

Live running config, read back from `/api/config`:

```
"provider":"ollama"   "base_url":"http://192.168.1.2:11434"   "model":"qwen2.5vl:3b"
```

Config as written:

```yaml
genai:
  default:
    provider: ollama
    base_url: http://192.168.1.2:11434
    model: qwen2.5vl:3b
    provider_options:
      options:            # Ollama params MUST nest here
        num_predict: 150   # Ollama's name for max_tokens
        temperature: 0.2
        repeat_penalty: 1.05
        num_ctx: 4096
    roles:
      - descriptions
      - chat
```

**Generation params must nest under `options:`.** `frigate/genai/plugins/ollama.py` spreads
`{**provider_options, **runtime_options}` straight into `provider.generate(...)`, whose
signature is explicit with no `**kwargs`. Flat params raise
`TypeError: Client.generate() got an unexpected keyword argument 'num_predict'` on **every**
description — Frigate starts fine and fails per event. Verified empirically against the real
client. `max_tokens` does not exist for Ollama. `num_ctx` is read from
`provider_options["options"]["num_ctx"]` (default 4096).

`roles` is `list[GenAIRoleEnum]` — `chat`, `descriptions`, `embeddings`; default is all
three. Listing two drops `embeddings`, which is desirable for a VL model, but check Semantic
Search if you rely on it.

**Proof the chain works** — ollama's access log:

```
[GIN] 2026/09/12 - 09:54:43 | 200 | 2.741s | 192.168.1.5 | POST "/api/generate"
```

192.168.1.5 is frigate, and `/api/generate` is the native endpoint only the ollama plugin
uses.

> **Do not expect an init log line from the ollama plugin.** Unlike `llama_cpp.py`, which
> logs INFO on init, `ollama.py` only has `logger.warning("Error initializing Ollama: ...")`
> on failure. **Silence is success.**

### Mealie

**Mealie nightly no longer configures AI by environment variable.** `OPENAI_BASE_URL` /
`OPENAI_API_KEY` / `OPENAI_MODEL` are gone; only `OPENAI_CUSTOM_PROMPT_DIR` remains, plus a
vestigial `OPENAI_REQUEST_TIMEOUT=900` the Unraid template still sets. An AI-free container
env does **not** mean AI is unconfigured.

Providers live in SQLite tables added by migration `2026-05-18 ... add_table_for_ai_providers`
— `ai_providers` (`name, base_url, api_key, model, timeout`; `api_key` is NOT NULL) and
`ai_provider_settings` (`default_provider_id, audio_provider_id, image_provider_id`). Edited
via **Group Settings → AI Providers**; API `PUT /api/groups/ai-providers/providers/{id}`.

Row verified after the change: `base_url='http://192.168.1.2:11434/v1'` (keep the `/v1` —
Ollama's OpenAI-compatible endpoint), `model='qwen2.5vl:3b'`, api_key preserved by leaving
the dialog field blank, `timeout=900`.

---

## Watch baseline and success criteria

| item | value at 2026-09-12 10:01 |
|---|---|
| boot | **2026-09-12 08:14** |
| NVMe Unsafe Shutdowns | **{70, 60}** ← best tripwire; any increment is a reset |
| `parity-checks.log` | last entry 2026-09-09 16:43 |
| correcting `check P Q` | running, 9.3 % (`mdResyncPos=1629627112` of `17578328012`) — deliberately left to complete, since the reset was unclean |

**30 clean days ≈ 2026-10-12** is the first point at which the revert means anything.
P(zero resets in 30 days | still broken) = 0.0085. The prior quiet era was 1 per 27 d, so
one or two clean weeks is not a result in either direction. **Change nothing else in the
meantime.**

**If it resets anyway:** GPU residency is falsified, the Aug 4 coincidence was luck, and the
next moves are hardware — **PSU first** (genuinely unexcluded; apcupsd samples once a minute
and is blind to a sub-millisecond droop), then board/VRM. Do not revisit the retracted
theories or the failed config levers.

---

## Method notes and gotchas

**No `python3` on the Unraid host, and no `bc`.** Also no `python3` inside the frigate
container. Use bash builtins (`$EPOCHREALTIME`, `read < sysfs`, `$SECONDS`), or
`docker exec -i <container> python3 -` piped from a local file for anything real.

**High-rate sysfs sampling from bash** reaches ~21 ms median / 23 ms max cadence, which is
enough for GPU power and throttle flags:

```bash
SECONDS=0
while [ $SECONDS -lt 40 ]; do
  read -r e < $H/energy1_input
  printf "%s,%s\n" "$EPOCHREALTIME" "$e"
  sleep 0.02
done > /tmp/samp.csv     # /tmp, never /mnt/user
```

**Drive GPU load from the Mac, not from Unraid.** `llama-server`/`ollama` are br0
containers and are unreachable from the Unraid host shell.

**`docker logs` only reaches back to ~04:01** for these containers — Docker Auto Update
recreates them daily. For GPU request history use the app's own database, not the container
log.

**netdata retention is ~2 weeks** and a longer query **silently clamps** rather than
erroring — a Jul 25–Sep 12 `ups_load` request returned only the current day. Always check
the oldest returned timestamp.

**Ollama's `library=cpu` startup line is misleading.** `inference compute id=0 library=cpu
total=125.6 GiB` is the CPU entry. GPU use is proven at model load:
`load_backend: loaded SYCL backend`, `Found 1 SYCL devices: Intel Arc A380 Graphics`,
`model weights buffer=SYCL0 size="3.0 GiB"`. **`/api/ps` showing `size_vram: 0` is cosmetic**
— 0.9.3 does not report VRAM for SYCL.

**`/boot/config/plugins-removed/` mtimes are worthless for dating.** `coral-driver.plg` and
~25 others all share `2025-12-25 02:29` — a bulk flash rewrite, not removal dates.

**Dated `unraid-diagnostics-*.zip` archives contain timestamped `smartctl` output** and are
the only way to pin lifetime counters historically. Found in `/boot/logs/` (20260512,
20260810, 20260816) and `~/Downloads/` on the Mac (**20250430**, the oldest). **Key by
serial, not device name** — NVMe enumeration swaps between boots.

**Graceful shutdowns do not increment NVMe Unsafe Shutdowns.** Verified: the Sep 7 08:47
apcupsd graceful shutdown, the manual power-on, the memtest86+ run and the BIOS trip all
left the pair at `{57,67}`, and the three subsequent resets stepped it exactly
`{58,68} → {59,69} → {60,70}`.

**`netconsole` is not available** — `modinfo netconsole` returns *not found* on
6.18.38-Unraid and there is no `/proc/config.gz`. It would have been the ideal witness; it
needs a custom kernel.

**`efi_pstore` registers but has never been proven to write.** It is a registered backend
(`pstore: Registered efi_pstore as persistent store backend`) and has been empty after all
six resets, which is the basis for "the reset is below the OS." Many boards have too little
efivar space and fail silently. **Calibrate it free on the next planned reboot** with
`echo c > /proc/sysrq-trigger`, then check `/sys/fs/pstore/`.

---

## Query cookbook

```bash
# THE reset ledger -- start = completion - duration; 05:00 starts are scheduled
cat /boot/config/parity-checks.log

# the tripwire (baselines 70 / 60); key by SERIAL, enumeration swaps
for d in /dev/nvme0n1 /dev/nvme1n1; do smartctl -i -A $d | grep -iE "Serial|Unsafe|Power On"; done

# historical counters from a dated diagnostics archive
unzip -p /boot/logs/unraid-diagnostics-20260512-1729.zip \
  "$(unzip -Z1 /boot/logs/unraid-diagnostics-20260512-1729.zip | grep 24274H803093 | head -1)" \
  | grep -iE "Power On Hours|Power Cycles|Unsafe Shutdowns"

# did the kernel record anything? (empty every time so far)
ls -la /sys/fs/pstore/ ; dmesg | grep -iE "mce|whea|hardware error|aer"

# A380: real host link is 01:00.0, NOT 03:00.0 (whose x1 is internal/cosmetic)
for d in 0000:01:00.0 0000:03:00.0; do
  echo "$d $(cat /sys/bus/pci/devices/$d/current_link_speed) x$(cat /sys/bus/pci/devices/$d/current_link_width)"
done

# GPU power envelope + throttle reasons (see Method notes for the sampler)
H=/sys/devices/pci0000:00/0000:00:01.0/0000:01:00.0/0000:02:01.0/0000:03:00.0/hwmon/hwmon5
cat $H/power1_max $H/power1_max_interval
for f in /sys/class/drm/card1/gt/gt0/throttle_reason_*; do echo "$(basename $f) $(cat $f)"; done

# what Frigate actually loaded (no python3 in that container)
docker exec frigate curl -s http://127.0.0.1:5000/api/config | tr "{}," "\n\n\n" | grep -iE "11434|ollama|qwen"

# Mealie's AI provider (read-only; no python3/sqlite3 on the Unraid host)
docker exec -i mealiev1 python3 - <<'PY'
import sqlite3
c = sqlite3.connect("file:/app/data/mealie.db?mode=ro", uri=True)
cols = [r[1] for r in c.execute("PRAGMA table_info(ai_providers)")]
for row in c.execute("SELECT * FROM ai_providers"):
    d = dict(zip(cols, row)); d["api_key"] = "<redacted>"; print(d)
PY

# end-to-end vision check against whichever backend is live
python3 llama-server/crash-watch-vision.py http://192.168.1.2:11434
```
