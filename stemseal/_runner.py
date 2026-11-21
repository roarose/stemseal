# -*- coding: utf-8 -*-
"""stemseal - cell runner. Started by hub.run_isolated as a separate Python process:
    python -I -S -B -X utf8 <this file>          (working directory: a new empty temporary folder)
It reads one JSON request on stdin and writes one JSON reply on stdout.
    request: {"mode": "run" | "check", "src": <cell source>, "sha256": <its hash>, "inputs": [<input>, ...]}
    reply:   {"results": [{"ok": bool, "out": ..., "err": str}, ...], "blocked": null | "<why>", "problems": [...]}

Order (each step finishes before the next starts):
  1. load policy.py from this file's own folder, by its path
  2. read the request; the source must match its hash and pass policy.check
  3. load only the allowed modules the cell imports (and their HIDDEN_DEPS)
  4. compile the cell, give it a namespace whose built-ins are the policy's list
  5. install the audit hook: from here on the only event allowed is the one exec of the compiled cell
  6. run cell_executor on each input, write the reply, exit
"""
import sys, os, json, hashlib
import importlib.util

MAX_REQUEST = 8 * 1024 * 1024
MAX_RESULT = 1024 * 1024
RESULT_NOT_JSON = "result is not plain JSON"

def load_policy():
    here = os.path.dirname(os.path.realpath(__file__))
    spec = importlib.util.spec_from_file_location("stemseal_policy", os.path.join(here, "policy.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def _reply(results, blocked=None, problems=None):
    return {"results": results, "blocked": blocked, "problems": problems or []}

def _fail_all(n, err, blocked):
    return _reply([{"ok": False, "err": err} for _ in range(max(1, n))], blocked)

def prepare(policy, src, enforce_policy=True):
    """Steps 2-4 for a source string. Returns (code, namespace, problems). enforce_policy=False exists only for the
    test suite, which calls this function directly to exercise the audit hook on its own; the stdin request cannot reach it."""
    problems = [policy.describe(p) for p in policy.check(src)] if enforce_policy else []
    if problems: return None, None, problems
    import builtins as _b
    mods = {}
    for m in policy.imports_of(src) if enforce_policy else list(policy.MODULES):
        for dep in policy.HIDDEN_DEPS.get(m, ()): __import__(dep)
        mods[m] = __import__(m)
    allowed_from = {m: policy.MODULES[m] for m in mods}
    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name not in mods: raise ImportError("module %s is not available to cells" % name)
        for f in fromlist or ():
            if f not in allowed_from[name]: raise ImportError("%s.%s is not available to cells" % (name, f))
        return mods[name]
    safe = {k: getattr(_b, k) for k in policy.BUILTINS if hasattr(_b, k)}
    safe["__build_class__"] = _b.__build_class__
    safe["__import__"] = safe_import
    code = compile(src, "cell.py", "exec")
    return code, {"__name__": "cell", "__builtins__": safe}, []

def guard(code):
    """Step 5. The hook allows exactly one event, the exec of `code`; everything else is refused and remembered."""
    state = [False, None]          # [exec used, first refused event]
    def hook(event, args):
        if event == "exec" and not state[0] and args and args[0] is code:
            state[0] = True
            return
        if state[1] is None: state[1] = event
        raise RuntimeError("blocked: %s" % event)
    sys.addaudithook(hook)
    return state

def execute(code, ns, inputs, state):
    """Step 6. Results per input; if any event was refused, every result fails (a cell cannot hide one by catching it)."""
    out = []
    try:
        exec(code, ns)
        fn = ns.get("cell_executor")
        if not callable(fn): raise ValueError("no cell_executor")
    except Exception as e:
        out = [{"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:200])} for _ in inputs]
        fn = None
    if fn is not None:
        for x in inputs:
            try:
                r = fn(x)
                if not isinstance(r, dict): out.append({"ok": False, "err": "result is not an object"}); continue
                try: text = json.dumps(r, ensure_ascii=False)
                except (TypeError, ValueError, RecursionError): out.append({"ok": False, "err": RESULT_NOT_JSON}); continue
                if len(text) > MAX_RESULT: out.append({"ok": False, "err": "result too large"}); continue
                out.append({"ok": True, "out": json.loads(text)})   # what is sent is exactly what was measured
            except Exception as e:
                out.append({"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:200])})
    if state[1] is not None:
        return _fail_all(len(inputs), "blocked: %s" % state[1], "event:%s" % state[1])
    return _reply(out)

def serve(raw, policy):
    try:
        if len(raw) > MAX_REQUEST: return _fail_all(1, "request too large", "request")
        req = json.loads(raw.decode("utf-8"))
        src, inputs, mode = req["src"], req.get("inputs") or [], req.get("mode", "run")
        if not isinstance(src, str) or not isinstance(inputs, list) or mode not in ("run", "check"): raise ValueError("bad request")
    except Exception:
        return _fail_all(1, "bad request", "request")
    if hashlib.sha256(src.encode("utf-8")).hexdigest() != req.get("sha256"):
        return _fail_all(len(inputs), "source does not match its hash", "hash")
    if mode == "check":
        problems = [policy.describe(p) for p in policy.check(src)]
        if not problems:
            try: compile(src, "cell.py", "exec")
            except Exception as e: problems = ["compile: %s" % type(e).__name__]
        return _reply([], None, problems)
    try: code, ns, problems = prepare(policy, src)
    except Exception as e: code, ns, problems = None, None, ["prepare: %s" % type(e).__name__]
    if problems:
        r = _fail_all(len(inputs), "blocked: policy", "policy"); r["problems"] = problems; return r
    state = guard(code)
    return execute(code, ns, inputs, state)

def main():
    policy = load_policy()
    raw = sys.stdin.buffer.read(MAX_REQUEST + 1)
    reply = serve(raw, policy)
    sys.stdout.write(json.dumps(reply, ensure_ascii=False))
    sys.stdout.flush()
    os._exit(3 if reply.get("blocked") else 0)

if __name__ == "__main__":
    main()
