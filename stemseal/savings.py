# -*- coding: utf-8 -*-
"""stemseal - token meter. Always on: every cell call records what it cost and what it saved.

Kept only on this machine, in the same ledger as every other record (~/.stemseal/ledger.jsonl). Nothing is sent.

Per call (the `tokens` object on a type="call" row, format "meter/1"):
  cost      tokens this call put through the model: the call it wrote (cell name + input) plus the reply it read.
            Estimated from the text (method "chars_v1"): stemseal never sees the model's tokenizer.
  baseline  tokens the model spends doing the same job without the cell, from the cell's baseline file.
  saved     baseline - cost. Negative is written as negative. A refused call saved nothing: baseline 0, saved = -cost.
  kind      measured  = a baseline measured on this exact model and cell version
            estimate  = no measurement for this model: the smallest baseline measured on any other model or version
            none      = nothing measured for this cell yet: baseline and saved are null (never guessed)
            refused   = the call did not give a verified result
The rule is not to inflate: these numbers are meant to be trusted by someone else later, so a missing measurement
stays missing instead of being filled with a hopeful number.

Baselines: <cell dir>/baseline.json (shipped) and ~/.stemseal/baselines/<cell>/<version>.json (measured here; wins).
`stemseal measure` makes them with a local Ollama model. `stemseal savings` adds up the ledger."""
import json, math, os, re, time, urllib.request
from datetime import datetime, timedelta, timezone

METER = "meter/1"
BASELINE = "baseline/1"
METHOD = "chars_v1"

def est_tokens(text):
    """A plain, stable estimate: 1 token per 4 ASCII characters, 1 per other character (Hangul and most non-Latin
    scripts take about one token per character in small-model tokenizers). Same text, same number, on every machine."""
    if not isinstance(text, str): text = json.dumps(text, ensure_ascii=False, sort_keys=True)
    a = sum(1 for ch in text if ord(ch) < 128)
    return int(math.ceil(a / 4.0)) + (len(text) - a)

# ---------------------------------------------------------------- baselines
def _hub():
    from . import hub; return hub
def user_baseline_path(cell, version): return os.path.join(_hub().HOME, "baselines", cell, "%s.json" % version)
def _read(p):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return None
def _files(cell):
    """Every baseline file for a cell, (version, path), shipped first then this machine's (later wins on merge)."""
    hub = _hub(); out = []
    for v, d in sorted(hub._found(cell).items(), key=lambda x: hub._vkey(x[0])):
        out.append((v, os.path.join(d, "baseline.json")))
    ud = os.path.join(hub.HOME, "baselines", cell)
    if os.path.isdir(ud):
        for f in sorted(os.listdir(ud)):
            if f.endswith(".json"): out.append((f[:-5], os.path.join(ud, f)))
    return out
def baselines(cell):
    """{version: {model: entry}} merged over shipped and local files."""
    out = {}
    for v, p in _files(cell):
        b = _read(p)
        if b and b.get("format") == BASELINE:
            for m, e in (b.get("models") or {}).items():
                if isinstance(e, dict) and isinstance(e.get("tokens"), (int, float)): out.setdefault(v, {})[m] = e
    return out
def baseline_for(cell, version, model):
    """(tokens, kind, source). kind: measured | estimate | none."""
    allb = baselines(cell)
    if model and model in allb.get(version, {}): return allb[version][model]["tokens"], "measured", "%s@%s" % (model, version)
    others = [(e["tokens"], "%s@%s" % (m, v)) for v, ms in allb.items() for m, e in ms.items()]
    if others:
        t, src = min(others); return t, "estimate", src
    return None, "none", None

def meter(cell, version, model, sent, returned, ok):
    """The tokens object for one call row."""
    cost = est_tokens(json.dumps(sent, ensure_ascii=False, sort_keys=True)) + est_tokens(json.dumps(returned, ensure_ascii=False, sort_keys=True))
    rec = {"meter": METER, "method": METHOD, "cost": cost}
    if not ok: rec.update(baseline=0, kind="refused", saved=-cost); return rec
    try: b, kind, src = baseline_for(cell, version, model)
    except Exception: b, kind, src = None, "none", None
    rec.update(baseline=b, kind=kind, saved=(round(b - cost, 1) if b is not None else None))
    if src: rec["baseline_from"] = src
    return rec

