#!/usr/bin/env python3
"""Read-only breakdown of what -connections_mapping (warm start) changes per flow.

Input: <out_dir>/analysis/flows_all.csv written by gap_cold_warm_asym.py analyze.
Output: tables on stdout only.
"""
import argparse
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(HERE, "..", "results", "instrumentation", "cold_warm_asym",
                           "analysis", "flows_all.csv")

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 200)


def add_predecessor(df):
    """Attach stats of the previous flow of the same src/dst pair (the one handing over state)."""
    df = df.sort_values(["scenario", "algo", "mapping", "src", "dst", "start_time_us"]).copy()
    g = df.groupby(["scenario", "algo", "mapping", "src", "dst"])
    for col in ["fct_us", "ecn_rate", "freeze_entries", "freeze_exits", "finish_time_us"]:
        df["prev_" + col] = g[col].shift(1)
    df["prev_left_frozen"] = df["prev_freeze_entries"] > df["prev_freeze_exits"]
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--rounds", type=int, default=8, help="number of ring rounds to bucket into")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    df = df[df["finish_time_us"] >= 0]
    df = add_predecessor(df)
    df = df[df["occurrence"] > 0]  # first flow of a pair is cold in both conditions

    scen = [s for s in df["scenario"].unique() if s != "ar32_sym"] + ["ar32_sym"]

    print("\n=== 1. Per-round evolution (occurrence bucketed), freezing ===")
    rep = df[df["algo"] == "freezing"].copy()
    rep["round_bucket"] = pd.cut(rep["occurrence"], args.rounds, labels=False)
    t = rep.groupby(["scenario", "mapping", "round_bucket"]).agg(
        fct_med=("fct_us", "median"), fct_p95=("fct_us", lambda s: s.quantile(0.95)),
        ecn=("ecn_rate", "mean"), empty=("cache_empty_sends", "mean"),
        freeze=("freeze_entries", "mean"), stale=("frozen_stale_sends", "mean"))
    print(t.round(3).unstack("mapping").to_string())

    print("\n=== 2. Oblivious per-round (only cwnd is inherited here) ===")
    obl = df[df["algo"] == "oblivious"].copy()
    obl["round_bucket"] = pd.cut(obl["occurrence"], args.rounds, labels=False)
    t = obl.groupby(["scenario", "mapping", "round_bucket"]).agg(
        n=("fct_us", "size"), fct_med=("fct_us", "median"),
        fct_p95=("fct_us", lambda s: s.quantile(0.95)))
    print(t.round(1).unstack("mapping").to_string())

    warm = rep[(rep["mapping"] == "on")]
    print("\n=== 3. Warm freezing flows: split by buffer sharing and by inherited state ===")
    for s in scen:
        w = warm[warm["scenario"] == s]
        if w.empty:
            continue
        print(f"\n-- {s}  (warm flows: {len(w)})")
        for key in ["shared_buffer", "prev_left_frozen"]:
            t = w.groupby(key).agg(n=("fct_us", "size"), fct_med=("fct_us", "median"),
                                  fct_p95=("fct_us", lambda x: x.quantile(0.95)),
                                  ecn=("ecn_rate", "mean"), empty=("cache_empty_sends", "mean"),
                                  stale=("frozen_stale_sends", "mean"))
            print(t.round(3).to_string())
        hi = w["prev_ecn_rate"] > w["prev_ecn_rate"].median()
        print("  predecessor ECN above median -> fct_med %.1f, ecn %.4f | below -> fct_med %.1f, ecn %.4f"
              % (w[hi]["fct_us"].median(), w[hi]["ecn_rate"].mean(),
                 w[~hi]["fct_us"].median(), w[~hi]["ecn_rate"].mean()))
        print("  corr(fct, prev_fct) = %.3f   corr(ecn, prev_ecn) = %.3f"
              % (w["fct_us"].corr(w["prev_fct_us"]), w["ecn_rate"].corr(w["prev_ecn_rate"])))

    print("\n=== 4. Slowest 10 warm freezing flows per failure scenario ===")
    cols = ["src", "dst", "occurrence", "start_time_us", "fct_us", "ecn_rate", "cache_empty_sends",
            "frozen_stale_sends", "freeze_entries", "shared_buffer", "prev_fct_us", "prev_left_frozen"]
    for s in scen:
        if s == "ar32_sym":
            continue
        w = warm[warm["scenario"] == s].nlargest(10, "fct_us")
        print(f"\n-- {s}")
        print(w[cols].round(3).to_string(index=False))

    print("\n=== 5. Concentration: share of total freezing flow-time in the slowest 10% flows ===")
    for (s, m), g in rep.groupby(["scenario", "mapping"]):
        g = g.sort_values("fct_us", ascending=False)
        k = max(1, len(g) // 10)
        print(f"  {s:22s} map {m:3s}  top10% share {g['fct_us'].head(k).sum() / g['fct_us'].sum():.3f}"
              f"   pairs with any flow > 300us: {g[g['fct_us'] > 300][['src', 'dst']].drop_duplicates().shape[0]}")


if __name__ == "__main__":
    main()
