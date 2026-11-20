# -*- coding: utf-8 -*-
"""stemseal update - bring cells made after this version was installed.

Reads cells/index.json from the public repo, downloads only cells this machine lacks (or newer versions), and
re-checks each one here before it can be used: the sha256 must match the index and the lock, the purity gate must pass,
and every ground-truth case must pass on this machine. A cell that fails any check is not installed.
Only runs when you type it; nothing else in stemseal touches the network. Nothing is sent: it only downloads.

  stemseal update          install new cells
  stemseal update --check  only list what is new
Maintainers: `stemseal index` rewrites stemseal/cells/index.json from the shipped cells before a push."""
import json, os, shutil, tempfile, urllib.request
from . import hub

RAW = os.environ.get("STEMSEAL_INDEX_URL", "https://raw.githubusercontent.com/roarose/stemseal/main/stemseal/cells")
FILES = ("cell.py", "contract.json", "gt_cases.json", "lock.json")

def build_index(base=None):
    base = base or hub.CELLS; out = {}
    for name in sorted(os.listdir(base)):
        d = os.path.join(base, name)
        if not os.path.isdir(d): continue
        for v in sorted((v for v in os.listdir(d) if os.path.exists(os.path.join(d, v, "lock.json"))), key=hub._vkey):
            L = json.load(open(os.path.join(d, v, "lock.json"), encoding="utf-8"))
            c = json.load(open(os.path.join(d, v, "contract.json"), encoding="utf-8"))
            out.setdefault(name, {})[v] = {"sha256": L["sha256"], "gt": L["gt_total"], "locked_at": L["locked_at"],
                                           "description": c.get("description", ""), "description_en": c.get("description_en", ""),
                                           "answers": c.get("answers", [])}
    idx = {"format": 1, "cells": out}
    json.dump(idx, open(os.path.join(base, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return idx

def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "stemseal-update"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()

def new_cells(index):
    have = {}
    for c in hub.list_cells(): have[c["cell"]] = hub._versions(c["cell"])
    todo = []
    for name, vers in index.get("cells", {}).items():
        for v, meta in sorted(vers.items(), key=lambda x: hub._vkey(x[0])):
            if v not in have.get(name, []): todo.append((name, v, meta))
    return todo

def update(check_only=False):
    try: index = json.loads(_get(RAW + "/index.json"))
    except Exception as e: return {"ok": False, "reason": "cannot read the cell index: %s" % e}
    todo = new_cells(index)
    if check_only: return {"ok": True, "new": [{"cell": n, "version": v, "description": m.get("description")} for n, v, m in todo]}
    done, refused = [], []
    for name, v, meta in todo:
        tmp = tempfile.mkdtemp(prefix="stemseal_")
        try:
            for f in FILES:
                open(os.path.join(tmp, f), "wb").write(_get("%s/%s/%s/%s" % (RAW, name, v, f)))
            src = open(os.path.join(tmp, "cell.py"), encoding="utf-8").read()
            lock = json.load(open(os.path.join(tmp, "lock.json"), encoding="utf-8"))
            why = None
            if hub.sha(src) != meta["sha256"] or lock.get("sha256") != meta["sha256"]: why = "sha256 does not match the index"
            elif hub.purity_check(src): why = "policy gate: %s" % hub.purity_check(src)
            else:
                rep = hub.gt_check(src, json.load(open(os.path.join(tmp, "gt_cases.json"), encoding="utf-8")))
                if rep["passed"] != rep["total"] or rep["total"] < hub.MIN_GT or not rep["deterministic"]:
                    why = "ground-truth gate on this machine: %d/%d" % (rep["passed"], rep["total"])
            if why: refused.append({"cell": name, "version": v, "reason": why}); continue
            try: open(os.path.join(tmp, "baseline.json"), "wb").write(_get("%s/%s/%s/baseline.json" % (RAW, name, v)))   # optional: token baseline, not part of the lock
            except Exception: pass
            dest = os.path.join(hub.USER_CELLS, name, v)
            if os.path.isdir(dest): shutil.rmtree(dest)
            shutil.copytree(tmp, dest)
            hub._log({"type": "update", "cell": name, "version": v, "sha256": meta["sha256"]})
            for t in meta.get("answers", []): hub._log({"type": "fulfilled", "ticket": t, "cell": name})
            done.append({"cell": name, "version": v, "description": meta.get("description")})
        except Exception as e:
            refused.append({"cell": name, "version": v, "reason": "download failed: %s" % e})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return {"ok": True, "installed": done, "refused": refused, "where": hub.USER_CELLS}