# ---------------------------------------------------------------- savings report
def _ts(r):
    try: return datetime.fromisoformat(r.get("ts", "").replace("Z", "+00:00"))
    except Exception: return None
def read_ledger(path=None):
    """Ledger rows; a damaged line is skipped, not allowed to blank the whole report."""
    path = path or _hub().LEDGER; out = []
    if not os.path.exists(path): return out
    for l in open(path, encoding="utf-8", errors="replace"):
        try: out.append(json.loads(l))
        except Exception: pass
    return out
def _blank(): return {"calls": 0, "cost": 0, "baseline": 0, "saved": 0}
def summarize(rows, days=None):
    """Totals over ledger rows. Measured and estimated savings are never added together."""
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    rows = [r for r in rows if not since or ((_ts(r) or since) >= since)]
    kinds = {k: _blank() for k in ("measured", "estimate", "none", "refused")}
    by = {"cell": {}, "model": {}, "day": {}}
    unmetered = overhead = overhead_n = 0
    for r in rows:
        if r.get("type") == "meter":
            overhead += (r.get("tokens") or {}).get("cost", 0); overhead_n += 1; continue
        if r.get("type") != "call": continue
        t = r.get("tokens")
        if not isinstance(t, dict) or t.get("meter") != METER: unmetered += 1; continue
        k = t.get("kind", "none"); keys = {"cell": r.get("cell") or "?", "model": r.get("model") or "(unknown)", "day": (r.get("ts") or "")[:10]}
        for bucket in [kinds.setdefault(k, _blank())] + [by[d].setdefault(keys[d], {}).setdefault(k, _blank()) for d in by]:
            bucket["calls"] += 1; bucket["cost"] += t.get("cost", 0)
            if t.get("baseline") is not None: bucket["baseline"] += t["baseline"]
            if t.get("saved") is not None: bucket["saved"] += t["saved"]
    for b in list(kinds.values()) + [x for d in by.values() for m in d.values() for x in m.values()]:
        for f in ("cost", "baseline", "saved"): b[f] = round(b[f], 1)
    for b in [kinds["none"]] + [m["none"] for d in by.values() for m in d.values() if "none" in m]:
        b.pop("baseline", None); b.pop("saved", None)   # nothing measured: no number, not zero
    return {"format": "savings/1", "days": days, "unit": "tokens (estimated from text, %s)" % METHOD,
            "measured": kinds["measured"], "estimate": kinds["estimate"], "no_baseline": kinds["none"], "refused": kinds["refused"],
            "find_overhead": {"finds": overhead_n, "cost": overhead},
            "net_measured": round(kinds["measured"]["saved"] + kinds["refused"]["saved"] - overhead, 1),
            "unmetered_calls": unmetered,
            "by_cell": by["cell"], "by_model": by["model"], "by_day": dict(sorted(by["day"].items())),
            "note": "net_measured = measured savings - refused calls - find overhead. Estimates are shown apart and are not in it."}

