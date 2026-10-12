#!/usr/bin/env python3
"""
[GAP-REPS] Small cold-start vs warm-start comparison for REPS.

Stages (run all by default, or pick with --stage):
  equiv   : run the original and the instrumented binary on the same seed and check
            that every flow finishes at exactly the same time (instrumentation is
            observational only).
  run     : 2x2 grid  {freezing (REPS), oblivious} x {connections_mapping off, on}
            for each seed, writing one REPS stats CSV + stdout log per run.
  analyze : per-flow metrics, warm/cold labelling, summary table and plots.

Cold vs warm:
  mapping off -> every flow starts with an empty REPS buffer (cold).
  mapping on  -> a flow whose src/dst pair already finished a flow inherits that
                 flow's REPS buffer and cwnd (warm). oblivious keeps no EV state, so
                 its off/on difference isolates the cwnd carry-over effect.

Run from anywhere, e.g.:
  python3 gap_cold_warm_small.py                  # everything with CONFIG below
  python3 gap_cold_warm_small.py --stage run --seeds 1 2 3 --jobs 8
  python3 gap_cold_warm_small.py --stage analyze
  python3 gap_cold_warm_small.py --dry-run        # only print the commands
"""

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DC = REPO / "htsim" / "sim" / "datacenter"

# ----------------------------------------------------------------------------------------
# Parameters you are expected to edit.
# ----------------------------------------------------------------------------------------
CONFIG = {
    # Instrumented simulator and a copy of the pre-instrumentation binary (for 'equiv').
    "binary": DC / "htsim_uec",
    "orig_binary": Path.home() / "reps-baseline-bin" / "htsim_uec_orig",

    # Workload and topology (node counts must match: 32-node matrix <-> 32-host fat tree).
    # allreduce = ring chains: the same src/dst pairs recur, each flow triggered by the
    # previous one finishing, so connections_mapping can hand buffers over.
    # allreduce_n32.cm is the 32-node allreduce.cm from the original artifact commit, kept
    # as its own file because the working-tree allreduce.cm is a 128-node version.
    "tm": DC / "connection_matrices" / "allreduce_n32.cm",
    "topo": DC / "topologies" / "reps" / "fat_tree_32_1os_2t_400g.topo",

    # Simulator arguments shared by every run (same style as the artifact figures).
    "end_us": 90000,
    "common_args": [
        "-sack_threshold", "4000",
        "-paths", "65535",
        "-sender_cc_only", "-sender_cc_algo", "mprdma",
        "-linkspeed", "400000",
        "-ecn", "25", "76",
        "-q", "100",
        "-cwnd", "151",
    ],

    # Grid.
    "algos": ["freezing", "oblivious"],
    "mapping": [False, True],
    "seeds": [1],

    # Execution.
    "jobs": 4,              # parallel simulator processes
    "timeout_s": 1800,      # per run
    "out_dir": REPO / "results" / "instrumentation" / "cold_warm_small",

    # Equivalence check workload (fig_1 freezing command, 16 flows on 128 hosts).
    "equiv_args": [
        "-sack_threshold", "4000", "-end", "90000", "-seed", "5", "-paths", "65535",
        "-sender_cc_only", "-sender_cc_algo", "mprdma",
        "-topo", str(DC / "topologies" / "reps" / "fat_tree_128_1os_2t_400g.topo"),
        "-linkspeed", "400000", "-ecn", "20", "80", "-q", "100", "-cwnd", "151",
        "-load_balancing_algo", "freezing",
        "-tm", str(DC / "connection_matrices" / "test_symm16.cm"),
    ],
}
# ----------------------------------------------------------------------------------------


def run_cmd(cmd, log_path, timeout_s, dry_run):
    print("  $ " + " ".join(str(c) for c in cmd))
    if dry_run:
        return 0, 0.0
    t0 = time.time()
    with open(log_path, "w") as log:
        try:
            rc = subprocess.run([str(c) for c in cmd], cwd=DC, stdout=log,
                                stderr=subprocess.STDOUT, timeout=timeout_s).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    return rc, time.time() - t0


# ---------------------------------- equiv -----------------------------------------------

def stage_equiv(cfg, dry_run):
    print("[equiv] original vs instrumented binary, same seed")
    out = cfg["out_dir"] / "equiv"
    out.mkdir(parents=True, exist_ok=True)
    if not Path(cfg["orig_binary"]).exists():
        print(f"  original binary not found at {cfg['orig_binary']}; skipping")
        return True
    runs = {
        "orig": [cfg["orig_binary"]] + cfg["equiv_args"],
        "new": [cfg["binary"]] + cfg["equiv_args"],
        "new_csv": [cfg["binary"]] + cfg["equiv_args"]
                   + ["-reps_stats_csv", out / "equiv_stats.csv"],
    }
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {k: ex.submit(run_cmd, c, out / f"{k}.log", cfg["timeout_s"], dry_run)
                for k, c in runs.items()}
        results = {k: f.result() for k, f in futs.items()}
    if dry_run:
        return True
    for k, (rc, dt) in results.items():
        print(f"  {k:8s} rc={rc} {dt:.1f}s")

    def finish_lines(name):
        lines = (out / f"{name}.log").read_text().splitlines()
        return sorted(l for l in lines if "finished at" in l)

    ref = finish_lines("orig")
    ok = bool(ref)
    for k in ("new", "new_csv"):
        same = finish_lines(k) == ref
        ok &= same
        print(f"  {k:8s} finish lines identical to orig: {same} ({len(ref)} flows)")
    print("[equiv] PASS" if ok else "[equiv] FAIL - instrumentation changed behaviour?")
    return ok


