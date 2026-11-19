#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stemseal - core (lite: runs on your machine, no server).

A cell is a verified, locked, deterministic function `cell_executor(input_data: dict) -> dict`.
The hub only answers from locked cells. Anything else is an honest refusal (not_available),
and every refusal is recorded as demand for a future cell.

Layout:  cells/<name>/<version>/{cell.py, contract.json, gt_cases.json, lock.json}
         ~/.stemseal/ledger.jsonl   (one line per call, find and refusal; call lines carry the token meter, see savings.py)
Stdlib only.
"""
import ast, hashlib, json, os, re, subprocess, sys, time
from datetime import datetime, timezone
from . import savings

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
def call(name, input_data, caller="unknown", version=None, model=None, decorate=None, log=True):
    """status = ok | not_available | invalid_input. A result only ever comes from a locked, untampered cell.
    Every call row carries its token meter (savings.py): what the call cost and, against the cell's baseline, what it saved.
    model: the calling model's name, when known (baselines are per model). decorate(out): lets a wrapper add its fields
    before the reply is measured, so the meter counts the reply the model actually reads."""
    t0 = time.time()
    def env(status, result=None, reason=None, ver=None):
        rec = {"type": "call", "cell": name, "version": ver, "status": status, "caller": caller, "ms": round((time.time() - t0) * 1000, 1),
               "input_sha": sha(json.dumps(input_data, sort_keys=True, ensure_ascii=False))[:16] if isinstance(input_data, dict) else None, "reason": reason}
        if status != "ok" and isinstance(input_data, dict): rec["input_keys"] = sorted(str(k) for k in input_data)[:12]   # names only, never values
        out = {"status": status, "cell": name, "version": ver, "verified": status == "ok", "result": result, "reason": reason}
        if status == "invalid_input" and c: out["how_to_fix"] = input_help(c)
        if decorate: decorate(out)
        rec["model"] = model
        try: rec["tokens"] = savings.meter(name, ver, model, {"cell": name, "input": input_data}, out, status == "ok")
        except Exception: pass   # the meter must never break a call
        if log: _log(rec)
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
def find(need, caller="unknown", k=3, min_score=0.3, words=None, model=None, record=True):
    """Return up to k locked cells that fit the stated need, best first. An empty list is an honest 'nothing fits', and the need
    is recorded as demand right there (auto=True), so demand gathers even when the model never calls request_cell.
    words: the caller's own short names for the calculation (e.g. "연평균 성장률"). They are searched on their own and the two result lists
    are taken in turn (request, words, request, ...), so a request worded unlike any cell card can still reach its cell (exp8).
    record=False: an internal probe (e.g. after a guessed cell name), whose caller records the demand itself."""
    need = need if isinstance(need, str) else ("" if need is None else json.dumps(need, ensure_ascii=False))
    a = _rank(need, min_score); b = _rank(" ".join(str(w) for w in words), min_score) if words else []
    hits = []; seen = set()
    for i in range(max(len(a), len(b))):
        for lst in (a, b):
            if i < len(lst) and lst[i][1]["cell"] not in seen: seen.add(lst[i][1]["cell"]); hits.append(dict(lst[i][1], score=lst[i][0]))
    hits = hits[:k]
    _log({"type": "find", "need": need[:300], "words": (words or [])[:8], "caller": caller, "hits": [h["cell"] for h in hits]})
    if not hits and record and need.strip(): _log_demand(need, caller, model=model, auto=True)
    return hits

# ---------------------------------------------------------------- demand (what to differentiate next)
# Every unmet need becomes one ledger row: {"type": "demand", "need", "caller", "model", "ticket", "auto" | "explicit",
# "nearest", "nearest_score", "example"}. auto = recorded by find/call when nothing fit; explicit = the model called request_cell.
# Rows stay on this machine. Requests for the same calculation share a ticket and are counted together; the count is the strength of the demand.
# Grouping is deliberately strict: merging two different calculations hides one of them, missing a merge only shows it twice.
CLOSE_ENOUGH = 0.2      # a nearest cell below this score is not worth mentioning
FILLER = {"계산", "계산기", "계산법", "계산하기", "구하기", "구하는", "구해", "방법", "금액", "값", "얼마", "알려줘", "해줘",
          "calculate", "calculation", "calculator", "compute", "computing", "amount", "value", "the", "a", "an", "of", "for", "how", "much", "to", "get"}
def _lang(text):
    v = (os.environ.get("STEMSEAL_LANG") or "").lower()
    if v in ("ko", "en"): return v
    return "ko" if any("가" <= ch <= "힣" for ch in (text or "")) else "en"
def _core(need):
    """The words of a need without the numbers and the '| inputs: ...' tail: what the calculation is, not this time's data."""
    return re.sub(r"\d[\d,.]*", " ", str(need or "").split(" | inputs:")[0])
