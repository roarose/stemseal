#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare cell-call time of two stemseal source trees on this machine, alternating A, B, A, B so that the machine's
state affects both alike.   python scripts/bench_ab.py <tree A> <tree B> [--rounds 6] [--per-round 5] [--warmup 5]
Prints, per cell and overall, the median and 95th percentile of each tree and B/A ratios."""
import json, os, statistics, subprocess, sys, tempfile

PROBE = r'''
import json, os, sys, time, tempfile
sys.path.insert(0, sys.argv[1]); os.environ["STEMSEAL_HOME"] = tempfile.mkdtemp()
from stemseal import hub
cases = json.loads(sys.argv[2]); per, warm = int(sys.argv[3]), int(sys.argv[4]); out = {}
for name, inp in cases:
    for _ in range(warm): hub.call(name, inp, caller="bench", log=False)
    ms = []
    for _ in range(per):
        t = time.perf_counter(); r = hub.call(name, inp, caller="bench", log=False); ms.append((time.perf_counter() - t) * 1000)
        assert r["status"] == "ok", (name, r)
    out[name] = ms
print(json.dumps(out))
'''

def cases(tree):
    base = os.path.join(tree, "stemseal", "cells"); out = []
    for name in sorted(os.listdir(base)):
        d = os.path.join(base, name)
        if not os.path.isdir(d): continue
        v = sorted((x for x in os.listdir(d) if os.path.exists(os.path.join(d, x, "gt_cases.json"))), key=lambda x: [int(p) for p in x.split(".")])
        if not v: continue
        with open(os.path.join(d, v[-1], "gt_cases.json"), encoding="utf-8") as f: gt = [c for c in json.load(f) if "expected" in c]
        if gt: out.append([name, gt[0]["input"]])
    return out

def pct(xs, q): xs = sorted(xs); return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]

def main(a):
    A, B = a[0], a[1]; opt = lambda k, d: int(a[a.index(k) + 1]) if k in a else d
    rounds, per, warm = opt("--rounds", 6), opt("--per-round", 5), opt("--warmup", 5)
    cs = [c for c in cases(A) if c in cases(B)]
    res = {"A": {}, "B": {}}
    for r in range(rounds):
        for tag, tree in (("A", A), ("B", B)) if r % 2 == 0 else (("B", B), ("A", A)):
            p = subprocess.run([sys.executable, "-c", PROBE, tree, json.dumps(cs, ensure_ascii=False), str(per), str(warm if r < 2 else 1)], capture_output=True, timeout=600)
            if p.returncode: sys.exit(p.stderr.decode())
            for k, v in json.loads(p.stdout).items(): res[tag].setdefault(k, []).extend(v)
    rows = []
    for k in sorted(res["A"]):
        a_, b_ = res["A"][k], res["B"][k]
        rows.append((k, statistics.median(a_), pct(a_, .95), statistics.median(b_), pct(b_, .95)))
    allA = [x for v in res["A"].values() for x in v]; allB = [x for v in res["B"].values() for x in v]
    rows.append(("ALL", statistics.median(allA), pct(allA, .95), statistics.median(allB), pct(allB, .95)))
    print("| cell | A median ms | A p95 ms | B median ms | B p95 ms | median B/A | p95 B/A |\n|---|---|---|---|---|---|---|")
    for k, am, ap, bm, bp in rows: print("| %s | %.1f | %.1f | %.1f | %.1f | %.2f | %.2f |" % (k, am, ap, bm, bp, bm / am, bp / ap))
    print("\nsamples per cell per tree: %d (rounds %d x %d, alternating)" % (rounds * per, rounds, per))

if __name__ == "__main__": main(sys.argv[1:])