# ----------------------------------- run ------------------------------------------------

def run_name(algo, mapping, seed):
    return f"{algo}_map{'on' if mapping else 'off'}_s{seed}"


def stage_run(cfg, dry_run):
    out = cfg["out_dir"] / "runs"
    out.mkdir(parents=True, exist_ok=True)
    tm = Path(cfg["tm"]).resolve()
    for label, p in (("traffic matrix", tm), ("topology", Path(cfg["topo"]))):
        if not p.exists():
            sys.exit(f"{label} not found: {p}")
    print(f"[run] tm={tm}\n      topo={cfg['topo']}")

    jobs = []
    for seed in cfg["seeds"]:
        for algo in cfg["algos"]:
            for mapping in cfg["mapping"]:
                name = run_name(algo, mapping, seed)
                cmd = ([cfg["binary"], "-topo", cfg["topo"], "-tm", tm,
                        "-end", str(cfg["end_us"]), "-seed", str(seed),
                        "-load_balancing_algo", algo]
                       + cfg["common_args"]
                       + (["-connections_mapping"] if mapping else [])
                       + ["-reps_stats_csv", out / f"{name}.csv"])
                jobs.append((name, cmd))

    with ThreadPoolExecutor(max_workers=cfg["jobs"]) as ex:
        futs = {name: ex.submit(run_cmd, cmd, out / f"{name}.log", cfg["timeout_s"], dry_run)
                for name, cmd in jobs}
        for name, f in futs.items():
            rc, dt = f.result()
            print(f"  {name:28s} rc={rc} {dt:.1f}s")


# --------------------------------- analyze ----------------------------------------------

def label_flows(df, mapping_on):
    """Add occurrence index per src/dst pair, warm flag, gap and buffer-sharing flag.

    Mirrors connections_mapping: at start, a flow inherits the buffer of the same-pair
    flow that finished most recently (any earlier one, not just the immediately previous).
    If the immediately previous same-pair flow is still running at that moment, the
    inherited buffer object may also be in use by another running flow (shared_buffer).
    """
    import bisect
    import pandas as pd

    df = df.sort_values("start_time_us").copy()
    df["occurrence"] = df.groupby(["src", "dst"]).cumcount()
    last_fin = pd.Series(float("nan"), index=df.index)
    for _, g in df.groupby(["src", "dst"]):
        fins = sorted(f for f in g["finish_time_us"] if f >= 0)
        for idx, start in zip(g.index, g["start_time_us"]):
            k = bisect.bisect_right(fins, start)
            if k:
                last_fin[idx] = fins[k - 1]
    prev_finish = df.groupby(["src", "dst"])["finish_time_us"].shift(1)
    df["warm"] = bool(mapping_on) & last_fin.notna()
    df["gap_us"] = (df["start_time_us"] - last_fin).where(last_fin.notna())
    df["shared_buffer"] = df["warm"] & (prev_finish > df["start_time_us"])
    return df


