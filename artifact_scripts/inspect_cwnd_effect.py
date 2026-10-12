#!/usr/bin/env python3
"""Read-only: does the inherited cwnd / frozen buffer explain the warm-start penalty?

Input: exit_freeze_sweep/analysis/flows_all.csv (needs the inherited, started_frozen,
cwnd_start, cwnd_end, cwnd_min, maxwnd columns). Output: tables on stdout only.
"""
import argparse
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(HERE, "..", "results", "instrumentation", "exit_freeze_sweep",
                           "analysis", "flows_all.csv")
DEFAULT_EF = 10_000_000_000

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 200)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--ef", type=int, default=DEFAULT_EF, help="exit_freeze (ps) to focus on")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    df = df[df["finish_time_us"] >= 0].copy()
    for c in ("cwnd_start", "cwnd_end", "cwnd_min"):
        df[c + "_frac"] = df[c] / df["maxwnd"]
    df = df[df["occurrence"] > 0]
    scen_order = ["ar32_sym", "ar32_fail_one_cable", "ar32_fail_one_switch", "ar32_5pct_cables"]

    d = df[df["exit_freeze_ps"] == args.ef]
    print(f"=== 1. Starting / ending / minimum cwnd as fraction of maxwnd (exit_freeze={args.ef/1e6:g}us) ===")
    t = d.groupby(["scenario", "algo", "mapping"]).agg(
        flows=("fct_us", "size"), inherited=("inherited", "mean"),
        start_mean=("cwnd_start_frac", "mean"), start_at_max=("cwnd_start_frac", lambda s: (s >= 0.999).mean()),
        start_p10=("cwnd_start_frac", lambda s: s.quantile(0.1)),
        end_mean=("cwnd_end_frac", "mean"), min_mean=("cwnd_min_frac", "mean"),
        started_frozen=("started_frozen", "mean"), fct_med=("fct_us", "median"))
    print(t.reindex(scen_order, level=0).round(3).to_string())

    print("\n=== 2. Hand-over check: warm cwnd_start == predecessor's cwnd_end? ===")
    w = df[(df["mapping"] == "on")].sort_values(["scenario", "algo", "exit_freeze_ps", "seed",
                                                 "src", "dst", "start_time_us"])
    w["prev_end"] = w.groupby(["scenario", "algo", "exit_freeze_ps", "seed", "src", "dst"])["cwnd_end"].shift(1)
    w2 = w.dropna(subset=["prev_end"])
    print("  match rate: %.3f  (mismatches come from overlapping flows: the later finisher overwrites)"
          % (w2["cwnd_start"] == w2["prev_end"]).mean())

    print("\n=== 3. FCT by starting cwnd (freezing + oblivious, failure scenarios, this exit_freeze) ===")
    f = d[d["scenario"] != "ar32_sym"].copy()
    f["start_bin"] = pd.cut(f["cwnd_start_frac"], [0, 0.25, 0.5, 0.75, 0.999, 1.01],
                            labels=["<25%", "25-50%", "50-75%", "75-99%", "max"])
    t = f.groupby(["algo", "mapping", "start_bin"]).agg(
        n=("fct_us", "size"), fct_med=("fct_us", "median"), fct_p95=("fct_us", lambda s: s.quantile(0.95)),
        ecn=("ecn_rate", "mean"), end_frac=("cwnd_end_frac", "mean"))
    print(t[t["n"] > 0].round(3).to_string())

    print("\n=== 4. Warm freezing flows: started_frozen x low start cwnd ===")
    wf = f[(f["algo"] == "freezing") & (f["mapping"] == "on")].copy()
    wf["low_cwnd"] = wf["cwnd_start_frac"] < 0.75
    t = wf.groupby(["scenario", "started_frozen", "low_cwnd"]).agg(
        n=("fct_us", "size"), fct_med=("fct_us", "median"), ecn=("ecn_rate", "mean"),
        start_frac=("cwnd_start_frac", "mean"), stale=("frozen_stale_sends", "mean"))
    print(t.round(3).to_string())
    print("\n  corr with FCT (warm freezing):  cwnd_start_frac %.3f  started_frozen %.3f  ecn %.3f"
          % (wf["fct_us"].corr(wf["cwnd_start_frac"]),
             wf["fct_us"].corr(wf["started_frozen"].astype(float)),
             wf["fct_us"].corr(wf["ecn_rate"])))
    print("  corr ecn vs started_frozen: %.3f" % wf["ecn_rate"].corr(wf["started_frozen"].astype(float)))

    print("\n=== 5. Ratchet: mean cwnd_start fraction by ring round (warm, this exit_freeze) ===")
    r = d[d["mapping"] == "on"].copy()
    r["round_bucket"] = pd.cut(r["occurrence"], [0, 4, 8, 12, 16, 20, 24, 28, 31], include_lowest=True)
    t = r.groupby(["scenario", "algo", "round_bucket"])["cwnd_start_frac"].mean().unstack("round_bucket")
    print(t.reindex(scen_order, level=0).round(3).to_string())

    print("\n=== 6. exit_freeze effect on warm freezing (all values) ===")
    a = df[(df["algo"] == "freezing") & (df["mapping"] == "on")]
    t = a.groupby(["scenario", "exit_freeze_ps"]).agg(
        start_mean=("cwnd_start_frac", "mean"), min_mean=("cwnd_min_frac", "mean"),
        started_frozen=("started_frozen", "mean"), ecn=("ecn_rate", "mean"), fct_med=("fct_us", "median"))
    print(t.reindex(scen_order, level=0).round(3).to_string())


if __name__ == "__main__":
    main()