def _words(need):
    """The words that name the calculation, in order: numbers, punctuation and filler (계산, amount, ...) removed."""
    return [w for w in re.sub(r"[^a-z가-힣]+", " ", _core(need).lower()).split() if w not in FILLER]
def _keys(need):
    """Two strict keys; a request matching either is the same calculation: the same words in any order ('loan monthly payment' =
    'monthly loan payment amount'), or the same letters spaced differently ('월 납입액' = '월납입액 계산'). A different word
    ('복리' vs '단리', '가중 평균' vs '평균') never matches."""
    w = _words(need)
    if not w: return ["x:" + re.sub(r"\s+", " ", str(need or "").strip().lower())]
    return ["s:" + " ".join(sorted(set(w))), "n:" + "".join(w)]
def _ticket(need):
    return "D-" + sha(_keys(need)[0])[:8]
def _rows(kind=None, path=None):
    """Ledger rows, oldest first. A damaged line (a write cut off midway) is skipped, never allowed to hide the rest.
    kind: a type or tuple of types to keep; the raw line is checked first, so a long call log does not slow a miss."""
    kinds = (kind,) if isinstance(kind, str) else tuple(kind or ())
    out = []
    try: f = open(path or LEDGER, encoding="utf-8", errors="replace")
    except OSError: return out
    with f:
        for l in f:
            if not l.strip() or (kinds and not any('"%s"' % k in l for k in kinds)): continue
            try: r = json.loads(l)
            except ValueError: continue
            if isinstance(r, dict) and (not kinds or r.get("type") in kinds): out.append(r)
    return out
def _doc_words(cell):
    c = load(cell)["contract"]
    return set(re.sub(r"[^a-z가-힣]+", " ", " ".join([cell.replace("_", " "), c["description"], c.get("when_to_use", ""), c.get("description_en", ""),
                                                       c.get("when_to_use_en", ""), " ".join(c.get("keywords", []))]).lower()).split()) - FILLER
def shares_word(text, cell):
    """True when the text and the cell's card have a whole word in common (two-letter pieces alone are noise: 'loan calc' ~ annual_leave)."""
    return bool(set(_words(text)) & _doc_words(cell))
def nearest(need):
    """The cell that comes closest to a need nothing fit, with its score, or (None, 0). Only a cell sharing a whole word counts."""
    for sc, c in _rank(_core(need), 0.0)[:5]:
        if sc > 0 and shares_word(need, c["cell"]): return c["cell"], sc
    return None, 0
def _log_demand(need, caller, model=None, auto=False, example=None):
    need = str(need or ""); t = _ticket(need); n, sc = nearest(need)
    rec = {"type": "demand", "need": need[:300], "caller": caller, "model": model, "ticket": t, "nearest": n, "nearest_score": sc}
    rec["auto" if auto else "explicit"] = True
    if example: rec["example"] = str(example)[:300]
    _log(rec); return t
def times_requested(need, rows=None):
    """How often this calculation was asked on this machine: one pass, no grouping (this runs on every miss)."""
    k = set(_keys(need)); rows = _rows("demand") if rows is None else rows
    return sum(1 for r in rows if r.get("type") == "demand" and k & set(_keys(r.get("need", ""))))

