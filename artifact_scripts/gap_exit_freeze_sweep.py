#!/usr/bin/env python3
"""
[GAP-REPS] Cold vs warm start under failures, sweeping how long REPS stays frozen.

Question: in cold_warm_asym, warm start (-connections_mapping) made REPS slower under
failures. Hypothesis: a frozen REPS buffer is handed to the next same-pair flow and never
unfreezes, because exit_freeze_after (default 1e10 ps = 10 ms) is longer than the job.
If so, warm start should recover as -exit_freeze shrinks, while cold barely changes.

Grid:
  freezing  x {mapping off, on} x exit_freeze values x seeds x scenarios
  oblivious x {mapping off, on} x seeds x scenarios       (exit_freeze has no effect)

Scenarios, simulator args and helpers come from gap_cold_warm_asym.py (unchanged).
Failure placements are copied from that run's private cache when present, so every run
here sees the same failed components as the previous experiment.

Longer flows (--flow-size): the ring's traffic matrix is copied with every flow resized,
written to <out_dir>/tm/, so a single flow can outlast exit_freeze and enter/exit freezing
mode several times. Default out_dir becomes exit_freeze_sweep_<size>MB.

Stages: run | analyze (default: both). Examples:
  python3 gap_exit_freeze_sweep.py --dry-run
  python3 gap_exit_freeze_sweep.py --stage analyze
  python3 gap_exit_freeze_sweep.py --flow-size 32000000 --algos freezing
"""

import argparse
import json
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gap_cold_warm_asym as base  # noqa: E402

# ----------------------------------------------------------------------------------------
# Parameters you are expected to edit.
# ----------------------------------------------------------------------------------------
SWEEP = {
    "scenarios": ["ar32_sym", "ar32_fail_one_cable", "ar32_fail_one_switch", "ar32_5pct_cables"],
    # -exit_freeze is in picoseconds. Default in the simulator is 1e10 (10 ms).
    #   1e8 = 100 us (about one 4 MB flow), 1e9 = 1 ms, 1e10 = default.
    "exit_freeze_ps": [100_000_000, 1_000_000_000, 10_000_000_000],
    "default_exit_freeze_ps": 10_000_000_000,
    "seeds": [42, 43, 44],
    "algos": ["freezing", "oblivious"],
    "mapping": [False, True],
    "jobs": 6,
    "timeout_s": 1800,
    "out_dir": base.REPO / "results" / "instrumentation" / "exit_freeze_sweep",
    # Reuse failure placements from this earlier run (same failed components).
    "placement_src": base.REPO / "results" / "instrumentation" / "cold_warm_asym" / "sim",
}
# ----------------------------------------------------------------------------------------


