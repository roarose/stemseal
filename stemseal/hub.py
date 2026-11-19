#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stemseal - core (lite: runs on your machine, no server).

A cell is a verified, locked, deterministic function `cell_executor(input_data: dict) -> dict`.
The hub only answers from locked cells. Anything else is an honest refusal (not_available),
and every refusal is recorded as demand for a future cell.

Layout:  cells/<name>/<version>/{cell.py, contract.json, gt_cases.json, lock.json}
         ledger/calls.jsonl   (one line per call, find and refusal)
Stdlib only.
"""
import ast, hashlib, json, os, re, subprocess, sys, time
from datetime import datetime, timezone

PKG = os.path.dirname(os.path.abspath(__file__))
def _home():
    """Where your own log lives; nothing is sent anywhere. MCP apps sometimes start servers without HOME/USERPROFILE,
    so fall back to the app-data folder, then the temp folder, rather than a path relative to wherever the app runs."""
    if os.environ.get("STEMSEAL_HOME"): return os.environ["STEMSEAL_HOME"]
    h = os.path.expanduser("~")
    if h and not h.startswith("~") and os.path.isdir(h): return os.path.join(h, ".stemseal")
    for k in ("LOCALAPPDATA", "APPDATA"):
        if os.environ.get(k): return os.path.join(os.environ[k], "stemseal")
    import tempfile; return os.path.join(tempfile.gettempdir(), "stemseal")
HOME = _home()
CELLS = os.environ.get("STEMSEAL_CELLS") or os.path.join(PKG, "cells")   # cells shipped with this version
USER_CELLS = os.path.join(HOME, "cells")                                    # cells added later by `stemseal update`
def _dirs(): return [CELLS] + ([USER_CELLS] if os.path.abspath(USER_CELLS) != os.path.abspath(CELLS) else [])
LEDGER = os.path.join(HOME, "ledger.jsonl")
REPO = "https://github.com/roarose/stemseal"
MIN_GT = 20                      # a cell needs at least this many ground-truth cases to be locked
CALL_TIMEOUT = 5                 # seconds per call
ALLOWED_IMPORTS = {"math", "statistics", "decimal", "fractions", "re", "json", "collections", "itertools", "functools"}   # no clock, no random, no I/O
FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "globals", "locals", "vars", "getattr", "setattr", "delattr", "exit", "quit"}
RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_runner.py")

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def sha(b): return hashlib.sha256(b if isinstance(b, bytes) else b.encode("utf-8")).hexdigest()
def _log(rec):
    """Logging must never break a call: if the log folder cannot be written, the answer still goes back."""
    try:
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        rec = {"ts": now(), **rec}
        with open(LEDGER, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception: pass

# ---------------------------------------------------------------- gate 1: purity
def purity_check(src):
    """Static check: a cell may only compute. Returns a list of problems (empty = clean)."""
    try: tree = ast.parse(src)
    except SyntaxError as e: return ["syntax error: %s" % e]
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            bad += ["import %s" % a.name for a in n.names if a.name.split(".")[0] not in ALLOWED_IMPORTS]
        elif isinstance(n, ast.ImportFrom):
            if (n.module or "").split(".")[0] not in ALLOWED_IMPORTS: bad.append("from %s import" % n.module)
        elif isinstance(n, ast.Name) and n.id in FORBIDDEN_NAMES: bad.append("use of %s" % n.id)
        elif isinstance(n, ast.Attribute) and n.attr.startswith("__"): bad.append("dunder attribute %s" % n.attr)
    if not any(isinstance(n, ast.FunctionDef) and n.name == "cell_executor" for n in tree.body): bad.append("no top-level cell_executor function")
    return sorted(set(bad))

# ---------------------------------------------------------------- isolated execution
def _limits():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (CALL_TIMEOUT * 4, CALL_TIMEOUT * 4))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except Exception: pass

def run_isolated(cell_path, inputs, timeout=None):
    """Run cell_executor on a list of inputs in a separate, stripped-down Python process.
    Returns a list of {"ok": bool, "out": ..., "err": str}. This is process isolation plus the purity gate,
    not an OS-level sandbox: before running cells written by strangers, put this process in a container."""
    kw = {"preexec_fn": _limits} if os.name == "posix" else {}
    env = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
    try:
        p = subprocess.run([sys.executable, "-I", "-X", "utf8", RUNNER, cell_path], input=json.dumps(inputs, ensure_ascii=False).encode("utf-8"),
                           capture_output=True, timeout=timeout or CALL_TIMEOUT * max(1, len(inputs) // 5 + 1), env=env, cwd=os.path.dirname(cell_path), **kw)
    except subprocess.TimeoutExpired:
        return [{"ok": False, "err": "timeout"} for _ in inputs]
    if p.returncode != 0:
        msg = (p.stderr.decode("utf-8", "replace").strip().splitlines() or ["exit %d" % p.returncode])[-1][:300]
        return [{"ok": False, "err": msg} for _ in inputs]
    return json.loads(p.stdout.decode("utf-8"))

# ---------------------------------------------------------------- gate 2: ground truth
def gt_check(cell_path, gt_cases):
    res = run_isolated(cell_path, [c["input"] for c in gt_cases])
    fails = [{"case": i, "expected": c["expected"], "got": r.get("out"), "err": r.get("err")} for i, (c, r) in enumerate(zip(gt_cases, res)) if not (r.get("ok") and r.get("out") == c["expected"])]
    # determinism: second run must give byte-identical outputs
    res2 = run_isolated(cell_path, [c["input"] for c in gt_cases])
    deterministic = json.dumps(res, sort_keys=True) == json.dumps(res2, sort_keys=True)
    return {"total": len(gt_cases), "passed": len(gt_cases) - len(fails), "deterministic": deterministic, "failures": fails[:5]}

# ---------------------------------------------------------------- registry
def _vkey(v): return [int(x) for x in v.split(".")]
def _found(name):
    """{version: dir} over the shipped cells and the ones `stemseal update` added; the shipped copy wins a tie."""
    out = {}
    for base in reversed(_dirs()):
        d = os.path.join(base, name)
        if os.path.isdir(d):
            for v in os.listdir(d):
                if os.path.exists(os.path.join(d, v, "lock.json")): out[v] = os.path.join(d, v)
    return out
def _versions(name): return sorted(_found(name), key=_vkey)
def cell_dir(name, version=None):
    f = _found(name)
    if not f: return None
    v = version or sorted(f, key=_vkey)[-1]
    return f.get(v)
def load(name, version=None):
    d = cell_dir(name, version)
    if not d: return None
    return {"dir": d, "contract": json.load(open(os.path.join(d, "contract.json"), encoding="utf-8")), "lock": json.load(open(os.path.join(d, "lock.json"), encoding="utf-8"))}
def list_cells():
    out = []
    names = sorted({n for b in _dirs() if os.path.isdir(b) for n in os.listdir(b) if os.path.isdir(os.path.join(b, n))})
    for name in names:
        c = load(name)
        if c: out.append({"cell": name, "version": c["lock"]["version"], "description": c["contract"]["description"], "when_to_use": c["contract"].get("when_to_use", ""),
                          "description_en": c["contract"].get("description_en", ""), "when_to_use_en": c["contract"].get("when_to_use_en", ""),
                          "required_inputs": c["contract"]["input_schema"].get("required", []), "gt_cases": c["lock"]["gt_total"], "locked_at": c["lock"]["locked_at"]})
    return out

def register(name, src, contract, gt_cases, locked_by="unknown", base=None):
    """The only way a cell enters the hub: purity gate, then ground-truth gate, then lock. Returns a report; report['locked'] says if it got in.
    A locked version is never overwritten. A change is a new version."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", name): return {"locked": False, "reason": "bad name"}
    for k in ("description", "input_schema", "output_keys"):
        if k not in contract: return {"locked": False, "reason": "contract missing %s" % k}
    if len(gt_cases) < MIN_GT: return {"locked": False, "reason": "needs at least %d ground-truth cases, got %d" % (MIN_GT, len(gt_cases))}
    problems = purity_check(src)
    if problems: return {"locked": False, "reason": "purity gate", "problems": problems}
    vs = _versions(name); version = "%d.0" % (int(vs[-1].split(".")[0]) + 1) if vs else "1.0"
    d = os.path.join(os.path.abspath(base or CELLS), name, version); os.makedirs(d, exist_ok=True)
    cp = os.path.join(d, "cell.py"); open(cp, "w", encoding="utf-8", newline="\n").write(src)
    rep = gt_check(cp, gt_cases)
    if rep["passed"] != rep["total"] or not rep["deterministic"]:
        os.remove(cp); 
        try: os.rmdir(d)
        except OSError: pass
        return {"locked": False, "reason": "ground-truth gate", "report": rep}
    json.dump(contract, open(os.path.join(d, "contract.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(gt_cases, open(os.path.join(d, "gt_cases.json"), "w", encoding="utf-8"), ensure_ascii=False)
    lock = {"cell": name, "version": version, "sha256": sha(src), "gt_total": rep["total"], "gt_passed": rep["passed"], "deterministic": True, "locked_at": now(), "locked_by": locked_by}
    json.dump(lock, open(os.path.join(d, "lock.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    _log({"type": "lock", "cell": name, "version": version, "sha256": lock["sha256"], "gt": rep["total"], "by": locked_by})
    return {"locked": True, "cell": name, "version": version, "sha256": lock["sha256"], "report": rep}

def input_help(c):
    """What a caller needs to retry a refused call: the exact input keys, what each means, and a template to fill (no example numbers: small models copy them)."""
    sch = c["contract"]["input_schema"]; h = {"required_inputs": sch.get("required", []), "inputs": sch.get("properties", {}),
        "note": "Call call_cell again with exactly these keys in `input`. Optional inputs can be left out."}
    h["input_template"] = {k: "<%s, from the user's question>" % sch.get("properties", {}).get(k, "number") for k in h["required_inputs"]}
    return h

# ---------------------------------------------------------------- the membrane: call
def call(name, input_data, caller="unknown", version=None):
    """status = ok | not_available | invalid_input. A result only ever comes from a locked, untampered cell."""
    t0 = time.time()
    def env(status, result=None, reason=None, ver=None):
        rec = {"type": "call", "cell": name, "version": ver, "status": status, "caller": caller, "ms": round((time.time() - t0) * 1000, 1),
               "input_sha": sha(json.dumps(input_data, sort_keys=True, ensure_ascii=False))[:16] if isinstance(input_data, dict) else None, "reason": reason}
        if status != "ok" and isinstance(input_data, dict): rec["input_keys"] = sorted(str(k) for k in input_data)[:12]   # names only, never values
        _log(rec)
        out = {"status": status, "cell": name, "version": ver, "verified": status == "ok", "result": result, "reason": reason}
        if status == "invalid_input" and c: out["how_to_fix"] = input_help(c)
        return out
    c = load(name, version) if isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9_]{2,63}", name or "") else None
    if not c: return env("not_available", reason="no locked cell with this name")
    ver = c["lock"]["version"]; cp = os.path.join(c["dir"], "cell.py")
    if sha(open(cp, "rb").read().decode("utf-8")) != c["lock"]["sha256"]: return env("not_available", reason="cell file does not match its lock", ver=ver)
    if not isinstance(input_data, dict): return env("invalid_input", reason="input must be an object", ver=ver)
    missing = [k for k in c["contract"]["input_schema"].get("required", []) if k not in input_data]
    if missing: return env("invalid_input", reason="missing required inputs: %s" % missing, ver=ver)
    r = run_isolated(cp, [input_data])[0]
    if not r.get("ok"): return env("invalid_input", reason="cell rejected the input: %s" % r.get("err"), ver=ver)
    return env("ok", result=r["out"], ver=ver)

# ---------------------------------------------------------------- find (how an AI picks)
def _grams(s):
    """Words and their 2-letter pieces. Pieces with a digit are dropped: numbers in a request are data (10030, 3.2),
    and their pieces only dilute the score of the words that name the calculation."""
    s = re.sub(r"[^0-9a-z가-힣]+", " ", (s or "").lower()); toks = [t for t in s.split() if not t.isdigit()]; g = set(toks)
    for t in toks: g.update(p for p in (t[i:i + 2] for i in range(len(t) - 1)) if not any(ch.isdigit() for ch in p))
    return g
def _rank(need, min_score):
    q = _grams(need); scored = []
    if not q: return scored
    for c in list_cells():
        con = load(c["cell"])["contract"]
        doc = _grams(" ".join([c["cell"].replace("_", " "), con["description"], con.get("when_to_use", ""), con.get("description_en", ""), con.get("when_to_use_en", ""), " ".join(con.get("keywords", []))]))
        s = len(q & doc) / max(1, len(q))
        if s >= min_score: scored.append((round(s, 3), c))
    scored.sort(key=lambda x: -x[0]); return scored
def find(need, caller="unknown", k=3, min_score=0.3, words=None):
    """Return up to k locked cells that fit the stated need, best first. An empty list is an honest 'nothing fits', logged as demand.
    words: the caller's own short names for the calculation (e.g. "연평균 성장률"). They are searched on their own and the two result lists
    are taken in turn (request, words, request, ...), so a request worded unlike any cell card can still reach its cell (exp8)."""
    a = _rank(need, min_score); b = _rank(" ".join(str(w) for w in words), min_score) if words else []
    hits = []; seen = set()
    for i in range(max(len(a), len(b))):
        for lst in (a, b):
            if i < len(lst) and lst[i][1]["cell"] not in seen: seen.add(lst[i][1]["cell"]); hits.append(dict(lst[i][1], score=lst[i][0]))
    hits = hits[:k]
    _log({"type": "find", "need": need[:300], "words": (words or [])[:8], "caller": caller, "hits": [h["cell"] for h in hits]})
    if not hits: _log({"type": "demand", "need": need[:300], "caller": caller})
    return hits
PROMISE = ("이 계산을 하는 검증된 세포가 아직 없습니다. 지금은 직접 처리하시고, 필요한 계산은 이 기기에 기록했습니다. "
           "share 링크로 요청하면 수요가 모이는 순서대로 새 세포를 만들고, 사용자가 `stemseal update` 를 하면 바로 쓸 수 있습니다. / "
           "No verified cell does this yet. Handle it yourself for now; the need is saved on this machine. "
           "Requests sent through the share link are built as demand gathers; `stemseal update` then brings the new cell here.")
def _ticket(need):
    return "D-" + sha(re.sub(r"\s+", " ", (need or "").strip().lower()))[:8]
def _rows():
    try: return [json.loads(l) for l in open(LEDGER, encoding="utf-8") if l.strip()] if os.path.exists(LEDGER) else []
    except Exception: return []
def share_link(t, need):
    """A prefilled GitHub issue. Opening it is the user's choice; stemseal never sends it."""
    from urllib.parse import quote
    body = "ticket: %s\nneed: %s\n\n(Optional) an example input and the answer you expect:\n" % (t, need)
    return "%s/issues/new?labels=cell-request&title=%s&body=%s" % (REPO, quote(("cell request " + t + ": " + need)[:120]), quote(body[:1500]))
def request_cell(need, caller="unknown"):
    """An AI says: I needed this and nothing fit. Recorded as demand; this is what gets differentiated next.
    Returns a ticket (same need -> same ticket) and a promise, so the caller knows the channel is being built and comes back."""
    t = _ticket(need)
    _log({"type": "demand", "need": need[:300], "caller": caller, "explicit": True, "ticket": t})
    n = sum(1 for r in _rows() if r.get("type") == "demand" and r.get("ticket") == t)
    link = share_link(t, need)
    return {"recorded": True, "ticket": t, "times_requested": n, "message": PROMISE,
            "share": {"note": "This request is saved only on this machine. To ask for the cell, the user can open this link (nothing is sent automatically).", "link": link}}
def fulfill(ticket, cell):
    """The hub keeper marks a demand ticket as answered by a locked cell."""
    if not load(cell): return {"ok": False, "reason": "no locked cell with this name"}
    _log({"type": "fulfilled", "ticket": ticket, "cell": cell}); return {"ok": True}
def request_status(ticket):
    rows = _rows(); f = [r for r in rows if r.get("type") == "fulfilled" and r.get("ticket") == ticket]
    n = sum(1 for r in rows if r.get("type") == "demand" and r.get("ticket") == ticket)
    if f: return {"ticket": ticket, "status": "ready", "cell": f[-1]["cell"], "times_requested": n}
    return {"ticket": ticket, "status": "queued" if n else "unknown", "times_requested": n}

# ---------------------------------------------------------------- observation
def stats():
    rows = [json.loads(l) for l in open(LEDGER, encoding="utf-8") if l.strip()] if os.path.exists(LEDGER) else []
    calls = [r for r in rows if r["type"] == "call"]; per = {}
    for r in calls:
        p = per.setdefault(r["cell"], {"calls": 0, "ok": 0, "ms": 0.0, "callers": set()})
        p["calls"] += 1; p["ok"] += r["status"] == "ok"; p["ms"] += r["ms"]; p["callers"].add(r["caller"])
    demand = {}
    for r in rows:
        if r["type"] == "demand": demand[r["need"]] = demand.get(r["need"], 0) + 1
    return {"cells_locked": len(list_cells()), "calls": len(calls), "ok": sum(r["status"] == "ok" for r in calls), "refused": sum(r["status"] != "ok" for r in calls),
            "distinct_callers": len({r["caller"] for r in calls}), "finds": sum(r["type"] == "find" for r in rows),
            "per_cell": {k: {"calls": v["calls"], "ok": v["ok"], "avg_ms": round(v["ms"] / v["calls"], 1), "callers": sorted(v["callers"])} for k, v in sorted(per.items(), key=lambda x: -x[1]["calls"])},
            "unmet_demand": sorted(demand.items(), key=lambda x: -x[1])[:20]}

def verify_all():
    out = {}
    for c in list_cells():
        L = load(c["cell"]); cp = os.path.join(L["dir"], "cell.py")
        ok_hash = sha(open(cp, encoding="utf-8").read()) == L["lock"]["sha256"]
        rep = gt_check(cp, json.load(open(os.path.join(L["dir"], "gt_cases.json"), encoding="utf-8")))
        out[c["cell"]] = {"version": c["version"], "hash_ok": ok_hash, "gt": "%d/%d" % (rep["passed"], rep["total"]), "deterministic": rep["deterministic"]}
    return out
