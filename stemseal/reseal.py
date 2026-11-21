# -*- coding: utf-8 -*-
"""stemseal reseal / relock - give a cell a format 2 lock (seal.py) at the same version.

  stemseal reseal <name ...> | --all [--dry-run]
      For your own cells under ~/.stemseal/cells that still have a format 1 lock. Each is re-sealed only when its cell.py
      is the one its lock names, it passes this version's checker, and it has at least MIN_GT ground-truth cases that all
      pass here, twice alike. The old lock is kept as lock.v1.json. A cell that does not pass is left as it is.
      A re-sealed cell is a cell of this machine only: copied to another machine, it is re-sealed there.

  stemseal relock [--dry-run]   (maintainers)
      The same for the cells shipped in the package, before a release. Writes nothing unless every shipped cell passes.
Standard library only."""
import json, os, platform
from . import hub, policy, seal, shape

def _check(name, d, lock):
    """(None, report) when the cell in d can be sealed as it is; (reason, None) otherwise."""
    raw = {f: seal.read_bytes(d, f) for f in seal.SEALED}
    missing = [f for f in seal.SEALED if raw[f] is None]
    if missing: return "missing %s" % ", ".join(missing), None
    if not isinstance(lock, dict) or lock.get("cell") != name or lock.get("version") != os.path.basename(d):
        return "lock.json does not name this cell", None
    if seal.sha(raw["cell.py"]) != lock.get("sha256"): return "cell.py is not the file its lock names (changed after locking)", None
    try: contract = json.loads(raw["contract.json"].decode("utf-8")); gt = json.loads(raw["gt_cases.json"].decode("utf-8"))
    except ValueError: return "contract.json or gt_cases.json is not valid JSON", None
    schema = contract.get("output_schema") if isinstance(contract, dict) else None
    if schema is not None:
        bad = shape.schema_problem(schema, contract.get("output_keys"))
        if bad: return bad, None
    problems = hub.purity_check(raw["cell.py"])
    if problems: return "checker: %s" % "; ".join(problems[:3]), None
    if not isinstance(gt, list) or len(gt) < hub.MIN_GT: return "needs at least %d ground-truth cases" % hub.MIN_GT, None
    rep = hub.gt_check(raw["cell.py"].decode("utf-8"), gt, schema)
    if rep["passed"] != rep["total"] or not rep["deterministic"]:
        return "ground truth %d/%d%s" % (rep["passed"], rep["total"], "" if rep["deterministic"] else ", not deterministic"), None
    return None, {"raw": raw, "rep": rep}

def _versions(base, name):
    d = os.path.join(base, name)
    if not os.path.isdir(d): return []
    return sorted((v for v in os.listdir(d) if os.path.isfile(os.path.join(d, v, "lock.json"))), key=hub._vkey)

def _lock(d):
    try:
        with open(os.path.join(d, "lock.json"), "rb") as f: return json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError): return None

def reseal(names=None, dry_run=False, base=None):
    """names: cells to re-seal (None: every cell with a format 1 lock). Returns {"resealed", "failed", "skipped", "dry_run"}."""
    base = base or hub.USER_CELLS
    every = sorted(n for n in os.listdir(base) if os.path.isdir(os.path.join(base, n))) if os.path.isdir(base) else []
    out = {"resealed": [], "failed": [], "skipped": [], "dry_run": bool(dry_run), "where": base}
    for name in (names if names else every):
        vs = _versions(base, name)
        if not vs: out["skipped"].append({"cell": name, "why": "not one of your cells (%s)" % base}); continue
        for v in vs:
            d = os.path.join(base, name, v); lock = _lock(d)
            if seal.problem(lock, {}) != seal.OLD:
                if names: out["skipped"].append({"cell": name, "version": v, "why": "already format 2" if seal.problem(lock, {}) is None else "lock.json is not a format 1 lock"})
                continue
            if os.path.exists(os.path.join(d, "lock.v1.json")):
                out["failed"].append({"cell": name, "version": v, "why": "lock.v1.json already exists"}); continue
            why, ok = _check(name, d, lock)
            if why: out["failed"].append({"cell": name, "version": v, "why": why}); continue
            if not dry_run:
                new = seal.build(name, v, ok["raw"], policy.POLICY_VERSION, ok["rep"]["total"], ok["rep"]["passed"], hub.now(),
                                 "reseal on %s" % (platform.node() or "this machine"))
                seal.write(d, new, keep_old_as="lock.v1.json")
                hub._log({"type": "lock", "cell": name, "version": v, "sha256": new["sha256"], "gt": new["gt_total"], "by": "reseal"})
            out["resealed"].append({"cell": name, "version": v})
    return out

def relock(dry_run=False, base=None):
    """Every shipped cell version, at the same version. Writes nothing unless all of them pass. Returns {"ok", "changed", "failed"}."""
    base = base or hub.CELLS
    plan, failed = [], []
    for name in sorted(n for n in os.listdir(base) if os.path.isdir(os.path.join(base, n))):
        for v in _versions(base, name):
            d = os.path.join(base, name, v); lock = _lock(d)
            why, ok = _check(name, d, lock)
            if why: failed.append({"cell": name, "version": v, "why": why}); continue
            new = seal.build(name, v, ok["raw"], policy.POLICY_VERSION, ok["rep"]["total"], ok["rep"]["passed"], lock.get("locked_at"), lock.get("locked_by"))
            if seal.dumps(new) != seal.read_bytes(d, "lock.json"): plan.append((d, new))
    if failed or dry_run:
        return {"ok": not failed, "changed": [os.path.relpath(d, base) for d, _ in plan], "failed": failed, "written": False}
    for d, new in plan: seal.write(d, new)
    return {"ok": True, "changed": [os.path.relpath(d, base) for d, _ in plan], "failed": [], "written": True}
