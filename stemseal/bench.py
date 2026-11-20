# -*- coding: utf-8 -*-
"""stemseal bench - how long a cell call takes on this machine (the whole call: separate process, checks, the cell).
  stemseal bench [--n 30] [--warmup 5]
Each shipped cell is called with its first ground-truth input; nothing is written to the ledger.
The result is printed and saved to ~/.stemseal/bench-<time>.json. To compare two versions on the same machine,
see scripts/bench_ab.py in the repository."""
import json, os, statistics, time
from datetime import datetime
from . import hub, __version__

def _cases():
    for name in sorted({c["cell"] for c in hub.list_cells()}):
        c = hub.load(name); p = os.path.join(c["dir"], "gt_cases.json")
        if not os.path.exists(p): continue
        with open(p, encoding="utf-8") as f: cases = json.load(f)
        ok = [x for x in cases if "expected" in x]
        if ok: yield name, ok[0]["input"]

def pct(xs, q):
    xs = sorted(xs); return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]

def bench(n=30, warmup=5):
    per = {}; allms = []
    for name, inp in _cases():
        for _ in range(warmup): hub.call(name, inp, caller="bench", log=False)
        ms = []
        for _ in range(n):
            t = time.perf_counter(); r = hub.call(name, inp, caller="bench", log=False); ms.append((time.perf_counter() - t) * 1000)
            if r["status"] != "ok": raise RuntimeError("%s did not answer ok: %s" % (name, r.get("reason")))
        per[name] = {"median_ms": round(statistics.median(ms), 1), "p95_ms": round(pct(ms, 0.95), 1)}; allms += ms
    return {"version": __version__, "n": n, "warmup": warmup, "cells": per,
            "all_median_ms": round(statistics.median(allms), 1) if allms else None, "all_p95_ms": round(pct(allms, 0.95), 1) if allms else None,
            "at": datetime.now().isoformat(timespec="seconds")}

def run(n=30, warmup=5):
    r = bench(n, warmup)
    try:
        os.makedirs(hub.HOME, exist_ok=True)
        p = os.path.join(hub.HOME, "bench-%s.json" % datetime.now().strftime("%Y%m%d-%H%M%S"))
        with open(p, "w", encoding="utf-8") as f: json.dump(r, f, ensure_ascii=False, indent=1)
        r["saved"] = p
    except OSError: pass
    return r
