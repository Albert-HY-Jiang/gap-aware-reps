# Gap-Aware REPS: instrumentation and cold vs warm start

Observational study of REPS (`-load_balancing_algo freezing`) before any gap-aware
mechanism. REPS behaviour is unchanged: finish times are identical to the original
binary (`cold_warm_asym/equiv/`).

## Instrumentation (htsim)

All changes are marked `[GAP-REPS instr]` in `htsim/sim/uec.h`, `htsim/sim/uec.cpp`,
`htsim/sim/datacenter/main_uec.cpp`.

- `-reps_stats_csv <path>`: one CSV row per flow, written at flow finish (unfinished flows
  at simulation end with `finish_time_us = -1`). No per-packet I/O.
- REPS counters (freezing only): `packets_sent, random_ev_packets, cached_ev_packets,
  ack_ecn, ack_no_ecn, cache_inserts, cache_reuses, cache_empty_sends, explore_sends,
  frozen_stale_sends, freeze_entries, freeze_exits`.
- Inherited-state snapshot (all algorithms): `inherited, started_frozen, cwnd_start,
  cwnd_end, cwnd_min, maxwnd` (bytes).

Code map: send path `UecSrc::nextEntropy_freezing`, ACK path `UecSrc::processEv_freezing`,
buffer `CircularBufferREPS` (`buffer_reps.{h,cpp}`), freeze entry `UecSrc::rtxTimerExpired`.

## Key finding: `-connections_mapping` is a naive warm start

- The paper's fig_4 / fig_7 runners (`run_failures.py`, `run_collective.py`,
  `run_symmetric.py`, `run_dc.py`) pass `-connections_mapping`. It hands the next flow of the
  same src/dst pair the previous flow's REPS buffer object (pointer, incl. frozen flag) and
  its final `cwnd`, with no age check. Only workloads with recurring pairs (allreduce, DC
  traces) are affected.
- Upside is capped: the buffer holds 8 EVs, so warm start saves at most ~8 random sends per
  flow (107 -> 96 on 979-packet flows without failures).

## Results (32-host 2-tier fat tree, 16-host ring allreduce, trimming off)

Failures are static: the failed component goes down ~1-2 us into the run and stays down
(cables 100 s hard-coded, switch 0-360 s random). See `failuregenerator.cpp`.

1. No failures: cold and warm are identical (JCT 2821 us at 4 MB flows).
2. Under failures, 4 MB flows, 3 seeds: warm is slower at every `exit_freeze`
   (`exit_freeze_sweep_4mb/analysis/warm_speedup.csv`, JCT cold/warm):
   one cable 0.68, one switch 0.40, 5% cables 0.80 at the default 10 ms.
   Oblivious (inherits only `cwnd`) shows a similar 0.64-0.67 warm penalty.
3. Warm REPS drops 3-20x fewer packets than cold (avoids the failed paths) but has ~100x
   higher ECN (concentrates on few EVs); with MPRDMA, ECN cuts `cwnd`.
4. Freezing carry-over is not fixed by unfreezing sooner: `exit_freeze` 100 us makes warm
   worse (buffer wipe -> forced exploration -> drops -> refreeze). Cold flows (4 MB, ~91 us)
   never reach the freeze deadline, so cold is insensitive to `exit_freeze`.
5. The penalty is entirely in flows that inherit a predecessor's damage
   (`inspect_cwnd_effect.py`): warm flows starting at max `cwnd` and not frozen are as fast
   as cold (~91 us); median FCT rises to 140 / 203 / 329 us as `cwnd_start` falls to
   50-75 / 25-50 / <25 % of max. Low inherited `cwnd` never occurs without a frozen buffer,
   so their individual contributions need an ablation (buffer-only vs cwnd-only mapping).
6. 32 MB flows (~670 us, 1 seed, `exit_freeze_sweep_32MB/`): freezing now cycles inside a
   flow. `exit_freeze` 100 us is bad for cold and warm (JCT 2.5-4.6x worse than 1 ms).
   At 1 ms (~one flow length) warm roughly breaks even (0.97 / 1.07 / 0.90); at the
   default 10 ms the penalty returns (0.79 / 0.69 / 0.60). For long flows the frozen
   buffer, not the starting `cwnd`, dominates.

Takeaway for gap-aware design: reuse path knowledge, not the congestion window or freezing
state, and bound the lifetime of reused state (roughly a flow length here).

## Caveats

- 32 hosts only; one failure placement per scenario; 3 seeds (4 MB), 1 seed (32 MB).
- Gaps between same-pair flows are ~0 us (back-to-back ring), not real idle gaps.
- Failures are static, so inherited path knowledge never goes stale.
- Overlapping same-pair flows share one buffer object; ~26-33 % of warm flows inherit from
  a flow other than the immediately previous one.
- `cwnd` also drops without ECN under failures (cold flows end at 74 % of max with ~0 ECN);
  the mechanism (receiver window penalty or ECN-marked cumulative ACKs) is not identified.
- `CircularBufferREPS::numValid()` is not ring-aware; the counters do not use it.

## Next steps

- Ablation: mapping carries buffer only vs `cwnd` only (behaviour change).
- Dynamic failures: `Switch-Fail-Start-After` (failure appears mid-job) and
  `Stop-Failures-After` (failure recovers) so inherited state can become wrong.
- Controlled idle gaps between rounds (traffic matrix with explicit start times).
- Phase 4: per-EV age metadata to estimate rho(age); ECN split by EV source.
- 128-host fig_4 mirror (`-failed 4 -down_ratio 0.25`, `allreduce_n128.cm`).

## Layout and reproduction

| Directory | Produced by |
|---|---|
| `cold_warm_small_1/` | `artifact_scripts/gap_cold_warm_small_sym.py` (first symmetric run; writes `cold_warm_small/`, renamed) |
| `cold_warm_asym/` | `artifact_scripts/gap_cold_warm_asym.py` (ar32 scenarios, seed 42; `equiv/`) |
| `exit_freeze_sweep_4mb/` | `gap_exit_freeze_sweep.py` (default 4 MB; run before the rename to `_4mb`) |
| `exit_freeze_sweep_32MB/` | `gap_exit_freeze_sweep.py --flow-size 32000000 --algos freezing --end 300000 --seeds 42` |

Each run directory has `runs/` (simulator log, per-flow CSV, JSON metadata with the exact
command), `sim/` (per-run working dirs and cached failure placements) and `analysis/`.
Read-only breakdowns: `inspect_mapping_effect.py`, `inspect_cwnd_effect.py --csv <flows_all.csv>`.
Use system `python3` (pandas, matplotlib).

Build: `cd htsim/sim && make libhtsim.a && cd datacenter && make htsim_uec`. The Makefiles do
not track header dependencies; after changing `uec.h`, delete `*.o` in both directories first.
