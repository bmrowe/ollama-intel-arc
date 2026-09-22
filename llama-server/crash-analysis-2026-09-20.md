# Crash analysis — 2026-09-20

**The seventh reset, and the end of the software investigation.** The ollama revert
of 2026-09-12 was the last software hypothesis standing, and it failed. The GenAI
server, the GPU backend and the model are all exonerated. What remains is hardware.

Investigated 2026-09-20. All timings local (CDT, UTC−5) unless marked.

> 🔄 **Read the [addendum](#addendum--the-same-day-what-changed-in-july-and-the-detector-finding)
> first.** Later the same day, Frigate's config history showed object detection had been
> moved from the iGPU onto the A380 between June 24 and August 18 — and stayed there through
> every reset, including the ollama watch. Detection was moved back to the iGPU at 10:52, and
> **that** is the live test (checkpoint 2026-10-11, confidence ≈ 2026-11-01). The "What remains" ranking and "Recommendation"
> below predate it and are superseded. [Addendum 2](#addendum-2--2026-09-21-same-board-different-slots)
> (2026-09-21) shows the Coral and the A380 failed on the same board in different slots: the
> board/platform leads, the PSU is demoted and no longer a fix candidate, and the working
> hypothesis is that keeping detection on the iGPU avoids the trigger — a hypothesis under test,
> not a demonstrated fix (a 22-day clean run already happened under the old configuration).

Continues [`crash-analysis-2026-09-12.md`](crash-analysis-2026-09-12.md), whose watch
this closes. Its evidence-source findings (`parity-checks.log` as the reset ledger, the
five-year episodic shape) still stand; its **action** — revert to `ollama` — is now
answered, negatively.

---

## Contents

- [The event](#the-event)
- [The watch result](#the-watch-result)
- [The power measurement, and its answer](#the-power-measurement-and-its-answer)
- [Eliminated](#eliminated)
- [What remains](#what-remains)
- [Recommendation](#recommendation)
- [Method notes](#method-notes)

---

## The event

Reset at **07:54:29**, pinned from pve's journal.

| source | evidence |
|---|---|
| pve `pvestatd` | first `Connection timed out` to `192.168.1.198:8007` at **07:54:36**, after a 7.26 s connect timeout → death ≈ **07:54:29** |
| pve `pulse-agent` | `no route to host` from **07:55:21** |
| Unraid | kernel boot **07:56:48** (~2 min 20 s POST+boot), `emhttpd: unclean shutdown detected` |

Unclean: **NVMe Unsafe Shutdowns {70,60} → {71,61}**, power cycles 104→105 and 93→94.
An automatic correcting `check P Q` started on the reboot.

**Uptime was 7 d 23 h 40 m** (boot 2026-09-12 08:14) — the second-longest interval of the
current cluster.

**Idle again, no excursion.** netdata pre-crash: RAPL package **28.1 W** (idle baseline),
CPU ~3.6 % user, GPU die 55 °C, UPS load 285–327 W. The last ollama inference completed
**07:52:44**, 1 m 45 s before death — but with 222–400 GenAI calls per day, a two-minute
pre-window covers roughly half the day, so that proximity is not evidence on its own.

Signature unchanged across all seven events: **instantaneous reset, rails up, zero
forensic trace.** `/sys/fs/pstore/` empty, 0 MCE, no AER, no kernel log entry.

Unrelated the same morning, both checked and dismissed: the pve→PBS `vzdump` ran
02:00–02:05 and completed clean, and the Fix Common Problems "Out Of Memory" email is the
known stale re-alert on the 2026-09-16 Frigate cgroup kill, not a new event.

---

## The watch result

The Sep 12 revert swapped a bundle — server (`llama-server` → `ollama` 0.9.3), backend
(Vulkan → SYCL), model (Qwen3-VL 4B → `qwen2.5vl:3b`) and context (8192 → 2048/4096) —
on the argument that it restored the configuration of the 15-month clean era. The
success criterion was **30 clean days (≈ 2026-10-12)**; it lasted **8**.

Intervals across the current cluster:

| # | reset | interval |
|---|---|---|
| 1 | Aug 4 06:41 | — |
| 2 | Aug 10 13:09 | 6 d 6 h |
| 3 | Aug 16 19:28 | 6 d 6 h |
| 4 | Sep 7 20:20 | 22 d 1 h |
| 5 | Sep 8 09:27 | 13 h |
| 6 | Sep 12 08:12 | 3 d 19 h |
| 7 | **Sep 20 07:54** | **7 d 23 h** |

- llama-server era: 6 resets in 37.6 powered days = **1 per 6.3 d**
- ollama era: 1 reset in 8.0 days = **1 per 8.0 d**

**No measurable change.** At the pre-revert rate, P(a reset by day 8) = **72 %**, so this
outcome is exactly what "nothing changed" predicts. The 8-day survival carries no
information in the other direction either.

---

## The power measurement, and its answer

On 2026-09-18 the A380's power draw under SYCL was sampled at 21 ms (same method as the
2026-09-12 Vulkan run: bash builtins reading `energy1_input`, output to `/tmp`, load driven
from the Mac). Three uncached runs, each three real 1280×720 camera frames (~2,000 prompt
tokens) — the shape of Frigate's slow multi-image calls.

| phase | SYCL / ollama | Vulkan / llama-server (Sep 12) |
|---|---|---|
| prompt-eval mean | **45.5 / 46.5 / 47.3 W** (83–86 % of the 55 W cap) | **54.9 W** (99.8 % — pegged) |
| prompt-eval p95 | 53.5–54.2 W | — |
| 21 ms max | 56.1 / 59.1 / 57.0 W | 65.6 / 52.0 W |
| 100 ms-avg max | 53.3 W | — |
| generation mean | 42.0–42.6 W | — |
| clock | 2450 MHz (RP0) in all phases | 2450 MHz |

Idle after: 16.9 W median, 0 MHz.

At the time this looked like modest support for "the old setup ran the card pinned at its
power limit, the new one doesn't." **The reset answers it: a ~15 % reduction in sustained
GPU power, sustained for eight days, changed nothing.** Peaks overlapped between the two
backends anyway, so the transient version never had support.

**Gotcha worth keeping:** ollama's prompt cache turns a repeated image prompt into a 0.3 s
prompt eval. Every power run must use fresh frames or it measures nothing.

---

## Eliminated

Everything in this list has now been tested and failed to prevent a reset:

| lever | tested | outcome |
|---|---|---|
| GenAI server (llama-server vs ollama) | Sep 12 – Sep 20 | both reset |
| GPU backend (Vulkan vs SYCL) | same | both reset |
| Model (Qwen3-VL 4B, 35B MoE, qwen2.5vl 3B) | Aug 16, Sep 12 | all reset |
| Sustained GPU power (55 W pegged vs ~46 W) | Sep 18–20 | no effect |
| `pcie_port_pm=off`, ASPM clears | Aug 16 → | reset Sep 7 |
| `intel_idle.max_cstate=1` | Sep 7 → | reset Sep 8, mid-parity-check |
| DDR4-3200 → 2666 | Sep 8 → | reset Sep 12 |
| BIOS F25a | Aug 9 → | resets after |

Also dead from earlier work and not to be re-opened: the JetKVM, the PCIe link (the Gen1
x1 reading is the card's internal bridge, the host link is Gen4 x8), the power-transient /
slot-overdraw derivation, the 6 d 6 h "cadence", and `power1_max_interval` as a knob.

**Every software and firmware lever available on this machine has now been pulled.**

---

## What remains

1. **PSU transient (RM850x).** Unexcluded throughout. apcupsd samples once per minute and
   cannot see a sub-millisecond rail droop; "PSU latched off" is excluded, "PSU transient"
   is not. A swap is a *fix*, not a test — if it works, service continues.
2. **Board / VRM / CPU.** More expensive, and only after the PSU.
3. **Any LLM inference on the A380 at all.** Still formally open: the quiet era ran the
   same card on openvino detection only, at 1 per 27 d. Testing it means turning GenAI off
   for ~3 weeks and losing the feature, with the same slow-measurement problem as before.
   > ⚠️ **Wrong, corrected in the [addendum](#-the-detector-finding):** the quiet era ran
   > detection on the **iGPU** (`device: GPU` = GPU.0), not the A380. The A380 was near idle.

Not a candidate any more: **a different GPU.** Both backends and three models reset; a new
card does not address what is left, and a 320 W card would add the largest transient load
in the machine to a box with suspect power delivery.

**The measurement floor still dominates.** Observed intervals span 13 h to 22 d, so no
experiment here resolves in under ~3 weeks, and there are at least two hypotheses left.
Swapping the most-suspected part beats waiting out another soak window.

---

## Recommendation

- **Swap the PSU.** Top-ranked unexcluded candidate, and it fixes rather than tests.
- **Add the serial console** (~$20: COM-header cable, null-modem, USB-RS232 on pve;
  `console=tty0 console=ttyS0,115200n8` via the Boot Parameters UI). It is a passive
  witness, so it does not interfere with the PSU swap, and it converts "we infer there was
  no kernel output" into "we observed there was none."
- **Leave GenAI running.** It is now known not to matter for the reset rate.
- **Stop pulling config levers.** The table above is the record of that approach.

---

## Method notes

- **Pin the time from pve's journal**, not netdata: `pvestatd` polls
  `192.168.1.198:8007` every ~9 s and logs every failure, and its connect timeout is
  7.26 s, which must be subtracted. netdata's per-chart last samples were staggered
  07:48–07:51 here — the usual dbengine flush artifact, not a staged failure.
- **Container json logs survive the reset** (they are on the cache pool). The frigate
  container was not recreated by the reboot, so its log still holds pre-crash lines;
  ollama's does too, via `docker inspect --format "{{.LogPath}}"`.
- **`dmesg -T | grep "Killed process"`** after a reboot shows only kills from the *current*
  boot; Fix Common Problems re-alerts on older ones until the ring buffer clears.

---

## Addendum — the same day: what changed in July, and the detector finding

Everything below was established after the sections above, still on 2026-09-20.

### Upstream power is exonerated

**Eaton 5PX alarm log** (`alarmLogs-2.csv`, 565 events, 2025-07-04 → 2026-09-12): **nothing
within ±15 minutes of any of the seven resets.** The UPS records plenty — 60 "On battery"
events, nearly all 1–2 s utility dropouts the server rode through, and the 2026-09-07
breaker trip exactly as independently known (on battery 08:28:28, back 08:51:20 CDT), which
validates the log's clock. Only one AVR/buck event in fourteen months (July 2025).

**Eaton measures log** (`logMeasures-5.csv`, 1-min samples, Sep 14 → Sep 20, no gaps): input
117.2–122.8 V, 59.9–60.0 Hz, battery 100 % throughout, output tracking input. At the Sep 20
reset input was 120.0 → 120.4 V; the only trace is closet load dropping 285 → 255 W while the
server was down. **Power into the box never moved; the box just died.**

Upstream is fully accounted for. The utility is disturbed often and the server never resets
then; it resets at unremarkable moments instead.

### Userspace was healthy and unaware

All 25 container json logs survive a reset (cache pool). Last pre-death lines: netdata
07:53:37, frigate 07:53:28, mealie 07:53:22, Pulse 07:53:23, ollama 07:52:44. In the ten
minutes before death the only error lines were two routine recurring ones — netdata's missing
`scripts.d` (every minute, all day) and proxmox-backup-server's `os error 107` (every 5 min,
including hours after the reboot). No stalls, GPU errors, OOM or I/O errors. Together with the
empty pstore, zero MCE and rails up: the failure is below everything that can log.

### Correlations checked and rejected

- **pve apt upgrades** (Sundays 02:00 plus ad-hoc): 2 of 7 resets fall within 24 h of one;
  chance predicts 1.3 (those windows cover 19 % of the period). No signal.
- **Time of day:** all seven resets fall between 06:41 and 20:20 (a 13.6 h window), ~3 % if
  uniform. Found post hoc with n = 7 — noted, not acted on.

### What changed in July

| date | change |
|---|---|
| Jul 8 | **Unraid 7.3.1 → 7.3.2, kernel 6.18.33 → 6.18.38** |
| Jul 23 | zfs modprobe config edit |
| Jul 25 | `go2rtc_frontdoor` container (standalone go2rtc containers since removed — streams now in Frigate's own go2rtc block) |
| Jul 30 | llama-server deployed |
| Aug 3 22:12 | compose.manager plugin removed |
| **Aug 4 06:41** | **first reset** |

**The kernel is not implicated.** Upstream stable changelogs 6.18.34–6.18.38 and 6.18.39–6.18.47
(the 7.4.0-beta.2 kernel) contain no ASPM, AER, DPC or link-reset changes, and every `i915`
change is display-path — PSR/Panel Replay, eDP link rates, DP Adaptive Sync SDP, HDMI, VRR,
HDCP — or GEM/context fixes. The A380 drives no panel. `drm/xe` changes do not apply (the card
runs `i915`). Beyond the kernel, 7.3.2 changed Docker 29.5.2 → 29.5.3, ZFS 2.4.2 → 2.4.3,
`CONFIG_USB_AUTOSUSPEND_DELAY=-1` (less aggressive PM), a WebGUI CVE and a cosmetic Intel GPU
PCI-speed reporting fix. Also, 27 clean days on 6.18.38 preceded the first reset. Caveat:
Unraid's own kernel patches are not in upstream changelogs. **The rollback to 7.3.1 (still in
`/boot/previous`) was not pursued.** For the record, the `r8125` plugin has builds for
6.18.33, 6.18.38 and 6.18.47, so a kernel move in either direction would not strand the NIC.

### ⭐ The detector finding

Frigate's `backup_config.yaml` (written 2026-06-24 21:07) versus the weekly appdata backup of
2026-08-18 and the running config:

```yaml
# 2026-06-24
detectors:
  arc_gpu_1: {type: openvino, device: GPU}
  arc_gpu_2: {type: openvino, device: GPU}
  arc_gpu_3: {type: openvino, device: GPU}

# 2026-08-18 through 2026-09-20 10:52
detectors:
  arc_gpu_1: {type: openvino, device: GPU.1}
#  arc_gpu_2 / arc_gpu_3 commented out
```

OpenVINO's plain `GPU` is **GPU.0 — the UHD 770**. `GPU.1` is **the A380**. So object
detection moved from the iGPU onto the A380 somewhere between **June 24 and August 18**, which
brackets the August 4 onset. The Frigate+ model also changed in that window
(`plus://ca4840…` → `plus://34b93b…`), and the genai `base_url` moved from `.80` to `.2`.

**The exact date could not be recovered:** Frigate prunes events at 30 days, the appdata
backups (`/mnt/user/appdata backup/`, weekly, 32-day retention) begin Aug 18, and the btrfs
cache has no snapshots. The Frigate+ account's model history would pin it.

**Why it matters:** detection ran on the A380 through **all seven resets, including the entire
ollama watch.** The revert swapped the small intermittent workload (LLM calls) and never
touched the large continuous one. That explains why it changed nothing.

| era | accelerator doing continuous detection | resets |
|---|---|---|
| Coral dual-TPU (~4 W) | Coral PCIe card | daily |
| A380 installed, detection on iGPU | none — A380 near idle | ~zero for 15 months |
| After the switch to `GPU.1` | A380 | ~1 per 7 days |

A 4 W card producing worse resets than a 50 W one argues against power *magnitude* (PSU,
slot overdraw) and toward the *behaviour* the Coral and the working A380 share: sitting idle
and bursting thousands of times an hour, cycling device power states. The HBA, which moves far
more data but never idles down, has never been associated with a reset.

### The change made — 2026-09-20 10:52

```yaml
detectors:
  arc_gpu_1: {type: openvino, device: GPU}
  arc_gpu_2: {type: openvino, device: GPU}
```

Verified live:

| | A380 (03:00.0) | iGPU (00:02.0) |
|---|---|---|
| clock | **0 MHz** | 731–1240 MHz |
| RC6 residency | **96–100 %** | 22–48 % |
| engines | **all 0.00 %** | render 31–60 %, video 17–24 %, enhance 9–14 % |

Inference 17.7–20.5 ms per detector (was 9.8 ms on the A380); `skipped_fps` 0.0 on all eight
cameras; worst-case demand 8 cameras × 5 fps = 40/s against ~113/s capacity for two
detectors. CPU package power rose from ~28 W to 36–44 W as inference moved into the package —
**the power baseline for this watch is not comparable with earlier ones.**

**Frigate's headline GPU % is not a saturation metric.** `frigate/util/services.py` (0.18.0)
computes `min(100, render + compute) + min(100, video + video-enhance)`, capped at 100 — a sum
of independent engines. It read ~93 % while the iGPU sat fully idle a third of the time. Judge
headroom by `skipped_fps`, inference time and RC6 residency.

### Hypothesis and watch

> **The fault is triggered by the A380 doing continuous inference work, not by which software
> drives it.** Mechanism unknown: slot power delivery, or power-state transition behaviour.

- **Baseline:** boot 2026-09-20 07:56, config changed 10:52, **NVMe Unsafe Shutdowns {71, 61}**,
  `parity-checks.log` as the confirming ledger.
- **Duration:** checkpoint **2026-10-11**; confidence needs ~6 weeks, **≈ 2026-11-01**. (The
  "~5 % odds after three weeks" figure originally given here assumed a steady rate and ignores a
  22-day clean run under the old configuration — see
  [Calibration](#calibration--what-a-clean-watch-can-and-cannot-show).)
- **Falsifier:** another reset.
- **Caveats:** a *partial* subtraction — GenAI (~200–400 calls/day) still runs on the A380. The
  switch date is unknown; if it was late June, weeks of clean running followed and the story
  weakens considerably. The 2024 cluster is unexplained by this, as by everything else.
- **Do not install the new case, PSU or a board during the watch.** Parts may arrive; they stay
  boxed until the watch reports.

---

## Addendum 2 — 2026-09-21: same board, different slots

The detector finding left one question open: when the Coral and the A380 each produced a reset
cluster, was it the same motherboard, and the same slot? The April 2025 Unraid diagnostics
(`unraid-diagnostics-20250430-1735.zip`, taken in the Coral era) answer both.

- **Same board:** `Gigabyte B760M GAMING X AX DDR4`, BIOS F19 (09/27/2024).
- **No A380 installed.** The Coral dual Edge TPU (`1ac1:089a` ×2, behind an ASMedia ASM1182e
  x1 Gen2 packet switch) was the only accelerator.
- The Coral ran continuous detection through the **2024** cluster as well as 2025 (confirmed
  by Bryan), so all three clusters coincide with a PCIe accelerator doing continuous detection
  on this board.

| slot | Coral era (Apr 2025) | now |
|---|---|---|
| CPU x16 (`00:01.0`) | LSI SAS2008 HBA | **A380** |
| chipset (`00:1c.4`) | **Coral** | LSI SAS2008 HBA |

The accelerator and the HBA **swapped slots between eras**. The accelerator's slot was
associated with resets both times; the HBA — which moves far more data — never was, in either
slot. (The 2025 mapping is inferred from sequential bus numbering; that `lspci` dump has no
tree. It agrees with today's `lspci -t`.)

**What this rules out:** a single bad slot (both the CPU-attached and chipset-attached paths are
implicated), a specific card (two unrelated vendors and drivers, ~4 W and ~50 W), a specific
BIOS (F19 and F25a), and "PCIe load" in general (the HBA).

**Ranking now:** the **board / platform** leads. The CPU's PCIe and power-management side is the
only other shared platform element, and a 65 W non-K i5 with no degradation history is a weak
suspect. The **PSU is demoted** — a ~4 W card producing daily resets is not a supply-capacity
problem — and is no longer a fix candidate.

*Observation, not a theory:* both accelerators carry an onboard PCIe switch (the Coral's
ASM1182e; the A380's internal `8086:4fa1` bridge). The HBA carries none.

### The working hypothesis, and the rule that goes with it

This is the best-supported hypothesis so far, **not a demonstrated fix** — see
[Calibration](#calibration--what-a-clean-watch-can-and-cannot-show) below.

- **Detection stays on the iGPU.** It is the configuration the box ran cleanly for 15 months,
  costs ~8–10 W of package power, and keeps up (0 skipped detections at 8 × 5 fps).
- **Do not buy a new GPU or TPU for detection on this board.** It would reproduce the same
  idle↔burst workload on the same platform. If an accelerator is wanted again, **replace the
  board first**.
- Intermittent GenAI on the A380 is being tested by this watch as a side effect: a long clean
  run with GenAI still on the card would suggest that workload is tolerable.
- Recommended guardrails: a comment above Frigate's `detectors:` block pointing here, and a
  boot-time alert when the NVMe Unsafe Shutdown count rises.

### Calibration — what a clean watch can and cannot show

Every earlier mechanism in this investigation was stated with conviction and failed: the 6 d 6 h
cadence, the power-transient / slot-overdraw derivation, C-states, DDR4-2666, `pcie_port_pm`,
ASPM, and the ollama revert. The pattern was fitting a mechanism to the latest measurement. The
detector hypothesis gets the same scrutiny.

**Counter-evidence that must stay attached:** the **22-day clean run from Aug 16 to Sep 7
happened with detection already on the A380** — the supposedly bad configuration. So a
three-week clean watch is within what the old configuration has already done once. The
"three clean weeks leaves ~5 % odds of coincidence" figure given above assumed a steady average
rate and is **too generous**. Other open weaknesses: the date of the switch to `GPU.1` is
unknown (a late-June switch would mean weeks of clean running afterwards and a much weaker
timing link), the fault is episodic and has gone quiet on its own before, and the evidence is
three clusters.

**Decision points:**
- **2026-10-11 is a checkpoint, not a verdict.** A reset before then falsifies the hypothesis;
  a clean run means only "consistent with".
- **Confidence needs ~6 weeks clean — about 2026-11-01** — twice the longest clean interval
  observed under the old configuration.
- **If a reset recurs:** first take the A380 fully out of service (GenAI off it, or pull the
  card) — free, and the only subtraction not yet made. Only then consider a board.

Do not describe this change as "the fix" before that point.
