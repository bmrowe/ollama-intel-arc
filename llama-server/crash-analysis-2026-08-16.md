# Crash analysis — 2026-08-16

> **This supersedes `crash-analysis-2026-08-10.md` and the
> [crash section of MOE.md](MOE.md#deployed-vs-measured--this-is-a-crash-fix-not-drift`).**
> Not because that analysis was careless, but because it was built on three crash
> timestamps that were all wrong, and on a failure mode — a hard lockup — that did not
> happen.

**Headline: the Unraid host is not hanging. It is warm-resetting and rebooting itself,
roughly every 6 days 6 hours, with no kernel output of any kind — and the platform is
physically incapable of recording why.**

Investigated 2026-08-16 evening. All timings local (CDT, UTC−5) unless marked.

---

## Contents

- [The corrected timeline](#the-corrected-timeline)
- [Why the old timestamps were wrong](#why-the-old-timestamps-were-wrong)
- [It is a reset, not a hang, and not a power loss](#it-is-a-reset-not-a-hang-and-not-a-power-loss)
- [Conditions at the moment of death](#conditions-at-the-moment-of-death)
- [What has been ruled out](#what-has-been-ruled-out)
- [Why nothing logs — the platform inventory](#why-nothing-logs--the-platform-inventory)
- [The cadence, and the tension it creates](#the-cadence-and-the-tension-it-creates)
- [Instrumentation built tonight](#instrumentation-built-tonight)
- [Changes in flight and the prediction](#changes-in-flight-and-the-prediction)
- [Levers not yet pulled](#levers-not-yet-pulled)
- [Method notes and gotchas](#method-notes-and-gotchas)

---

## The corrected timeline

Derived from netdata `system.cpu` null-gap scans at 2-minute resolution, cross-checked
against the Eaton 5PX's per-minute output-power log.

| event | last sample | resumed | outage | nature |
|---|---|---|---|---|
| **Aug 4** | 06:38 | **06:46** | ~8 min | **unattended reset** — nobody touched the machine |
| Aug 9 | 11:44 | 12:30 | ~46 min | deliberate — BIOS flash to F25a |
| Aug 9 | 12:36 | 12:50 | ~14 min | deliberate — second reboot |
| **Aug 10** | 13:10 | **13:14** | ~4 min | **reset** |
| **Aug 16** | 19:18* | **19:31** | ~3 min | **reset** |

\* `system.cpu` stops at 19:18 to dbengine flush loss. The A380 temperature chart
survived to **19:27:45**, and the Eaton shows output power dipping from ~297 W to
255–270 W at 19:28–19:30 before rising to 322 W as the box POSTed. True crash ≈ **19:28**.

**Aug 5–8 and Aug 11–15 are completely clean.** No gaps at all.

### Intervals

Computed from **resume** times, which are immune to flush loss — data coming back is a
hard fact, whereas "last sample" understates by up to ~15 minutes and varies per chart.

| from → to | interval |
|---|---|
| Aug 4 06:46 → Aug 10 13:14 | **6d 6h 28m** |
| Aug 10 13:14 → Aug 16 19:31 | **6d 6h 17m** |

**Eleven minutes apart. 0.12%.**

### Onset is sharp

`system.uptime` climbs monotonically from a boot around **July 9** to **2,240,030 s
(25.9 days)** at Aug 3 23:12. No reboots for nearly a month, then Aug 4. The machine was
not chronically marginal — it was solid, and then abruptly wasn't.

---

## Why the old timestamps were wrong

`crash-analysis-2026-08-10.md` records **Aug 4 04:02** and **Aug 10 10:32**. Both were
read off the last syslog line before a quiet stretch.

**An idle Unraid box routinely goes one to two hours without logging anything.** On
Aug 16 the syslog record has gaps of 1h45m (12:29→14:15) and 2h12m (16:30→18:42) during
perfectly healthy operation. Silence in syslog carries no information about liveness.

The metrics contradict both figures directly:

- **Aug 4**: clean, unremarkable samples at 04:04, 04:06, 04:08 and **04:10**. The box was
  alive and idle ten minutes after it is recorded as having locked up.
- **Aug 10**: `system.cpu` is unbroken from 10:00 through 13:00. There is no gap anywhere
  near 10:32.

### Consequence: the Docker Auto Update claim is unsupported

[MOE.md:682](MOE.md) states the 04:00 auto-update "restarted the container unattended and
directly triggered the Aug 4 lockup." The 04:02 spike is real — Frigate 178.6% (llama-server
going away underneath it), llama-server 6.5% system, system CPU 14.7% user — but it
**resolves to baseline by 04:04 and the box carries on for another two and a half hours.**

Excluding llama-server from auto-update remains defensible on one-variable-per-restart
grounds. It is not a crash fix, and it did not cause Aug 4.

---

## It is a reset, not a hang, and not a power loss

Three independent lines converge.

**Not a hang.** A hung machine sits there until someone cuts power. All three outages are
3–8 minutes and the box came back on its own. Bryan confirmed he did not power-cycle it on
Aug 4 at 06:40.

**Not a power loss.** BIOS **`AC BACK` was set to `Always Off`** for all three events —
verified in firmware on 2026-08-16. A machine that genuinely lost power would have stayed
dark until the button was pressed. It recovered by itself, three times.

> `AC BACK` was changed to `Always On` on 2026-08-16 for operational reasons (auto-recovery
> from a real outage). The finding was already collected and is not affected.

**So: a warm reset.** The platform resets and re-POSTs without the supply ever entering an
off state. Candidates that produce that: triple fault, memory-controller fault, or a fatal
PCIe error escalated to a platform reset.

This also explains the otherwise-puzzling UPS observation — output power fell only ~37 W
during the Aug 16 "outage". The machine never stopped drawing power. It restarted.

---

## Conditions at the moment of death

Last surviving sample per chart, Aug 16 event:

| metric | value | reading |
|---|---|---|
| A380 die temperature | **55.3 °C** | flat all evening |
| A380 power alarm | `clear=1, warning=0, fault=0` | no alarm |
| CPU package temperature | **54.2 °C** | cool |
| CPU package power (RAPL) | **28.6 W** | idle-normal |
| RAM free | **~43 GB** of 128 GB | no pressure |
| `mem.oom_kill` | **0** | none, ever |
| CPU | ~4% user, ~2% system | idle |
| UPS load | 285–347 W | normal |
| llama-server | idle since 19:16 | not mid-inference |

Nothing was moving. No alerts fired (`/api/v2/alerts` clean).

**Honest limit:** dbengine flush loss means the final 1–3 minutes are missing from every
chart. A spike inside that window would not have been recorded. That said, a 55 °C part
does not thermally trip in 90 seconds, so thermal is out regardless.

---

## What has been ruled out

| hypothesis | evidence against |
|---|---|
| **GPU / VRAM exhaustion** | Zero `fence\|i915\|drm\|segfault` hits across the full week of retained syslog covering the entire post-Aug-10 period. The escalating fence timeouts (Jul 22 ×5, Jul 30 ×3 and ×4, Aug 2 ×7 + segfault) stopped completely after the Aug 10 config fix — **and the box reset anyway on Aug 16.** The fix worked and was not addressing what kills this machine. |
| **Thermal** | 55.3 °C GPU, 54.2 °C CPU package, both flat. |
| **Memory exhaustion / OOM** | 43 GB free of 128 GB; `mem.oom_kill` zero across every sample. |
| **Kernel-side accumulation** | Tested explicitly across the whole Aug 10→16 interval: slab (unreclaimable 557→610 MB, noise), KReclaimable, KernelStack, PageTables, VmallocUsed (one step on Aug 13), Percpu, `Committed_AS` (oscillates 79–101 GB), `mem.available` (oscillates 73–94 GB). **No monotonic ramp.** |
| **Kernel panic / oops** | `efi_pstore` registered as a backend at boot and its store is **empty**. Records persist in EFI variables until deleted, and Unraid has no service that clears them. The kernel never reached its panic path. |
| **Uptime-driven accumulation** | A clean, deliberate reboot on Aug 9 ~12:30 did **not** reset the clock — Aug 10 fired ~24h later but 6d 6h 28m after Aug 4. |
| **BIOS F25a** | Flashed Aug 9 (the two deliberate gaps), five days **after** the first reset. Did not start it; did not fix it. |
| **Raptor Lake Vmin shift** | i5-13500 (family 6, model 191, stepping 2), microcode `0x3e` on a BIOS built 2026-07-29 — current. And the box is CPU-idle when it dies; Vmin failures are load-correlated. |
| **The UPS** | Eaton 5PX measures log: 8,533 consecutive 1-minute samples Aug 11–17, **no gaps**, battery pinned at 100% / 50.8 V, input 116.0–122.6 V, no transfer to battery. Alarm log demonstrably records `Group 1/2 \| Group is ON/OFF`, `Sequential shutdown scheduled`, `Output \| Load not powered`, transfers and utility loss — and contains **four entries in all of August**, all at Aug 9 12:25, a ~1.2 s utility dropout absorbed on battery. Nothing at any reset. Load segments included. |
| **Site power** | Proxmox (`pve`) ran Jul 12 → Aug 9 and has been up continuously since Aug 9 11:32 — through Aug 10 and Aug 16. Nothing else on the network blinked. |
| **PSU** | Warm resets, not power loss (see above). Rails healthy in firmware: +12V 12.132, +5V 5.062, +3.3V 3.274, Vcore 1.224, DRAM 1.197. RM850x 850 W running at roughly 15–25% load. |
| **Disks** | Seven array drives plus two NVMe. All zero on pending sectors, offline uncorrectable, UDMA CRC and reported-uncorrect. One parity drive (`ZR5A2ADP`) shows 3 reallocated sectors; one drive one command timeout. NVMe both `Critical Warning 0x00`, zero media errors, 13% and 15% wear. |
| **Memory overclock** | **XMP Disabled.** 128 GB running its native JEDEC 3200 profile at 1.197 V. Not an overclock. |
| **ASPM as platform configuration** | Platform Power Management (the ASPM master switch) already `Disabled`; Native ASPM `Disabled`. Firmware was never applying ASPM. |

---

## Why nothing logs — the platform inventory

This was checked exhaustively so it does not need re-checking. **Every mechanism that
could witness a reset is absent on this hardware.**

| mechanism | status |
|---|---|
| BMC / IPMI | **none** — B760M GAMING X AX is a consumer board |
| ACPI **BERT** (previous-boot error record) | **absent** — no BERT, HEST, ERST or EINJ tables exist |
| SMBIOS **Type 15** System Event Log | **absent** — `dmidecode --type 15` returns no structure |
| **ramoops** | **absent** — not a module; `CONFIG_PSTORE_RAM` not in Unraid's kernel |
| netconsole / watchdog / hung-task | **compiled out** of Unraid's kernel |
| `efi_pstore` | present, but fires **only** from `kmsg_dump` on panic/oops — a path a hardware reset never takes |
| mcelog | daemon runs, but `/var/log/mcelog` is RAM-backed and wiped every boot |

Every logging layer needs a CPU that is still executing kernel code. All three remaining
suspicions stop the CPU. **The silence is not a gap in the investigation — it is a
property of the failure class**, and it is why the July fence timeouts *were* logged (card
failing survivably, kernel alive) while the resets are not.

External witnesses are the only instruments available. That is what tonight built.

---

## The cadence, and the tension it creates

Two intervals agreeing to **0.12%** across 150 hours is not what workload-triggered or
random hardware faults look like. It is what a timer looks like. And the clock is
**wall-clock, not uptime** — it survived a deliberate reboot.

**But there is no timer.** Searched and eliminated:

- RTC alarm — `wakealarm` empty, `alarm_IRQ: no`, `alrm_pending: no`, CMOS battery okay
- cron — stock Slackware crontab, nothing custom; `/etc/cron.d/` holds only the generated `root` file
- User Scripts — six scripts, **none has a schedule**
- BMC — none exists
- UPS scheduling — alarm log shows no scheduled action of any kind
- kernel memory accumulation — flat

Nothing in that machine keeps a 150-hour clock. Which leaves two possibilities, and the
evidence does not currently distinguish them:

1. Something keeps time that we have not found.
2. **Three events and two intervals is thin, and the agreement is coincidence.**

0.12% is exactly the kind of number that fools people. Hold it loosely.

---

## Instrumentation built tonight

Everything here survives the Unraid host dying.

### Remote syslog — Debian LXC `110` (`syslog`) on Proxmox

- Reachable via `pct enter 110`; files at `/var/log/remote/192.168.1.198.log{,.1}`
- rsyslog dynaFile template, `/etc/logrotate.d/remote`
- **Retention raised from `rotate 1` to `rotate 14`** (weekly ⇒ ~3 months, ~1 MB total)
- **AER restored** — see [changes](#changes-in-flight-and-the-prediction); PCIe errors now
  land here with three months of history

### netdata parent — same LXC

- Parent `v2.11.0-23-nightly` (apt, netdata edge repo); child on Unraid `v2.11.0-20-nightly`
- Child streams to `192.168.1.195:19999`; config in
  `/mnt/user/appdata/netdata/config/stream.conf`, key section in the parent's
  `/etc/netdata/stream.conf` with `allow from = 192.168.1.198`
- **Query the parent, not the child**: `http://192.168.1.195:19999/host/unraid/api/v1/...`
- Verified: 1-second resolution, ~25 h retention (replication backfilled a day on connect),
  ~12 MB/h growing to a ~1 GB tier-0 plateau in ~3.5 days on 15 GB free
- All forensic charts confirmed present through the parent: i915 temp and power alarm, CPU
  package temp, RAPL, apcupsd load, `system.ram`, `mem.oom_kill`, `cgroup_llama-server.cpu`
- Unattended upgrades enabled in the LXC with `Origins-Pattern { "origin=Netdata"; }` so the
  parent cannot fall behind the child

**This is the piece that matters.** The parent writes points as they arrive, so there is no
unflushed tail. The next event will have a last-known-good sample on *every chart
simultaneously*, at the second the machine died.

### Other witnesses

- **Eaton 5PX** measures + alarm logs, via its Gigabit Network Card web UI — independent of
  the host entirely
- **NVMe unsafe-shutdown baselines: 57 (`nvme0n1`) and 67 (`nvme1n1`).** A tick to 58/68
  confirms abrupt termination independently of netdata
- **`/sys/fs/pstore` now mounted** at boot via `/boot/config/go`, in case a panic ever does occur

---

## Changes in flight and the prediction

Three changes, all made 2026-08-16 evening, ahead of the next predicted event.

| time | change | tests |
|---|---|---|
| ~21:00 | llama-server **35B MoE → dense `Qwen3-VL-4B-Instruct-Q4_K_M`** + `mmproj-F16.gguf`, `N_CPU_MOE` removed, `CTX_SIZE` 32768→**8192**, `BATCH` 2048→**512** | GPU and PCIe **workload** — the 35B streamed 38 layers of expert weights across PCIe on every token; the 4B is fully resident and does none of that |
| ~22:00 | `pcie_port_pm=off` (kernel parameter, GRUB default entry) | PCIe port runtime power management |
| ~23:00 | ASPM cleared on `02:04.0` and `04:00.0` via `setpci`, persisted in `/boot/config/go` | PCIe link power states |

> ⚠ **`CTX_SIZE` and `BATCH` do not transfer between these models.** A first attempt kept
> the 35B's 32768/2048 and landed at **5.64 GiB with a Vulkan `ErrorOutOfDeviceMemory`** —
> ~300 MiB free, tighter than the configuration that preceded Aug 4, with the vision buffer
> failing to allocate while the server still reported `model loaded`. The 35B is
> hybrid-linear-attention with a tiny KV and only 2 expert layers resident via `-ncmoe 38`;
> the dense 4B at `-ngl 99` is fully resident with full attention on every layer.
> **Settled at 4369960 KiB = 4.17 GiB, ~1.78 GiB free, no OOM** — then **4418400 KiB = 4.21 GiB (~1.73 GiB free) after the 2026-08-17 04:01
> Docker Auto Update pulled a new llama.cpp build.** +47 MiB, benign, but it is the
> current baseline; a text probe after that update returned `finish=stop` at 38 tokens
> and an image probe was described correctly, so neither the template nor the vision
> path regressed — slightly *below* the 35B's
> 4.26 GiB.

### ASPM — what was actually found

The only two links in L1 anywhere in the system were `02:04.0` (a bridge) and `04:00.0`
(the DG2 audio function). Everything else — both CPU root ports, all six chipset root
ports, both NVMe, the LSI HBA, the AX210, the RTL8125, **and the A380's own graphics
function at `03:00.0`** — reported ASPM Disabled.

Topology matters here: `01:00.0` fans out to `02:01.0 → 03:00.0` (GPU) and
`02:04.0 → 04:00.0` (audio). **Both L1 links are on the audio branch, not the GPU's data
path.** That weakens ASPM as a suspicion considerably. It was cleared anyway because it
costs two register writes.

Also worth recording: the kernel logs
`pci 0000:03:00.0: ASPM: overriding L1 acceptable latency from 0x0 to 0x7` — the A380
declares it can tolerate *zero* L1 exit latency and the kernel overrides that to maximum
as a generic quirk.

### Prediction

**2026-08-23, ~01:53** (Aug 16 19:31 + 6d 6h 22m), ±~15 min.

- **Fires on schedule** with the A380 barely loaded → llama-server, the model, and the GPU
  workload are eliminated together, and very little is left standing.
- **Passes clean** → either one of the three changes fixed it, or the cadence was never
  real. Reintroduce one variable per subsequent window (~Aug 29) to find out which.

---

## Levers not yet pulled

In rough order of promise:

1. **CPU PCIe Link Speed → Gen3** (BIOS, currently `Auto`). Standard fix for marginal
   signal integrity on a GPU link; a fatal PCIe error escalating to a platform reset fits
   the warm-reset picture. Now a 30-second trip since Fast Boot is disabled.
2. **Memory multiplier below 3200.** Not an overclock, but four dual-rank DIMMs at 3200 is
   a demanding 2-DIMM-per-channel config for a Raptor Lake IMC even at JEDEC.
3. **Powered USB hub for the JetKVM.** It currently draws power from the target, so it
   reboots along with it and sees nothing until i915 loads. On independent power it stays
   awake through a reset and can **show the console at the moment it happens** — the one
   witness class this platform otherwise lacks entirely.
4. `nvme_core.default_ps_max_latency_us=0` — NVMe deep power states. Both drives report
   clean SMART, so low priority.

### Serial console — assessed 2026-08-18, deferred

The board **does** have a `COM` header (bottom edge, between `SPDIF_O` and `D_LED1`), and
the kernel already detects `ttyS0 at 0x03f8 ... 16550A`. Wiring it to pve would need three
cheap parts: a 10-pin-header-to-DB9-male slot bracket, a **null-modem** DB9 female-female
cable (crossover is mandatory — both ends are DTE), and an FTDI USB-RS232 adapter. Unraid
side is `console=tty0 console=ttyS0,115200n8` plus optional
`earlycon=uart8250,io,0x3f8,115200n8`; pve side is socat piped through `awk ... fflush()`
into a timestamped log.

**Why it is attractive:** serial `printk` is synchronous — the character is on the wire
before the CPU advances — so it is the only path with no ring buffer, no filesystem, no
network stack. It would catch a panic/oops trace, an MCE (currently invisible, since
`/var/log/mcelog` is RAM-backed), a fatal AER, or a GPU error in the final microseconds.

**Why it was deferred:** it cannot catch a pure hardware reset — triple fault, chipset
RESET#, VRM fault — because the CPU stops executing and nothing is printed. That is
precisely what the empty `efi_pstore` points at. Expected outcome is an ordinary message,
a gap, then the next boot. Worth revisiting only if the streamed metrics leave a genuine
question that only kernel output could answer.

**If revisited**, also check AMI's **Serial Port Console Redirection** (Advanced) — that
would put POST and firmware output on the same line, covering the layer serial otherwise
misses.

**Do not** enable `pci=noaer` or `ghes.disable=1`. They look like stability fixes and would
blind the only error reporting this box has.

---

## Method notes and gotchas

Hard-won tonight; all of these cost real time.

**netdata's API returns newest-first.** `tail` gives you the *oldest* rows. Use `head`.

**dbengine loses unflushed pages on a hard crash, and different charts lose different
amounts** (1–15 min). A staggered per-chart stop time is a flush artifact, **not**
subsystems failing in sequence. Use **resume** times for intervals — data reappearing is a
hard fact. This is exactly what the parent now eliminates.

**Syslog silence proves nothing** on an idle box. Pin crash times from netdata.

**`pcie_aspm=off` is actively harmful on this board.** The FADT already declares ASPM
unsupported (`FADT indicates ASPM is unsupported, using BIOS configuration`), so the
parameter cannot disable anything — but it removes ASPM and ClockPM from the capability set
Linux advertises, which makes the kernel decline `_OSC` negotiation entirely and **takes AER
down with it**. Confirmed: `_OSC: not requesting OS control` and zero `AER: enabled` lines.
Backed out; AER restored.

**The Eaton's "system" log never records power events.** 1,068 lines, 850 of them NTP
syncs; the only battery hits are `RTC battery cell low`, which is the *network card's* coin
cell. Its silence is meaningless. **The Alarms log** (bell icon, not Settings → System logs)
is the one that records transfers, utility loss, and outlet-group operations.

**br0 containers are unreachable from the Unraid host shell.** `curl http://192.168.1.2:8080`
returns empty from Unraid and works fine from anywhere else on the LAN. Do not read that as
a broken service.

**JetKVM cannot see POST unless it is independently powered *and* on the A380.** Initial
Display Output is `PCIe 1 Slot`, so firmware renders to the discrete card; and the KVM
power-cycles with the host if it draws power from it. Both conditions must hold at once —
several attempts failed because only one did.

**Fast Boot blocked `Del`.** Firmware skips USB HID init during the POST keypress window;
GRUB has its own USB stack, which is why the bootloader accepted keys and the BIOS did not.
Now disabled.

**`group=max` on aggregated tiers surfaces single-sample sensor glitches as if they were
events.** On 2026-08-20 a coarse max-grouped query reported the A380 die at **147 °C** —
against a 55–59 °C average and a ~100 °C junction limit. At 1-second resolution the same
window peaked at **56.0 °C** across 420 samples, the fan never rose above 466 RPM, and the
power alarm stayed clear. It was one bad hwmon read. **Always re-check a peak at native
resolution before believing it**, and confirm the fan and alarm charts corroborate.

**There is a 7-hour hole in the remote syslog on 2026-08-17 (01:01:50 → 08:04:48) that
is NOT an Unraid event.** pve's Intel I219 NIC threw `e1000e ... Detected Hardware Unit
Hang` at ~01:08 and stopped transmitting for six hours; pve stayed fully alive but the
collector was unreachable. Unraid ran continuously throughout — confirmed by its own
netdata, unbroken from 00:30 to 03:00, and an uptime that traces back to the 23:11 reboot
the night before. Cause was a `post-up /sbin/ethtool -K nic0 tso on gso on gro on` line in
pve's `/etc/network/interfaces` **enabling** the offloads implicated in I219 TX hangs;
flipped to `off` plus EEE off, with `|| true` so a failing `post-up` cannot strand the
host. Both syslog and netdata streaming reconnected by themselves once pve returned.

**Unraid 7.3 boots via GRUB**, not syslinux — `/boot/grub/grub.cfg`, kernel path
`/boot@/bzimage`. `/boot/syslinux.cfg-` is a stale leftover. The boot-parameters GUI once
proposed dropping the `/boot@/` prefix while leaving `initrd /boot@/bzroot` intact; **always
verify `grep -nE "^\s*(linux|initrd)" /boot/grub/grub.cfg` before rebooting.**

---

## Query cookbook for the next event

Pin the exact second, against the **parent**:

```bash
A=$(date -d '2026-08-23 00:00' +%s); B=$(date -d '2026-08-23 06:00' +%s)
wget -qO- "http://192.168.1.195:19999/host/unraid/api/v1/data?chart=system.cpu&after=$A&before=$B&points=21600&format=csv" \
  | awk -F, 'NR>1{s=($2=="null")?"GAP":"DATA"; if(s!=p){print $1"  "s; p=s}}'
```

Then the final two minutes across everything, substituting the stop time:

```bash
T="2026-08-23 01:53:00"; A=$(( $(date -d "$T" +%s) - 120 )); B=$(( $(date -d "$T" +%s) + 30 ))
for c in system.cpu "sensors.temperature_i915-pci-0300_temp1_input" \
         "sensors.power_i915-pci-0300_power1_alarm" cpu.powercap_intel_rapl_zone_package-0 \
         "sensors.temperature_coretemp-isa-0000_temp1_Package_id_0_input" \
         "apcupsd_local_3551.ups_load" cgroup_llama-server.cpu; do
  echo "=== $c"
  wget -qO- "http://192.168.1.195:19999/host/unraid/api/v1/data?chart=$c&after=$A&before=$B&points=150&format=csv"
done
```

And the corroborating witnesses:

```bash
# did anything reach the collector before it died?
# NOTE: weekly logrotate is due 2026-08-23 and may fire either side of 01:53 --
# grep BOTH files, the crash lines can land in either.
pct enter 110   # then: grep -iE "aer|i915|fence|drm|Hardware Error" /var/log/remote/192.168.1.198.log{,.1}

# abrupt termination, independent of netdata (baselines: 57 / 67)
for d in /dev/nvme0n1 /dev/nvme1n1; do smartctl -a "$d" | grep -i "Unsafe Shutdowns"; done

# and pull the Eaton's Alarms log from its web UI for the same window
```
