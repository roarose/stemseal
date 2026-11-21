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
import hashlib, json, os, re, shutil, sys, tempfile, time
from datetime import datetime, timedelta, timezone
from . import savings, policy, limits, seal, shape

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
STATE = os.path.join(HOME, "state.json")    # this machine's record of cell versions it has held with a format 2 lock
REPO = "https://github.com/roarose/stemseal"
MIN_GT = 20                      # a cell needs at least this many ground-truth cases to be locked
CALL_TIMEOUT = 5                 # seconds per call
ALLOWED_IMPORTS = set(policy.MODULES)   # what a cell may contain is defined in policy.py
LIMITS_FAILED = "cannot apply limits"
def _interpreter():
    """The interpreter that runs cells. On Windows, python.exe in a virtual environment (venv, uvx) only starts the base
    interpreter as a second process, which the one-process limit would end; the runner needs no packages, so it starts
    the base interpreter directly."""
    if os.name == "nt":
        base = getattr(sys, "_base_executable", None)
        if base and os.path.isfile(base): return base
    return sys.executable
PYTHON = _interpreter()
RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_runner.py")

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def sha(b): return hashlib.sha256(b if isinstance(b, bytes) else b.encode("utf-8")).hexdigest()
LOG_MODES = ("full", "minimal", "off")
def log_mode():
    """STEMSEAL_LOG: full (default) keeps request sentences; minimal keeps, instead of a sentence, its hash and at most
    MIN_WORDS calculation words found in it (see _calc_words); off writes no ledger at all."""
    v = (os.environ.get("STEMSEAL_LOG") or "full").strip().lower()
    return v if v in LOG_MODES else "full"
MIN_WORDS = 4
CALC_TERMS = set("""이자 대출 원리금 상환 복리 단리 적금 예금 금리 할부 할인 세금 부가세 소득세 수수료 환율 환전 평균 비율 퍼센트 백분율 합계 총액 가격 요금
단가 원가 마진 이익 매출 시간 날짜 기간 요일 나이 칼로리 무게 거리 속도 면적 부피 넓이 월급 시급 연봉 일급 주휴수당 퇴직금 보험 연금 배송비 택배비
주문 메뉴 인분 세트 영업시간 마감 예약 bmi 체질량 성장률 증가율 감소율 반올림 단위 변환 환산 개수 수량 나누기 더치페이 팁
loan interest tax fee discount average rate price total cost margin profit wage salary hourly monthly yearly age date time days hours
distance speed weight area volume calories currency exchange percent percentage growth tip split order menu""".split())
_VOCAB = None
def _calc_words(text, n=MIN_WORDS):
    """At most n calculation words found in the text, each given as the known word (a cell card's word or CALC_TERMS), never
    as the text's own spelling: a word of the text counts when it starts with a known word ('이자를' -> '이자')."""
    global _VOCAB
    if _VOCAB is None:
        _VOCAB = sorted(CALC_TERMS, key=len, reverse=True)      # in place while the cell cards are read
        v = set(CALC_TERMS)
        try:
            for c in list_cells(): v |= {w for w in _doc_words(c["cell"]) if len(w) >= 2}
        except Exception: pass
        _VOCAB = sorted(v, key=len, reverse=True)
    out = []
    for w in _words(text):
        hit = next((t for t in _VOCAB if w.startswith(t)), None)
        if hit and hit not in out: out.append(hit)
        if len(out) >= n: break
    return out
def _minimal(rec):
    """A ledger row in minimal mode: a request sentence becomes need_sha + a few calculation words, a model's search words
    are kept only as calculation words, examples are not kept, and a cell's error keeps only its exception type."""
    rec = dict(rec)
    if "need" in rec:
        need = str(rec.pop("need") or "")
        rec["need_sha"] = sha(need)[:16]; rec["need_words"] = _calc_words(need)
    if isinstance(rec.get("words"), list): rec["words"] = _calc_words(" ".join(str(w) for w in rec["words"]))
    rec.pop("example", None)
    if isinstance(rec.get("reason"), str) and rec["reason"].startswith(REJECTED):
        rec["reason"] = REJECTED + rec["reason"][len(REJECTED):].split(":")[0][:40]
    return rec