def stage_analyze(cfg):
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    runs_dir = cfg["out_dir"] / "runs"
    frames = []
    for csv in sorted(runs_dir.glob("*.csv")):
        algo, map_tag, seed_tag = csv.stem.rsplit("_", 2)
        df = pd.read_csv(csv)
        if df.empty:
            continue
        mapping_on = map_tag == "mapon"
        df = label_flows(df, mapping_on)
        df["algo"], df["mapping"], df["seed"] = algo, ("on" if mapping_on else "off"), int(seed_tag[1:])
        frames.append(df)
    if not frames:
        print("[analyze] no CSVs found in", runs_dir)
        return
    df = pd.concat(frames, ignore_index=True)

    unfinished = (df["finish_time_us"] < 0).sum()
    if unfinished:
        print(f"[analyze] WARNING: {unfinished} flows did not finish before -end; excluded from FCT")
    bad = df[df["random_ev_packets"] + df["cached_ev_packets"] != df["packets_sent"]]
    bad = bad[bad["algo"] == "freezing"]
    print(f"[analyze] consistency random+cached==packets_sent: "
          f"{'OK' if bad.empty else f'{len(bad)} rows FAIL'}")

    df["fct_us"] = (df["finish_time_us"] - df["start_time_us"]).where(df["finish_time_us"] >= 0)
    df["cold_frac"] = df["cache_empty_sends"] / df["packets_sent"]
    df["cached_frac"] = df["cached_ev_packets"] / df["packets_sent"]
    acks = df["ack_ecn"] + df["ack_no_ecn"]
    df["ecn_rate"] = (df["ack_ecn"] / acks).where(acks > 0)   # only counted for freezing

    out = cfg["out_dir"] / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "flows_all.csv", index=False)

    # Exclude each pair's first flow: it is cold in every condition and starts in an
    # empty network, so it would blur the off/on comparison.
    later = df[df["occurrence"] > 0]
    grp = later.groupby(["algo", "mapping"])
    summary = grp.agg(
        flows=("fct_us", "size"),
        warm_flows=("warm", "sum"),
        shared_buffer_flows=("shared_buffer", "sum"),
        fct_med_us=("fct_us", "median"),
        fct_p99_us=("fct_us", lambda s: s.quantile(0.99)),
        fct_mean_us=("fct_us", "mean"),
        pkts_sent=("packets_sent", "mean"),
        cache_empty_sends=("cache_empty_sends", "mean"),
        cold_frac=("cold_frac", "mean"),
        cached_frac=("cached_frac", "mean"),
        ecn_rate=("ecn_rate", "mean"),
        gap_med_us=("gap_us", "median"),
    ).round(4)
    summary.to_csv(out / "summary.csv")
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print("\n[analyze] per condition, excluding first flow of each pair:\n")
        print(summary)

    def med(algo, mapping):
        s = later[(later.algo == algo) & (later.mapping == mapping)]["fct_us"]
        return s.median() if len(s) else float("nan")

    s_reps = med("freezing", "off") / med("freezing", "on")
    s_cwnd = med("oblivious", "off") / med("oblivious", "on")
    print(f"\n  median-FCT speedup from mapping, freezing  (REPS state + cwnd): {s_reps:.3f}")
    print(f"  median-FCT speedup from mapping, oblivious (cwnd only)       : {s_cwnd:.3f}")
    print(f"  ratio (approx. contribution of reused EVs)                    : {s_reps / s_cwnd:.3f}")

    f = later[later.algo == "freezing"]
    d_cold = (f[f.mapping == "off"]["cache_empty_sends"].mean()
              - f[f.mapping == "on"]["cache_empty_sends"].mean())
    print(f"  cache_empty_sends saved per flow by warm start (freezing)     : {d_cold:.1f}")

    # Plots.
    fig, ax = plt.subplots(figsize=(6, 4))
    for (algo, mapping), g in later.groupby(["algo", "mapping"]):
        s = g["fct_us"].dropna().sort_values()
        if len(s):
            ax.plot(s.values, [i / len(s) for i in range(1, len(s) + 1)],
                    label=f"{algo}, mapping {mapping}")
    ax.set_xlabel("FCT (us)")
    ax.set_ylabel("CDF")
    ax.set_title("FCT, excluding first flow per pair")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "fct_cdf.png", dpi=150)

    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    for ax, col, title in zip(axes, ["cache_empty_sends", "cold_frac", "ecn_rate"],
                              ["random sends (cache empty)", "cold fraction", "ECN rate"]):
        data = [f[f.mapping == m][col].dropna().values for m in ("off", "on")]
        ax.boxplot(data, labels=["cold (map off)", "warm-capable (map on)"])
        ax.set_title(f"freezing: {title}")
    fig.tight_layout()
    fig.savefig(out / "freezing_cold_vs_warm.png", dpi=150)
    print(f"\n[analyze] wrote {out}/summary.csv, flows_all.csv, fct_cdf.png, freezing_cold_vs_warm.png")


# ----------------------------------- main -----------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=["all", "equiv", "run", "analyze"], default="all")
    ap.add_argument("--seeds", type=int, nargs="+", help="override CONFIG seeds")
    ap.add_argument("--jobs", type=int, help="override CONFIG jobs")
    ap.add_argument("--end", type=int, help="override CONFIG end_us")
    ap.add_argument("--tm", help="override CONFIG tm (path to a .cm file)")
    ap.add_argument("--topo", help="override CONFIG topo")
    ap.add_argument("--out", help="override CONFIG out_dir")
    ap.add_argument("--dry-run", action="store_true", help="print commands without running")
    args = ap.parse_args()

    cfg = dict(CONFIG)
    if args.seeds: cfg["seeds"] = args.seeds
    if args.jobs: cfg["jobs"] = args.jobs
    if args.end: cfg["end_us"] = args.end
    if args.tm: cfg["tm"] = args.tm
    if args.topo: cfg["topo"] = Path(args.topo).resolve()
    if args.out: cfg["out_dir"] = Path(args.out).resolve()
    cfg["out_dir"] = Path(cfg["out_dir"])
    cfg["out_dir"].mkdir(parents=True, exist_ok=True)

    if not Path(cfg["binary"]).exists():
        sys.exit(f"simulator not found: {cfg['binary']} (build htsim/sim then htsim/sim/datacenter)")

    if args.stage in ("all", "equiv"):
        if not stage_equiv(cfg, args.dry_run) and args.stage == "all":
            sys.exit("equivalence check failed; not running the grid")
    if args.stage in ("all", "run"):
        stage_run(cfg, args.dry_run)
    if args.stage in ("all", "analyze") and not args.dry_run:
        stage_analyze(cfg)


if __name__ == "__main__":
    main()