def resized_tm(src, dst, size_bytes):
    """Copy a connection matrix, replacing every flow's 'size <bytes>' field."""
    text = Path(src).read_text()
    out, n = re.subn(r"\bsize \d+", f"size {size_bytes}", text)
    if not n:
        sys.exit(f"no 'size' fields found in {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(out)
    print(f"[run] traffic matrix {Path(src).name} -> {dst} ({n} flows at {size_bytes} B)")
    return dst


def ef_label(ps):
    return f"{ps / 1e6:g}us"


def run_name(scen, algo, mapping, ef, seed):
    return f"{scen}__{algo}_map{'on' if mapping else 'off'}_ef{ef_label(ef)}_s{seed}"


def build_jobs(cfg, sweep, out):
    jobs = []
    for scen_name in sweep["scenarios"]:
        scen = cfg["scenarios"][scen_name]
        wl = cfg["workloads"][scen["workload"]]
        extra = list(scen.get("args", []))
        if scen.get("failures_input"):
            extra += ["-failures_input", base.FAILS / scen["failures_input"], "-other_location"]
        if cfg["disable_trim"]:
            extra += ["-disable_trim"]
        scen_dir = sweep["out_dir"] / "sim" / scen_name
        for seed in sweep["seeds"]:
            for algo in sweep["algos"]:
                efs = sweep["exit_freeze_ps"] if algo == "freezing" else [sweep["default_exit_freeze_ps"]]
                for ef in efs:
                    for mapping in sweep["mapping"]:
                        name = run_name(scen_name, algo, mapping, ef, seed)
                        cmd = ([cfg["binary"], "-topo", wl["topo"], "-tm", wl["tm"],
                                "-end", str(cfg["end_us"]), "-seed", str(seed),
                                "-load_balancing_algo", algo]
                               + cfg["common_args"] + extra
                               + ["-exit_freeze", str(ef)]
                               + (["-connections_mapping"] if mapping else [])
                               + ["-reps_stats_csv", out / f"{name}.csv"])
                        meta = {"scenario": scen_name, "algo": algo,
                                "mapping": "on" if mapping else "off", "seed": seed,
                                "exit_freeze_ps": ef, "cmd": [str(c) for c in cmd]}
                        jobs.append({"name": name, "cmd": cmd, "meta": meta,
                                     "scen_dir": scen_dir, "cwd": scen_dir / name})
    return jobs


def prepare_placements(sweep, dry_run):
    """Copy cached failure placements from the earlier experiment, scenario by scenario."""
    for scen_name in sweep["scenarios"]:
        if not base.CONFIG["scenarios"][scen_name].get("failures_input"):
            continue
        src = sweep["placement_src"] / scen_name / "failures_input" / "saved"
        dst = sweep["out_dir"] / "sim" / scen_name / "failures_input" / "saved"
        files = sorted(src.glob("saved_*")) if src.exists() else []
        print(f"[run] {scen_name}: placement "
              f"{'copied from ' + str(src) if files else 'NOT FOUND, will be generated'}")
        if dry_run:
            continue
        dst.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(f, dst / f.name)


def completed(out, name):
    meta = out / f"{name}.json"
    return meta.exists() and json.loads(meta.read_text()).get("rc") == 0


def stage_run(cfg, sweep, dry_run, overwrite):
    out = sweep["out_dir"] / "runs"
    out.mkdir(parents=True, exist_ok=True)
    prepare_placements(sweep, dry_run)
    jobs = build_jobs(cfg, sweep, out)
    done = [j for j in jobs if completed(out, j["name"])]
    if done and not overwrite:
        jobs = [j for j in jobs if j not in done]
        print(f"[run] skipping {len(done)} runs already completed in {out} (use --overwrite to redo)")
    print(f"[run] output: {sweep['out_dir']}")
    print(f"[run] {len(jobs)} runs, {sweep['jobs']} in parallel")

    def one(j):
        if not dry_run:
            j["cwd"].mkdir(parents=True, exist_ok=True)
        rc, dt = base.run_cmd(j["cmd"], out / f"{j['name']}.log", sweep["timeout_s"], dry_run, cwd=j["cwd"])
        if not dry_run:
            (out / f"{j['name']}.json").write_text(json.dumps(dict(j["meta"], rc=rc, wall_s=round(dt, 1)), indent=1))
        return rc, dt

    # A scenario without a cached placement: run one job alone first so it generates it.
    first, seen = [], set()
    for j in jobs:
        cache = j["scen_dir"] / "failures_input" / "saved"
        scen = j["meta"]["scenario"]
        if base.CONFIG["scenarios"][scen].get("failures_input") and scen not in seen:
            seen.add(scen)
            if not dry_run and not any(cache.glob("saved_*")):
                first.append(j)
    rest = [j for j in jobs if j not in first]
    with ThreadPoolExecutor(max_workers=sweep["jobs"]) as ex:
        for j, f in [(j, ex.submit(one, j)) for j in first]:
            rc, dt = f.result()
            print(f"  [placement] {j['name']:58s} rc={rc} {dt:.1f}s")
        for j, f in [(j, ex.submit(one, j)) for j in rest]:
            rc, dt = f.result()
            print(f"  {j['name']:70s} rc={rc} {dt:.1f}s")


def parse_log(path):
    text = path.read_text(errors="replace") if path.exists() else ""
    d = base.parse_log(path)
    d["freeze_exit_msgs"] = len(re.findall(r"exited freezing mode", text))
    return d


def stage_analyze(sweep):
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    runs_dir = sweep["out_dir"] / "runs"
    frames, runs = [], []
    for mp in sorted(runs_dir.glob("*.json")):
        meta = json.loads(mp.read_text())
        if meta["scenario"] not in sweep["scenarios"]:
            continue
        if meta.get("rc", 0) != 0:
            print(f"[analyze] skipping {mp.stem}: rc={meta.get('rc')}")
            continue
        csv = mp.with_suffix(".csv")
        if not csv.exists():
            print(f"[analyze] missing CSV for {mp.stem}")
            continue
        df = base.label_flows(pd.read_csv(csv), meta["mapping"] == "on")
        for k in ("scenario", "algo", "mapping", "seed", "exit_freeze_ps"):
            df[k] = meta[k]
        frames.append(df)
        runs.append(dict({k: meta[k] for k in ("scenario", "algo", "mapping", "seed", "exit_freeze_ps")},
                         unfinished=int((df["finish_time_us"] < 0).sum()),
                         jct_us=(df["finish_time_us"].max() - df["start_time_us"].min())
                         if (df["finish_time_us"] >= 0).all() else float("nan"),
                         **parse_log(mp.with_suffix(".log"))))
    if not frames:
        print("[analyze] no runs found in", runs_dir)
        return
    df = pd.concat(frames, ignore_index=True)
    runs = pd.DataFrame(runs)
    df["fct_us"] = (df["finish_time_us"] - df["start_time_us"]).where(df["finish_time_us"] >= 0)
    acks = df["ack_ecn"] + df["ack_no_ecn"]
    df["ecn_rate"] = (df["ack_ecn"] / acks).where(acks > 0)
    df["ef"] = df["exit_freeze_ps"].map(ef_label)
    runs["ef"] = runs["exit_freeze_ps"].map(ef_label)

    out = sweep["out_dir"] / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "flows_all.csv", index=False)
    runs.to_csv(out / "runs.csv", index=False)
    if runs["unfinished"].sum():
        print(f"[analyze] WARNING: {runs['unfinished'].sum()} unfinished flows; those runs have no JCT")

    keys = ["scenario", "algo", "exit_freeze_ps", "ef", "mapping"]
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.max_rows", 200)

    # Run level, over seeds.
    rl = runs.groupby(keys).agg(seeds=("seed", "nunique"),
                                jct_mean=("jct_us", "mean"), jct_min=("jct_us", "min"),
                                jct_max=("jct_us", "max"), drops=("dropped_pkts", "mean"),
                                freeze_in=("freeze_msgs", "mean"), freeze_out=("freeze_exit_msgs", "mean"))
    # Flow level, excluding each pair's first flow (cold in every condition).
    later = df[df["occurrence"] > 0]
    fl = later.groupby(keys).agg(fct_med=("fct_us", "median"),
                                 fct_p99=("fct_us", lambda s: s.quantile(0.99)),
                                 ecn=("ecn_rate", "mean"), empty=("cache_empty_sends", "mean"),
                                 explore=("explore_sends", "mean"), stale=("frozen_stale_sends", "mean"))
    summary = rl.join(fl).reset_index()
    summary["scenario"] = pd.Categorical(summary["scenario"], sweep["scenarios"], ordered=True)
    summary = summary.sort_values(["scenario", "algo", "exit_freeze_ps", "mapping"]).drop(columns="exit_freeze_ps")
    summary.round(4).to_csv(out / "summary.csv", index=False)
    print("\n[analyze] per condition (JCT over seeds; flow stats exclude each pair's first flow):\n")
    print(summary.round(3).to_string(index=False))

    # Warm speedup per seed (paired: same seed, same placement), then summarised.
    piv = runs.pivot_table(index=["scenario", "algo", "exit_freeze_ps", "ef", "seed"],
                           columns="mapping", values="jct_us").dropna()
    piv["warm_speedup"] = piv["off"] / piv["on"]
    ws = piv.groupby(level=["scenario", "algo", "exit_freeze_ps", "ef"])["warm_speedup"].agg(
        ["mean", "min", "max", "count"]).reset_index()
    ws["scenario"] = pd.Categorical(ws["scenario"], sweep["scenarios"], ordered=True)
    ws = ws.sort_values(["scenario", "algo", "exit_freeze_ps"]).drop(columns="exit_freeze_ps")
    ws.round(4).to_csv(out / "warm_speedup.csv", index=False)
    print("\n[analyze] warm speedup = JCT(cold) / JCT(warm), paired per seed (>1 means warm is faster):\n")
    print(ws.round(3).to_string(index=False))

    # Plot: JCT vs exit_freeze, cold vs warm, per scenario; oblivious as horizontal lines.
    scen = [s for s in sweep["scenarios"] if s in set(runs["scenario"])]
    fig, axes = plt.subplots(1, len(scen), figsize=(4.5 * len(scen), 3.6), squeeze=False)
    for ax, s in zip(axes[0], scen):
        r = runs[runs["scenario"] == s]
        for m, style in (("off", "o-"), ("on", "s--")):
            g = r[(r["algo"] == "freezing") & (r["mapping"] == m)].groupby("exit_freeze_ps")["jct_us"]
            mean, lo, hi = g.mean(), g.min(), g.max()
            ax.errorbar(mean.index / 1e6, mean.values, yerr=[mean - lo, hi - mean], fmt=style,
                        capsize=3, label=f"REPS {'cold' if m == 'off' else 'warm'}")
            o = r[(r["algo"] == "oblivious") & (r["mapping"] == m)]["jct_us"].mean()
            if o == o:
                ax.axhline(o, ls=":", lw=1, color="gray" if m == "off" else "black",
                           label=f"oblivious {'cold' if m == 'off' else 'warm'}")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("exit_freeze (us)")
        ax.set_ylabel("allreduce JCT (us)")
        ax.set_title(s, fontsize=10)
        ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out / "jct_vs_exit_freeze.png", dpi=150)
    print(f"\n[analyze] wrote {out}/summary.csv, warm_speedup.csv, runs.csv, flows_all.csv, "
          f"jct_vs_exit_freeze.png")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=["all", "run", "analyze"], default="all")
    ap.add_argument("--scenarios", nargs="+", help="override SWEEP scenarios")
    ap.add_argument("--seeds", type=int, nargs="+", help="override SWEEP seeds")
    ap.add_argument("--jobs", type=int, help="override SWEEP jobs")
    ap.add_argument("--algos", nargs="+", help="override SWEEP algos (e.g. freezing)")
    ap.add_argument("--flow-size", type=int, help="resize every flow of the ring to this many bytes")
    ap.add_argument("--end", type=int, help="override simulation end (us)")
    ap.add_argument("--out", help="override output directory")
    ap.add_argument("--overwrite", action="store_true",
                    help="re-run runs that already completed (default: skip them)")
    ap.add_argument("--dry-run", action="store_true", help="print commands without running")
    args = ap.parse_args()

    cfg = dict(base.CONFIG)
    cfg["workloads"] = {k: dict(v) for k, v in base.CONFIG["workloads"].items()}
    sweep = dict(SWEEP)
    if args.scenarios: sweep["scenarios"] = args.scenarios
    if args.seeds: sweep["seeds"] = args.seeds
    if args.jobs: sweep["jobs"] = args.jobs
    if args.algos: sweep["algos"] = args.algos
    if args.end: cfg["end_us"] = args.end
    if args.flow_size:
        sweep["out_dir"] = sweep["out_dir"].with_name(f"exit_freeze_sweep_{args.flow_size / 1e6:g}MB")
    if args.out: sweep["out_dir"] = Path(args.out).resolve()
    if args.flow_size:
        for wl_name in {cfg["scenarios"][s]["workload"] for s in sweep["scenarios"]}:
            wl = cfg["workloads"][wl_name]
            wl["tm"] = resized_tm(wl["tm"], sweep["out_dir"] / "tm" /
                                  f"{Path(wl['tm']).stem}_s{args.flow_size}.cm", args.flow_size)
    unknown = set(sweep["scenarios"]) - set(cfg["scenarios"])
    if unknown:
        sys.exit(f"unknown scenarios {sorted(unknown)}; known: {list(cfg['scenarios'])}")
    if not Path(cfg["binary"]).exists():
        sys.exit(f"simulator not found: {cfg['binary']}")

    if args.stage in ("all", "run"):
        stage_run(cfg, sweep, args.dry_run, args.overwrite)
    if args.stage in ("all", "analyze") and not args.dry_run:
        stage_analyze(sweep)


if __name__ == "__main__":
    main()