def summarize_demand(rows):
    """Group demand rows by the strict keys (same calculation; see _keys). Linear in the ledger size. Returns groups, open ones
    strongest first: {ticket, need, count, explicit, auto, tickets, models, callers, first, last, nearest, nearest_score, examples,
    wordings, status, cell}. status is 'ready' when a cell was marked as answering one of the group's tickets (stemseal update reads
    that from the index); only the same calculation joins a ready group, so a different request can never disappear into it."""
    par = {}
    def find_(x):
        while par.setdefault(x, x) != x: par[x] = par[par[x]]; x = par[x]
        return x
    def union(a, b): par[find_(a)] = find_(b)
    dem = [r for r in rows if r.get("type") == "demand" and str(r.get("need") or "").strip()]
    for r in dem:
        ks = _keys(r["need"]) + ["t:" + (r.get("ticket") or _ticket(r["need"]))]
        for k in ks[1:]: union(ks[0], k)
    done = {}
    for r in rows:
        if r.get("type") == "fulfilled" and r.get("ticket"): done[find_("t:" + r["ticket"])] = r.get("cell")
    groups = {}
    for r in dem: groups.setdefault(find_(_keys(r["need"])[0]), []).append(r)
    out = []
    for root, rs in groups.items():
        rs.sort(key=lambda r: r.get("ts", ""))
        tickets = list(dict.fromkeys(r.get("ticket") or _ticket(r["need"]) for r in rs))
        wc = {}
        for r in rs: wc.setdefault(r["need"], [0, False]); wc[r["need"]][0] += 1; wc[r["need"]][1] |= not r.get("auto")
        # the wording asked most often speaks for the group; on a tie the model's own request_cell words (no data mixed in), then the shortest
        lead = max(wc, key=lambda w: (wc[w][0], wc[w][1], -len(w)))
        nr = next((r for r in reversed(rs) if r.get("nearest") and (r.get("nearest_score") or 0) >= CLOSE_ENOUGH), None)
        cell = done.get(root)
        out.append({"ticket": _ticket(lead), "need": lead, "count": len(rs), "explicit": sum(1 for r in rs if not r.get("auto")),
                    "auto": sum(1 for r in rs if r.get("auto")), "tickets": tickets, "models": sorted({r["model"] for r in rs if r.get("model")}),
                    "callers": sorted({r["caller"] for r in rs if r.get("caller")}), "first": rs[0].get("ts"), "last": rs[-1].get("ts"),
                    "nearest": nr["nearest"] if nr else None, "nearest_score": nr["nearest_score"] if nr else 0,
                    "examples": list(dict.fromkeys(r["example"] for r in rs if r.get("example")))[:3],
                    "wordings": sorted(wc, key=lambda w: -wc[w][0])[:5],
                    "status": "ready" if cell else "open", "cell": cell})
    out.sort(key=lambda x: (x["status"] != "open", -x["count"], x["first"] or ""))
    return out
def demand_summary(include_ready=False):
    s = summarize_demand(_rows(("demand", "fulfilled"))); return s if include_ready else [g for g in s if g["status"] == "open"]
def _group_of(ticket, rows=None):
    for g in summarize_demand(_rows(("demand", "fulfilled")) if rows is None else rows):
        if ticket in g["tickets"] or ticket == g["ticket"]: return g
    return None