def ledger_has_text():
    """True when the ledger files still hold rows that minimal mode would not keep as they are (written before the switch)."""
    for path in (LEDGER, os.path.join(os.path.dirname(LEDGER), "ledger.1.jsonl")):
        for r in _rows(path=path, raw=True):
            if _minimal(r) != r: return True
    return False
def minimize_ledger():
    """Rewrite the ledger files as minimal mode would have written them. Run by the user (stemseal ledger --minimize);
    nothing does it on its own. Returns how many rows changed."""
    changed = 0
    for path in (LEDGER, os.path.join(os.path.dirname(LEDGER), "ledger.1.jsonl")):
        if not os.path.exists(path): continue
        rows = _rows(path=path, raw=True); new = [_minimal(r) for r in rows]
        changed += sum(a != b for a, b in zip(rows, new))
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".ledger_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f: f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in new)
        os.replace(tmp, path)
    return changed
def _log(rec):
    """Logging must never break a call: if the log folder cannot be written, the answer still goes back."""
    try:
        mode = log_mode()
        if mode == "off": return
        if mode == "minimal": rec = _minimal(rec)
        os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
        rec = {"ts": now(), **rec}
        with open(LEDGER, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception: pass

# ---------------------------------------------------------------- gate 1: policy (what a cell may contain, see policy.py)
def purity_check(src):
    """The policy gate. Returns a list of problems (empty = allowed). The source is parsed only inside a runner process."""
    return policy_check_isolated(src.encode("utf-8") if isinstance(src, str) else src)

def policy_check_isolated(src_bytes):
    pre = policy.precheck(src_bytes)
    if pre: return [policy.describe(p) for p in pre]
    rep = read_reply(_run_runner({"mode": "check", "src": bytes(src_bytes).decode("utf-8"), "sha256": sha(bytes(src_bytes)), "inputs": []}, CALL_TIMEOUT), "check")
    if not rep["complete"]: return [LIMITS_FAILED] if rep["why"] == "limits" else ["checker did not finish (E_INTERNAL: %s)" % rep["why"]]
    if rep["blocked"]: return ["checker refused the request (%s)" % rep["blocked"]]
    return rep["problems"]

# ---------------------------------------------------------------- isolated execution
def _run_runner(request, timeout):
    """Start the runner in a new empty folder under the limits in limits.py and send one request.
    Returns (exit code, stdout bytes), ("timeout", b"") or ("limits", b"") when the limits could not be applied (nothing ran)."""
    env = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
    work = tempfile.mkdtemp(prefix="stemseal_run_")
    try:
        code, out, _ = limits.run([PYTHON, "-I", "-S", "-B", "-X", "utf8", RUNNER],
                                  json.dumps(request, ensure_ascii=False).encode("utf-8"), timeout, cwd=work, env=env)
    except limits.Timeout:
        return "timeout", b""
    except limits.LimitError:
        return "limits", b""
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return code, out

def read_reply(proc, mode, n=0):
    """The one place a runner's answer is read, for every path (call, verify, register, update). A reply is trusted only when it
    is complete and in the exact form the runner writes; anything else (timeout, other exit code, empty or broken output,
    unexpected shape) is returned as {"complete": False, "why": ...}, which every caller treats as not passed.
    Complete: {"complete": True, "blocked": None | str, "problems": [str], "results": [{"ok": True, "out": {...}} | {"ok": False, "err": str}]}."""
    def bad(why): return {"complete": False, "why": why}
    code, out = proc
    if code in ("timeout", "limits"): return bad(code)
    if code not in (0, 3): return bad("exit %s" % code)
    try: rep = json.loads(out.decode("utf-8"))
    except Exception: return bad("no reply" if not out else "broken reply")
    if not isinstance(rep, dict) or set(rep) != {"results", "blocked", "problems"}: return bad("unexpected reply")
    blocked, problems, results = rep["blocked"], rep["problems"], rep["results"]
    if not (blocked is None or (isinstance(blocked, str) and blocked)): return bad("unexpected reply")
    if not (isinstance(problems, list) and all(isinstance(x, str) for x in problems)): return bad("unexpected reply")
    if not isinstance(results, list): return bad("unexpected reply")
    if (code == 3) != (blocked is not None): return bad("exit %s" % code)
    if blocked: return {"complete": True, "blocked": blocked, "problems": problems, "results": []}
    if mode == "check":
        if results: return bad("unexpected reply")
        return {"complete": True, "blocked": None, "problems": problems, "results": []}
    if problems or len(results) != n: return bad("unexpected reply")
    for r in results:
        if not isinstance(r, dict) or not isinstance(r.get("ok"), bool): return bad("unexpected reply")
        if r["ok"] and not (set(r) == {"ok", "out"} and isinstance(r["out"], dict)): return bad("unexpected reply")
        if not r["ok"] and not (set(r) == {"ok", "err"} and isinstance(r["err"], str)): return bad("unexpected reply")
    return {"complete": True, "blocked": None, "problems": [], "results": results}

def run_isolated(src, sha256, inputs, timeout=None):
    """Run cell_executor on a list of inputs in a separate Python process (see _runner.py: policy check, cell-only built-ins,
    audit hook). src is the source text whose hash the caller checked; the runner checks it again before running it.
    Returns a list of {"ok": bool, "out": ..., "err": str}. When the runner refused the cell, each item also has "blocked";
    when its answer could not be trusted (read_reply), each item has "fault"."""
    rep = read_reply(_run_runner({"mode": "run", "src": src, "sha256": sha256, "inputs": inputs}, timeout or CALL_TIMEOUT * max(1, len(inputs) // 5 + 1)),
                     "run", len(inputs))
    if not rep["complete"]:
        err = {"timeout": "timeout", "limits": LIMITS_FAILED}.get(rep["why"]) or "runner gave no proper answer (%s)" % rep["why"]
        return [{"ok": False, "err": err, "fault": True} for _ in inputs]
    if rep["blocked"]: return [{"ok": False, "err": "blocked: %s" % rep["blocked"], "blocked": rep["blocked"]} for _ in inputs]
    return rep["results"]

# ---------------------------------------------------------------- gate 2: ground truth
def _refused_as_expected(case, r):
    """A refusal case passes only on the cell's own refusal: a non-empty expected text, found in an error the cell raised."""
    want = case.get("expected_error")
    return (isinstance(want, str) and bool(want) and r.get("ok") is False and not r.get("blocked") and not r.get("fault")
            and want in str(r.get("err")))

def gt_check(src, gt_cases, schema=None):
    """src: the cell source text (not a path). schema: the contract's output_schema, if any; an answer must also fit it (shape.py)."""
    h = sha(src)
    res = run_isolated(src, h, [c["input"] for c in gt_cases])
    # a case may say the cell must refuse: {"input": ..., "expected_error": "text the refusal must contain"} (ambiguous input is refused, not guessed)
    good = lambda c, r: _refused_as_expected(c, r) if "expected_error" in c else (r.get("ok") is True and r.get("out") == c["expected"] and shape.problem(r["out"], schema) is None)
    fails = [{"case": i, "expected": c.get("expected", {"error": c.get("expected_error")}), "got": r.get("out"), "err": r.get("err")} for i, (c, r) in enumerate(zip(gt_cases, res)) if not good(c, r)]
    # determinism: second run must give byte-identical outputs
    res2 = run_isolated(src, h, [c["input"] for c in gt_cases])
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
def _json(b):
    try: return json.loads(b.decode("utf-8")) if b is not None else None
    except ValueError: return None
def inspect(name, version=None):
    """A cell as found on disk, whether or not its lock holds: {"dir", "version", "contract", "lock", "seal"}.
    seal is None when the lock is format 2 and contract.json matches it (the contract is parsed from the bytes that were hashed);
    otherwise seal.OLD or the name of the file that does not match."""
    d = cell_dir(name, version)
    if not d: return None
    v = os.path.basename(d); lock = _json(seal.read_bytes(d, "lock.json")); raw = seal.read_bytes(d, "contract.json")
    problem = seal.problem(lock, {"contract.json": raw}, name, v)
    if problem == seal.OLD and was_sealed(name, v): problem = "lock.json"    # held here with a format 2 lock before
    contract = _json(raw)
    if problem is None and not (isinstance(contract, dict) and isinstance(contract.get("description"), str) and isinstance(contract.get("input_schema"), dict)):
        problem = "contract.json"
    return {"dir": d, "version": v, "contract": contract if isinstance(contract, dict) else {}, "lock": lock if isinstance(lock, dict) else {}, "seal": problem}
def load(name, version=None):
    """A cell whose lock holds (see inspect), or None."""
    c = inspect(name, version)
    return c if c and c["seal"] is None else None
def exists(name): return bool(isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9_]{2,63}", name) and cell_dir(name))
def _names(): return sorted({n for b in _dirs() if os.path.isdir(b) for n in os.listdir(b) if os.path.isdir(os.path.join(b, n))})
_TAMPER_SEEN = set()
def _tamper(name, version, file, once=False):
    if once:
        if (name, version, file) in _TAMPER_SEEN: return
        _TAMPER_SEEN.add((name, version, file))
    _log({"type": "tamper", "cell": name, "version": version, "file": file})
def _sealed():
    """(name, cell) for every cell whose newest version's lock holds. A cell whose files do not match is left out and recorded once."""
    for name in _names():
        c = inspect(name)
        if not c: continue
        if c["seal"] is None: yield name, c
        elif c["seal"] != seal.OLD: _tamper(name, c["version"], c["seal"], once=True)
def list_cells():
    out = []
    for name, c in _sealed():
        out.append({"cell": name, "version": c["lock"]["version"], "description": c["contract"]["description"], "when_to_use": c["contract"].get("when_to_use", ""),
                    "description_en": c["contract"].get("description_en", ""), "when_to_use_en": c["contract"].get("when_to_use_en", ""),
                    "required_inputs": c["contract"]["input_schema"].get("required", []), "gt_cases": c["lock"]["gt_total"], "locked_at": c["lock"]["locked_at"]})
    return out
def _state():
    try:
        with open(STATE, encoding="utf-8") as f: s = json.load(f)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError): return {}
def mark_sealed(name, version, sha256):
    """Record that this machine holds name/version with a format 2 lock (kept outside the cell folder, in state.json).
    Such a version is never taken for a format 1 cell again: reseal refuses it and its use is refused."""
    try:
        s = _state(); rec = s.get("sealed") if isinstance(s.get("sealed"), dict) else {}
        rec["%s/%s" % (name, version)] = sha256; s["sealed"] = rec
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(STATE), prefix=".state_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(s, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE)
    except Exception: pass
def was_sealed(name, version):
    s = _state().get("sealed")
    return isinstance(s, dict) and "%s/%s" % (name, version) in s
def _from_update(name, version, lock):
    """True when this machine's ledger says `stemseal update` installed this very cell file."""
    return any(r.get("cell") == name and r.get("version") == version and r.get("sha256") == lock.get("sha256") for r in _rows("update"))
def old_lock_text(name, version, lock, short=False):
    """What to tell about a cell with a format 1 lock: short for a model, the full step for a person."""
    if _from_update(name, version, lock): return "old lock format; run stemseal update"
    return "cell needs re-sealing on this machine" if short else "old lock format. If you made this cell yourself, run: stemseal reseal %s" % name
def unsealed():
    """[{"cell", "version", "why"}] for every cell whose newest version cannot be used because of its lock, for people (list, verify)."""
    out = []
    for name in _names():
        c = inspect(name)
        if c and c["seal"] is not None:
            why = old_lock_text(name, c["version"], c["lock"]) if c["seal"] == seal.OLD else "cell files do not match the lock (%s)" % c["seal"]
            out.append({"cell": name, "version": c["version"], "why": why})
    return out

def register(name, src, contract, gt_cases, locked_by="unknown", base=None):
    """The only way a cell enters the hub: purity gate, then ground-truth gate, then lock. Returns a report; report['locked'] says if it got in.
    A locked version is never overwritten. A change is a new version."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", name): return {"locked": False, "reason": "bad name"}
    for k in ("description", "input_schema", "output_keys"):
        if k not in contract: return {"locked": False, "reason": "contract missing %s" % k}
    if len(gt_cases) < MIN_GT: return {"locked": False, "reason": "needs at least %d ground-truth cases, got %d" % (MIN_GT, len(gt_cases))}
    schema = contract.get("output_schema")
    if schema is not None:
        bad = shape.schema_problem(schema, contract["output_keys"])
        if bad: return {"locked": False, "reason": bad}
    problems = purity_check(src)
    if problems: return {"locked": False, "reason": "purity gate", "problems": problems}
    vs = _versions(name); version = "%d.0" % (int(vs[-1].split(".")[0]) + 1) if vs else "1.0"
    d = os.path.join(os.path.abspath(base or CELLS), name, version); os.makedirs(d, exist_ok=True)
    cp = os.path.join(d, "cell.py"); open(cp, "w", encoding="utf-8", newline="\n").write(src)
    rep = gt_check(src, gt_cases, schema)
    if rep["passed"] != rep["total"] or not rep["deterministic"]:
        os.remove(cp); 
        try: os.rmdir(d)
        except OSError: pass
        return {"locked": False, "reason": "ground-truth gate", "report": rep}
    raw = {"cell.py": src.encode("utf-8"), "contract.json": json.dumps(contract, ensure_ascii=False, indent=1).encode("utf-8"),
           "gt_cases.json": json.dumps(gt_cases, ensure_ascii=False).encode("utf-8")}
    for f in ("contract.json", "gt_cases.json"):
        with open(os.path.join(d, f), "wb") as fh: fh.write(raw[f])
    lock = seal.build(name, version, raw, policy.POLICY_VERSION, rep["total"], rep["passed"], now(), locked_by)
    seal.write(d, lock); mark_sealed(name, version, lock["sha256"])
    _log({"type": "lock", "cell": name, "version": version, "sha256": lock["sha256"], "gt": rep["total"], "by": locked_by})
    return {"locked": True, "cell": name, "version": version, "sha256": lock["sha256"], "report": rep}

def input_help(c):
    """What a caller needs to retry a refused call: the exact input keys, what each means, and a template to fill (no example numbers: small models copy them)."""
    sch = c["contract"]["input_schema"]; h = {"required_inputs": sch.get("required", []), "inputs": sch.get("properties", {}),
        "note": "Call call_cell again with exactly these keys in `input`. Optional inputs can be left out."}
    h["input_template"] = {k: "<%s, from the user's question>" % sch.get("properties", {}).get(k, "number") for k in h["required_inputs"]}
    return h

# ---------------------------------------------------------------- the membrane: call
ERR_TO_MODEL = 200     # characters of a cell's error message the model sees (the runner already sends no more)
ERR_TO_LEDGER = 60     # characters of it (after the exception type) the ledger keeps in full mode; minimal keeps the type only
REJECTED = "cell rejected the input: "
def _one_line(text): return re.sub(r"\s+", " ", str(text or "")).strip()
def _cut(text, n):
    """text if it fits in n characters; otherwise cut at the last word boundary before n, marked with '…'."""
    if len(text) <= n: return text
    head = text[:n]; sp = head.rfind(" ")
    return (head[:sp] if sp > n // 2 else head).rstrip() + "…"
def _err_for_model(err):
    """The cell's error as the runner sent it: put on one line only when it has line breaks, cut (at a word) only past ERR_TO_MODEL."""
    err = str(err or "")
    if "\n" in err or "\r" in err: err = _one_line(err)
    kind, sep, msg = err.partition(": ")
    return kind + sep + _cut(msg, ERR_TO_MODEL) if sep else _cut(err, ERR_TO_MODEL)
RESULT_FORM = ("result is not an object", "result too large", "result is not plain JSON")   # the runner's words for a result it could not pass on
def _err_for_ledger(err):
    """The exception type and the first characters of its message only."""
    kind, sep, msg = err.partition(": ")
    return (kind + sep + msg[:ERR_TO_LEDGER]) if sep else err[:ERR_TO_LEDGER]
def call(name, input_data, caller="unknown", version=None, model=None, decorate=None, log=True):
    """status = ok | not_available | invalid_input. A result only ever comes from a locked, untampered cell.
    Every call row carries its token meter (savings.py): what the call cost and, against the cell's baseline, what it saved.
    model: the calling model's name, when known (baselines are per model). decorate(out): lets a wrapper add its fields
    before the reply is measured, so the meter counts the reply the model actually reads."""
    t0 = time.time()
    def env(status, result=None, reason=None, ver=None, log_reason=None):
        rec = {"type": "call", "cell": name, "version": ver, "status": status, "caller": caller, "ms": round((time.time() - t0) * 1000, 1),
               "input_sha": sha(json.dumps(input_data, sort_keys=True, ensure_ascii=False))[:16] if isinstance(input_data, dict) else None,
               "reason": reason if log_reason is None else log_reason}
        if status != "ok" and isinstance(input_data, dict):
            keys = sorted(str(k) for k in input_data)        # names only, never values
            if log_mode() == "minimal":                      # minimal: only names the cell's contract declares, others counted
                sch = c["contract"].get("input_schema", {}) if c else {}
                declared = set(sch.get("properties", {})) | set(sch.get("required", [])) if isinstance(sch, dict) else set()
                kept = [k for k in keys if k in declared]
                if len(kept) < len(keys): rec["input_other"] = len(keys) - len(kept)
                keys = kept
            rec["input_keys"] = keys[:12]
        out = {"status": status, "cell": name, "version": ver, "verified": status == "ok", "result": result, "reason": reason}
        if status == "invalid_input" and c: out["how_to_fix"] = input_help(c)
        if decorate: decorate(out)
        rec["model"] = model
        try: rec["tokens"] = savings.meter(name, ver, model, {"cell": name, "input": input_data}, out, status == "ok")
        except Exception: pass   # the meter must never break a call
        if log: _log(rec)
        return out
    c = inspect(name, version) if exists(name) else None
    if not c: return env("not_available", reason="no locked cell with this name")
    ver = c["version"]
    raw = seal.read_bytes(c["dir"], "cell.py")   # read once: the bytes whose hash is checked are the bytes that run
    problem = c["seal"] or seal.problem(c["lock"], {"cell.py": raw}, name, ver) or (None if seal.kind(c["lock"]) == "cell" else "lock.json")
    if problem == seal.OLD:
        lock, c = c["lock"], None
        return env("not_available", reason=old_lock_text(name, ver, lock, short=True), ver=ver)
    if problem:
        c = None
        if log: _tamper(name, ver, problem)
        return env("not_available", reason="cell files do not match the lock (%s)" % problem, ver=ver)
    if not isinstance(input_data, dict): return env("invalid_input", reason="input must be an object", ver=ver)
    missing = [k for k in c["contract"]["input_schema"].get("required", []) if k not in input_data]
    if missing: return env("invalid_input", reason="missing required inputs: %s" % missing, ver=ver)
    r = run_isolated(raw.decode("utf-8"), c["lock"]["sha256"], [input_data])[0]
    if r.get("err") == LIMITS_FAILED: return env("not_available", reason="cannot apply limits on this machine", ver=ver)
    if r.get("blocked"):
        if log: _log({"type": "blocked", "cell": name, "version": ver, "why": r["blocked"]})
        return env("not_available", reason="cell failed the safety check", ver=ver)
    if r.get("fault") and r.get("err") != "timeout": return env("not_available", reason="the cell gave no proper answer", ver=ver)
    if not r.get("ok") and r.get("err") in RESULT_FORM:     # the cell answered, but not with a plain JSON object of bounded size
        return env("not_available", reason="cell returned an unexpected result", ver=ver, log_reason="cell returned an unexpected result: %s" % r["err"])
    if not r.get("ok"):
        err = _err_for_model(r.get("err"))
        return env("invalid_input", reason=REJECTED + err, ver=ver, log_reason=REJECTED + _err_for_ledger(_one_line(err)))
    bad = shape.problem(r["out"], c["contract"].get("output_schema"))
    if bad: return env("not_available", reason="cell returned an unexpected result", ver=ver, log_reason="cell returned an unexpected result: %s" % bad[:ERR_TO_LEDGER])
    return env("ok", result=r["out"], ver=ver)

# ---------------------------------------------------------------- find (how an AI picks)
# A number followed by one of these is a quantity in the request (data): "4500원", "2잔", "10%", "3년". Dropped from search.
_UNIT_WORDS = set("원 만원 천원 억 억원 만 천 잔 개 명 인 인분 분 초 시 시간 일 주 월 년 개월 주년 회 번 번째 년차 차 층 호 살 세 그릇 공기 병 캔 장 판 마리 세트 컵 점 등 위 배수 퍼센트 프로 kg g mg l ml km m cm mm".split())
def _token(t):
    """A word with a number in it. Number + unit ("4500원", "2잔", "3년차") is data and goes; number + a word that names something
    ("1인당", "2배", "4대보험") keeps the word, because it says what is being calculated."""
    if not any(ch.isdigit() for ch in t): return t
    m = re.fullmatch(r"[0-9.]+([a-z가-힣]*)", t)
    if not m or not m.group(1) or m.group(1) in _UNIT_WORDS: return None
    return m.group(1)
def _grams(s):
    """Words and their 2-letter pieces. Bare numbers and number+unit are dropped: numbers in a request are data (10030, 3.2, 4500원),
    and their pieces only dilute the score of the words that name the calculation."""
    s = re.sub(r"[^0-9a-z가-힣.%]+", " ", (s or "").lower()).replace("%", " ")
    toks = [w for w in (_token(t.strip(".")) for t in s.split()) if w]; g = set(toks)
    for t in toks: g.update(t[i:i + 2] for i in range(len(t) - 1))
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
def _is_part(card):
    c = load(card["cell"]); return bool(c and c["contract"].get("part"))
def find(need, caller="unknown", k=3, min_score=0.3, words=None, model=None, record=True):
    """Return up to k locked cells that fit the stated need, best first. An empty list is an honest 'nothing fits', and the need
    is recorded as demand right there (auto=True), so demand gathers even when the model never calls request_cell.
    words: the caller's own short names for the calculation (e.g. "연평균 성장률"). They are searched on their own and the two result lists
    are taken in turn (request, words, request, ...), so a request worded unlike any cell card can still reach its cell (exp8).
    Part cells (contract "part": true) are listed after the whole-job cells.
    record=False: an internal probe (e.g. after a guessed cell name), whose caller records the demand itself."""
    need = need if isinstance(need, str) else ("" if need is None else json.dumps(need, ensure_ascii=False))
    a = _rank(need, min_score); b = _rank(" ".join(str(w) for w in words), min_score) if words else []
    hits = []; seen = set()
    for i in range(max(len(a), len(b))):
        for lst in (a, b):
            if i < len(lst) and lst[i][1]["cell"] not in seen: seen.add(lst[i][1]["cell"]); hits.append(dict(lst[i][1], score=lst[i][0]))
    # a part cell (contract "part": true, one step of a job) comes after every whole-job cell that fits, so a small model's first
    # candidates stay what they were; parts only fill the slots left over
    hits = sorted(hits, key=_is_part)[:k]
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
def _rows(kind=None, path=None, raw=False):
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
            if isinstance(r, dict) and (not kinds or r.get("type") in kinds):
                if not raw and "need" not in r and isinstance(r.get("need_words"), list): r["need"] = " ".join(str(w) for w in r["need_words"])
                out.append(r)
    return out
KEEP_DAYS = 90                      # ledger rows older than this move to ledger.1.jsonl
MAX_LEDGER = 20 * 1024 * 1024       # past this size the oldest rows move too, down to half of it
KEEP_TYPES = ("lock", "update", "fulfilled")   # records of what was installed and answered: kept at any age
def tidy_ledger(today=None):
    """Run once when the MCP server starts. Rows older than KEEP_DAYS, and the oldest rows while the file is over MAX_LEDGER,
    move to ledger.1.jsonl, which replaces the previous one. Returns how many rows moved. Never raises."""
    try:
        d = os.path.dirname(LEDGER)
        for left in (n for n in os.listdir(d) if n.startswith(".ledger_") and n.endswith(".tmp")) if os.path.isdir(d) else ():
            try: os.remove(os.path.join(d, left))     # left by a tidy that did not finish
            except OSError: pass
        if not os.path.exists(LEDGER): return 0
        size = os.path.getsize(LEDGER)
        cut = (today or datetime.now(timezone.utc)) - timedelta(days=KEEP_DAYS)
        def old(line):
            try: return datetime.fromisoformat(json.loads(line)["ts"]) < cut
            except Exception: return False
        with open(LEDGER, encoding="utf-8", errors="replace") as f: first = f.readline()
        if size <= MAX_LEDGER and not old(first): return 0      # rows are appended in time order: nothing is old yet
        with open(LEDGER, encoding="utf-8", errors="replace") as f: lines = [l for l in f if l.strip()]
        keep, move = [], []
        for l in lines:
            if old(l) and not any('"type": "%s"' % t in l for t in KEEP_TYPES): move.append(l)
            else: keep.append(l)
        total = sum(len(l.encode("utf-8")) for l in keep)
        if total > MAX_LEDGER:
            i = 0
            while i < len(keep) and total > MAX_LEDGER // 2:
                if not any('"type": "%s"' % t in keep[i] for t in KEEP_TYPES):
                    total -= len(keep[i].encode("utf-8")); move.append(keep.pop(i))
                else: i += 1
        if not move: return 0
        d = os.path.dirname(LEDGER); old_path = os.path.join(d, "ledger.1.jsonl")
        for path, rows in ((old_path, move), (LEDGER, keep)):
            fd, tmp = tempfile.mkstemp(dir=d, prefix=".ledger_", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f: f.writelines(rows)
            os.replace(tmp, path)
        return len(move)
    except Exception: return 0
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
    rows = _rows()
    calls = [r for r in rows if r.get("type") == "call" and r.get("cell")]; per = {}
    for r in calls:
        p = per.setdefault(r["cell"], {"calls": 0, "ok": 0, "ms": 0.0, "callers": set()})
        p["calls"] += 1; p["ok"] += r.get("status") == "ok"; p["ms"] += r.get("ms") or 0; p["callers"].add(str(r.get("caller")))
    demand = {}
    for r in rows:
        if r.get("type") == "demand" and r.get("need"): demand[r["need"]] = demand.get(r["need"], 0) + 1
    return {"cells_locked": len(list_cells()), "calls": len(calls), "ok": sum(r.get("status") == "ok" for r in calls), "refused": sum(r.get("status") != "ok" for r in calls),
            "distinct_callers": len({str(r.get("caller")) for r in calls}), "finds": sum(r.get("type") == "find" for r in rows),
            "per_cell": {k: {"calls": v["calls"], "ok": v["ok"], "avg_ms": round(v["ms"] / v["calls"], 1), "callers": sorted(v["callers"])} for k, v in sorted(per.items(), key=lambda x: -x[1]["calls"])},
            "unmet_demand": sorted(demand.items(), key=lambda x: -x[1])[:20]}

def verify_all():
    """Every cell's newest version: its lock and every file the lock lists, the checker, and its ground-truth cases."""
    out = {}
    for name in _names():
        c = inspect(name)
        if not c: continue
        L = c["lock"]; raw = seal.read_bytes(c["dir"], "cell.py") or b""
        problem = seal.problem_all(L, c["dir"], name, c["version"])
        r = out[name] = {"version": c["version"], "hash_ok": sha(raw) == L.get("sha256"), "seal_ok": problem is None}
        if problem: r["seal"] = old_lock_text(name, c["version"], L) if problem == seal.OLD else "cell files do not match the lock (%s)" % problem
        schema = c["contract"].get("output_schema")
        bad = shape.schema_problem(schema, c["contract"].get("output_keys")) if schema is not None else None
        if bad: r["schema"] = bad
        problems = purity_check(raw)
        try:
            with open(os.path.join(c["dir"], "gt_cases.json"), encoding="utf-8") as f: rep = gt_check(raw.decode("utf-8"), json.load(f), schema if not bad else None)
        except (OSError, ValueError): rep = {"total": 0, "passed": 0, "deterministic": False}
        r.update({"policy_ok": not problems and not bad, "gt": "%d/%d" % (rep["passed"], rep["total"]),
                  "gt_ok": rep["total"] >= MIN_GT and rep["passed"] == rep["total"], "deterministic": rep["deterministic"]})
        if problems: r["problems"] = problems[:5]
    return out
