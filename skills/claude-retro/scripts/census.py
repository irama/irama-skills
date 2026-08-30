#!/usr/bin/env python3
"""Join two independent coding runs and report what is safe to claim.

One coding run is not enough. Measured 2026-08-31 on 499 records coded twice: the outcome
column agreed only 71.9% exactly and 80.4% on the collapsed binary, and the "changed
something" count came out 100 in one run and 128 in the other. The *ordering* of moves was
stable across both runs; the point estimates were not.

So this reports the ordering as the finding, and any ratio as a range across runs.

Usage: census.py run1.csv run2.csv
CSV format per line: id,MOVE,OUTCOME,conf
"""
import csv, sys, collections

TARGET = {"BRIEF", "REFOCUS", "LOGIC"}
OUTPUT = {"TEST", "HELP", "REMIND"}

def load(p):
    return {r[0]: (r[1].strip().upper(), r[2].strip().upper())
            for r in csv.reader(open(p)) if len(r) >= 3 and r[0] != "id"}

def main():
    runs = [load(p) for p in sys.argv[1:3]]
    print(f"=== move census, {len(runs[0])} turns, {len(runs)} independent coding runs ===\n")

    for i, run in enumerate(runs, 1):
        c = collections.Counter(m for m, _ in run.values())
        n = len(run)
        print(f"run {i}:")
        print(f"  {'move':<10}{'n':>5}{'share':>8}{'changed':>9}")
        for m, k in c.most_common():
            dr = sum(1 for mv, o in run.values() if mv == m and o in "DR")
            print(f"  {m:<10}{k:>5}{k/n:>7.1%}{dr/k:>8.0%}")
        print()

    if len(runs) < 2:
        print("WARNING: only one run given. Do not quote any rate from a single run.")
        return

    a, b = runs
    both = [k for k in a if k in b]
    exact = sum(1 for k in both if a[k][1] == b[k][1])
    binary = sum(1 for k in both if (a[k][1] in "DR") == (b[k][1] in "DR"))
    move_ag = sum(1 for k in both if a[k][0] == b[k][0])
    print(f"=== reliability across the two runs ({len(both)} shared records) ===")
    print(f"  move agreement:                 {move_ag/len(both):.1%}")
    print(f"  outcome exact agreement:        {exact/len(both):.1%}")
    print(f"  outcome collapsed to changed:   {binary/len(both):.1%}")
    if binary / len(both) < 0.85:
        print("  -> below 85%. Report the ORDERING of moves, not the rates.")

    print("\n=== ordering by 'changed direction or rebuilt' (the reproducible finding) ===")
    for i, run in enumerate(runs, 1):
        c = collections.Counter(m for m, _ in run.values())
        rk = sorted(((sum(1 for mv, o in run.values() if mv == m and o in "DR") / k, m)
                     for m, k in c.items() if k >= 8), reverse=True)
        print(f"  run {i}: " + "  ".join(f"{m}({r:.0%})" for r, m in rk))

    print("\n=== target-setting vs output-checking, as a range ===")
    for i, run in enumerate(runs, 1):
        t = [v for v in run.values() if v[0] in TARGET]
        o = [v for v in run.values() if v[0] in OUTPUT]
        if not t or not o:
            continue
        tr = sum(1 for _, x in t if x in "DR") / len(t)
        orr = sum(1 for _, x in o if x in "DR") / len(o)
        print(f"  run {i}: target {len(t):>3} turns {tr:.0%} | output {len(o):>3} turns {orr:.0%}"
              f" | ratio {tr/orr if orr else float('inf'):.1f}x")

if __name__ == "__main__":
    main()