# ---------------------------------------------------------------- the way out: a cell-request issue the user opens
PRIVATE = [(re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[email]"),
           (re.compile(r"\b\d{6}\s*-\s*\d{7}\b"), "[id-number]"),                                 # 주민등록번호 꼴
           (re.compile(r"(?<!\d)(?:\+?82[\s-]?)?0\d{1,2}[\s.-]?\d{3,4}[\s.-]?\d{4}(?!\d)"), "[phone]"),
           (re.compile(r"(?<![\d.,])\d(?:[\s-]?\d){9,}(?![\d.,])"), "[long-number]")]            # 계좌·카드 꼴: 띄어 쓰거나 - 로 이은 10자리 이상
def mask_private(text):
    """Hide what looks like contact or ID data before anything is shown as a public issue. Amounts (3,000,000) stay: they make the example.
    Names cannot be found reliably, which is why `stemseal demand --open` shows the whole text and asks first."""
    t = str(text or "")
    for rx, sub in PRIVATE: t = rx.sub(sub, t)
    return t
def issue_text(group):
    """Title and body of the cell-request issue for one demand group, already masked. This is exactly what goes public if the user submits."""
    g = group; need = mask_private(g["need"])
    others = [mask_private(w) for w in g.get("wordings", []) if w != g["need"]]
    body = ("**What needs computing** (one or two sentences):\n%s\n\n" % need
            + ("Other wordings: %s\n\n" % " / ".join(others) if others else "")
            + "**An example input and the answer you expect**:\n%s\n\n" % ("\n".join(mask_private(e) for e in g.get("examples") or []) or "(optional)")
            + "**Rule source, if there is one**:\n\n"
            + "---\nticket: %s\nrequested: %d times on this machine%s\nmodels: %s\nclosest cell now: %s\n"
              % (" ".join(g.get("tickets") or [g["ticket"]]), g.get("count", 1), " (%d by the model itself)" % g["explicit"] if g.get("explicit") else "",
                 ", ".join(g.get("models") or []) or "-", ("%s (%.2f)" % (g["nearest"], g["nearest_score"])) if g.get("nearest") else "-"))
    title = ("cell request %s: %s" % (g["ticket"], re.sub(r"\s+", " ", need).strip()))[:120]
    return title, body[:1800]
def share_link(group):
    """A prefilled GitHub cell-request issue. Opening it is the user's choice; stemseal never sends it. The repository is public."""
    from urllib.parse import quote
    title, body = issue_text(group)
    return "%s/issues/new?labels=cell-request&title=%s&body=%s" % (REPO, quote(title), quote(body))

PROMISE = {   # short on purpose: a model pays for every token of it, on every miss
 "ko": "검증된 세포가 아직 없습니다. 요청을 기록했고({n}번째), 요청이 모이는 순서대로 만듭니다. 지금은 직접 답하되 검증되지 않은 답이라고 밝혀 주세요. 다음에 find_cell 로 다시 찾으면 세포가 있을 수 있습니다.",
 "en": "No verified cell yet. Request saved ({n} so far); cells are built as requests gather. Answer yourself for now and say it is unverified. Next time, find_cell may have it.",
}
NEAR = {"ko": "가장 가까운 세포: {cell} ({desc}). 바로 이 계산일 때만 쓰세요.",
        "en": "Closest cell: {cell} ({desc}). Use it only for exactly this calculation."}
def no_cell_reply(need, ticket=None, rows=None):
    """What a model hears when nothing fits: not a refusal but 'saved, the channel is being built, come back', plus the closest cell
    when one is worth a look. Short on purpose: every character here is a token the model pays. Records nothing by itself;
    the issue link for people lives in `stemseal demand`, not here."""
    t = ticket or _ticket(need); lang = _lang(need); n = max(1, times_requested(need, rows))
    out = {"recorded": True, "ticket": t, "message": PROMISE[lang].format(n=n)}
    c, sc = nearest(need)
    if c and sc >= CLOSE_ENOUGH:
        con = load(c)["contract"]; desc = ((con.get("description_en") if lang == "en" else None) or con["description"]).split(".")[0].split("(")[0].strip()
        out["closest_cell"] = NEAR[lang].format(cell=c, desc=desc)
    return out
def request_cell(need, caller="unknown", model=None, example=None, auto=False):
    """An AI says: I needed this and nothing fit. Recorded as demand; this is what gets differentiated next.
    example: optional, one input and the answer it expects, in any words. Returns a ticket (same calculation -> same ticket),
    how often it was asked here, and the promise, so the caller knows the channel is being built and comes back."""
    need = str(need if need is not None else "").strip()
    if not need: return {"recorded": False, "reason": "say in one sentence what you need computed (need)"}
    t = _log_demand(need, caller, model=model, auto=auto, example=example)
    return no_cell_reply(need, t)
def fulfill(ticket, cell):
    """The hub keeper marks a demand ticket as answered by a locked cell."""
    if not load(cell): return {"ok": False, "reason": "no locked cell with this name"}
    _log({"type": "fulfilled", "ticket": ticket, "cell": cell}); return {"ok": True}
def request_status(ticket):
    g = _group_of(ticket)
    if not g: return {"ticket": ticket, "status": "unknown", "times_requested": 0}
    return {"ticket": ticket, "status": "ready" if g["status"] == "ready" else "queued", "cell": g["cell"], "times_requested": g["count"]}

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
