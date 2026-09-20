# Crash analysis — 2026-09-20

**The seventh reset, and the end of the software investigation.** The ollama revert
of 2026-09-12 was the last software hypothesis standing, and it failed. The GenAI
server, the GPU backend and the model are all exonerated. What remains is hardware.

Investigated 2026-09-20. All timings local (CDT, UTC−5) unless marked.

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