# ---------------------------------------------------------------- measuring a baseline (local Ollama)
OLLAMA = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
def _chat(url, model, messages, num_ctx=4096, timeout=300):
    body = json.dumps({"model": model, "messages": messages, "stream": False, "options": {"temperature": 0, "seed": 7, "num_ctx": num_ctx}}).encode("utf-8")
    req = urllib.request.Request(url.rstrip("/") + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r: d = json.loads(r.read().decode("utf-8"))
    return {"text": (d.get("message") or {}).get("content", ""), "in": d.get("prompt_eval_count", 0), "out": d.get("eval_count", 0), "sec": round(time.time() - t0, 2)}
def question(contract, inp):
    """The task as a plain question built from the cell's own card, so every cell is measured the same way."""
    return ("%s\n입력: %s\n풀이를 보이고, 마지막 줄에 결과를 JSON 하나로 쓰세요. 키: %s"
            % (contract["description"], json.dumps(inp, ensure_ascii=False), ", ".join(contract.get("output_keys", []))))
def _last_json(text):
    for m in reversed(list(re.finditer(r"\{[^{}]*\}", text or ""))):
        try: return json.loads(m.group(0))
        except Exception: continue
    return None
def _same(got, exp):
    if not isinstance(got, dict) or not isinstance(exp, dict): return False
    for k, v in exp.items():
        g = got.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            try: g = float(str(g).replace(",", ""))
            except Exception: return False
            if abs(g - v) > max(0.01, abs(v) * 1e-6): return False
        elif g != v: return False
    return True
def _pick(cases, n):
    if len(cases) <= n: return list(range(len(cases)))
    step = len(cases) / float(n); return [int(i * step) for i in range(n)]

def measure(cell, model, n=5, url=None, ship=False, chat=None):
    """Measure the tokens a model spends on this cell's job without the cell, on n of its ground-truth cases.
      alone_out   output tokens when the model solves it alone (Ollama eval_count)
      answer_out  output tokens of the final answer when it is handed the cell's verified result instead
      tokens      alone_out - answer_out = what the cell replaces (the answer is written either way, so it is not counted as saved)
    Retries are not included (retry_included false); alone_correct is recorded so a retry cost can be argued later, apart.
    Writes ~/.stemseal/baselines/<cell>/<version>.json, or with ship=True the cell's own baseline.json (maintainers)."""
    hub = _hub(); chat = chat or _chat; url = url or OLLAMA
    c = hub.load(cell)
    if not c: return {"ok": False, "reason": "no locked cell with this name"}
    version = c["lock"]["version"]; cases = json.load(open(os.path.join(c["dir"], "gt_cases.json"), encoding="utf-8"))
    runs = []
    for i in _pick(cases, n):
        case = cases[i]; q = question(c["contract"], case["input"])
        alone = chat(url, model, [{"role": "user", "content": q}])
        r = hub.call(cell, case["input"], caller="measure", model=model, log=False)
        sent = {"cell": cell, "input": case["input"]}
        msgs = [{"role": "user", "content": q}, {"role": "assistant", "content": json.dumps(sent, ensure_ascii=False)},
                {"role": "user", "content": "세포 결과(검증됨): %s\n이 결과로 답하세요. 마지막 줄에 결과를 JSON 하나로 쓰세요." % json.dumps(r, ensure_ascii=False)}]
        withc = chat(url, model, msgs)
        runs.append({"case": i, "alone_out": alone["out"], "alone_in": alone["in"], "alone_correct": _same(_last_json(alone["text"]), case["expected"]),
                     "answer_out": withc["out"], "with_in": withc["in"], "cost_est": est_tokens(json.dumps(sent, ensure_ascii=False, sort_keys=True)) + est_tokens(json.dumps(r, ensure_ascii=False, sort_keys=True)),
                     "with_correct": _same(_last_json(withc["text"]), case["expected"]), "sec": round(alone["sec"] + withc["sec"], 1)})
    if not runs: return {"ok": False, "reason": "no ground-truth cases"}
    mean = lambda k: round(sum(x[k] for x in runs) / len(runs), 1)
    # how far the text estimate is from the model's real count, for the part stemseal adds (the call and the reply)
    real_added = [x["with_in"] - x["alone_in"] for x in runs]
    entry = {"kind": "measured", "tokens": round(mean("alone_out") - mean("answer_out"), 1), "alone_out": mean("alone_out"), "answer_out": mean("answer_out"),
             "n": len(runs), "alone_correct": round(sum(x["alone_correct"] for x in runs) / len(runs), 3),
             "with_cell_correct": round(sum(x["with_correct"] for x in runs) / len(runs), 3), "retry_included": False,
             "cost_est_mean": mean("cost_est"), "cost_real_mean": round(sum(real_added) / len(runs), 1),
             "measured_at": hub.now(), "method": "ollama eval_count, temperature 0, num_ctx 4096, question built from the cell card (savings.question)"}
    p = os.path.join(c["dir"], "baseline.json") if ship else user_baseline_path(cell, version)
    b = _read(p) or {"format": BASELINE, "cell": cell, "version": version, "models": {}}
    b["models"][model] = entry
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(b, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return {"ok": True, "cell": cell, "version": version, "model": model, "baseline": entry, "runs": runs, "written": p}
