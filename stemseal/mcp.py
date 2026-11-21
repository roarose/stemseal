#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stemseal - MCP server (stdio). Add to an MCP client as:  command: stemseal-mcp   (or: python -m stemseal.mcp)
Three tools. An AI states what it needs, gets back the few locked cells that fit, and calls one.
Env: STEMSEAL_CALLER = name recorded in the ledger for this client (default 'mcp').
     STEMSEAL_LOG    = full (default) | minimal (request sentences kept only as a hash and a few words) | off (no ledger).
     STEMSEAL_INPUT_DIR = folder call_cell's input_file may read from (default ~/.stemseal/inputs; the server's start folder too,
                        unless it is a drive's top, the home folder or a folder above it).
     STEMSEAL_MODEL  = the client's model name (e.g. exaone3.5:7.8b). Unset, the general small-model guide is used. When set, find_cell returns that model's cell-selection guide
                       with the candidates, and call_cell repairs the input mistakes the guide knows about (see guides/)."""
import json, os, sys
from . import hub, guides, savings, __version__
CALLER = os.environ.get("STEMSEAL_CALLER", "mcp")
MODEL = os.environ.get("STEMSEAL_MODEL")
TOOLS = [
 {"name": "find_cell", "description": "Call this first whenever the user asks for a number worked out by rules: wages, salary, rates, growth, margins, prices, percentiles, calories, currency, leave days and similar. Verified cells give the exact checked answer, and small models get these wrong when computing alone. State the need in plain words. Returns the cells that fit, each with its required inputs and an input example, or an empty list when nothing fits.",
  "inputSchema": {"type": "object", "properties": {"need": {"type": "string", "description": "What you need computed, in plain words (Korean or English)."}, "words": {"type": "array", "items": {"type": "string"}, "description": "Optional: 3-6 standard names for the calculation (e.g. 연평균 성장률, 이동평균). They are searched too, which helps the hub find a cell when the request is worded unusually."}}, "required": ["need"]}},
 {"name": "call_cell", "description": "Run a locked cell found with find_cell (use its exact name; do not guess names). Use the cell's required input keys exactly, as in its input example. Pass its input either inline as `input` or, for large data, as `input_file` (path to a JSON file holding the input object) so the data need not be retyped. Returns status ok (verified result), not_available, or invalid_input. Never invents a result. If refused, the reply's how_to_fix shows the exact input to send again.",
  "inputSchema": {"type": "object", "properties": {"cell": {"type": "string"}, "input": {"type": "object"}, "input_file": {"type": "string"}}, "required": ["cell"]}},
 {"name": "list_cells", "description": "List every locked cell on this machine with what it computes and its required inputs. Cheap; use it when unsure what exists.",
  "inputSchema": {"type": "object", "properties": {}}},
 {"name": "request_cell", "description": "Ask for a cell that does not exist yet. When find_cell had nothing that fits (or only something close but different), say in one sentence what you needed computed. The request is saved, requests asked alike are counted together, and cells are made in the order they are asked for, so the next time this calculation comes up there may be an exact answer waiting. Only `need` is required.",
  "inputSchema": {"type": "object", "properties": {"need": {"type": "string", "description": "What you needed computed, in one sentence (Korean or English)."},
   "example": {"type": "string", "description": "Optional: one input and the answer you expect, in any words (e.g. '1,000,000 won loan, 5% a year, 12 months -> 85,607 a month')."}}, "required": ["need"]}},
]
def _card(h, lang):
    """What a small model needs to act on one candidate, nothing more."""
    c = hub.load(h["cell"])["contract"]; card = {"cell": h["cell"],
        "computes": (c.get("description_en") if lang == "en" else None) or c["description"],
        "required_inputs": c["input_schema"].get("required", []), "output_keys": c.get("output_keys", [])}
    # a template, not a worked example: small models copied example numbers (rate 1544.2, rates [-0.011, ...]) into real calls
    props = c["input_schema"].get("properties", {})
    card["input_template"] = {k: "<%s, from the user's question>" % props.get(k, "number") for k in card["required_inputs"]}
    return card
NEXT = {"ko": "다음 단계: 사용자가 묻는 값과 output_keys 가 맞는 세포를 골라, call_cell 에 그 cell 이름과 input_template 의 키를 쓰고 값은 사용자 질문의 숫자로 채워 부르세요. 세포의 답이 검증된 정답입니다.",
        "en": "Next step: pick the cell whose output_keys match what the user asked, then call call_cell with that cell name and its input_template keys, filled with the numbers from the user's question. The cell's answer is the verified result."}
def _for_model(reply):
    """A no-cell reply as the model gets it: the message and the closest cell only. The ticket and counts are for people (stemseal demand)."""
    return {k: v for k, v in reply.items() if k in ("message", "closest_cell", "reason")}
def find_for_mcp(need, words=None, record=True):
    need = need if isinstance(need, str) else ("" if need is None else json.dumps(need, ensure_ascii=False))
    r = guides.find(need, model=MODEL, caller=CALLER, words=words, record=record); lang = r["guide"].get("lang", "ko")
    out = {"cells": [_card(h, lang) for h in r["cells"]]}
    if out["cells"]: out["next_step"] = NEXT[lang]
    elif r.get("no_cell"): out["no_cell"] = _for_model(r["no_cell"])
    return out
# input_file may name only a .json file of at most 1MB under the inputs folder, or under the folder the server was started in
# when that folder is not a drive's top, the home folder or a folder above it.
INPUT_DIR = os.path.realpath(os.environ.get("STEMSEAL_INPUT_DIR") or os.path.join(hub.HOME, "inputs"))
MAX_INPUT_FILE = 1024 * 1024
RESERVED = {"con", "prn", "aux", "nul", "conin$", "conout$"} | {"%s%d" % (p, i) for p in ("com", "lpt") for i in range(10)}
def _same(a, b): return os.path.normcase(a) == os.path.normcase(b)
def _under(path, root):
    try: return _same(os.path.commonpath([path, root]), root)
    except ValueError: return False             # another drive, or one path relative
def _broad(folder):
    """A folder too wide to read input files from: a drive's (or the file system's) top, the home folder, or one above it."""
    home = os.path.realpath(os.path.expanduser("~"))
    return _same(os.path.dirname(folder), folder) or _under(home, folder)
def input_roots(cwd=None):
    cwd = os.path.realpath(cwd or os.getcwd())
    return [INPUT_DIR] + ([cwd] if not _broad(cwd) and not _same(cwd, INPUT_DIR) else [])
INPUT_ROOTS = input_roots()
def _shown(folder):
    home = os.path.realpath(os.path.expanduser("~"))
    if _under(folder, home): return "~" + folder[len(home):]
    return os.path.basename(folder) or "the inputs folder"
def input_file_error(path):
    name = os.path.basename(str(path).replace("\\", "/"))[:60]
    where = _shown(INPUT_DIR) + (" or the folder the server was started in" if len(INPUT_ROOTS) > 1 else "")
    return "input_file '%s' was not read: it must be a .json file of at most 1MB in %s" % (name, where)
def read_input_file(path):
    """The parsed JSON of an allowed input file, or None. Every failure gives the same None. A relative path is taken
    from the inputs folder first, then from the folder the server was started in."""
    try:
        path = str(path)
        cands = [path] if os.path.isabs(path) else [os.path.join(root, path) for root in INPUT_ROOTS]
        for cand in cands:
            real = os.path.realpath(cand)
            base = os.path.basename(real).lower()
            if not base.endswith(".json") or base.split(".")[0].rstrip(" ") in RESERVED or ":" in base: continue
            if not os.path.isfile(real) or not any(_under(real, root) for root in INPUT_ROOTS): continue
            with open(real, "rb") as fh: raw = fh.read(MAX_INPUT_FILE + 1)
            if len(raw) > MAX_INPUT_FILE: return None
            return json.loads(raw.decode("utf-8"))
        return None
    except Exception: return None
CORE = {"status", "cell", "version", "verified", "result", "reason", "how_to_fix", "guide", "repairs", "input_used", "answer_text", "say"}
def handle(name, a):
    """Every tool's tokens are counted. call_cell's core reply is metered on its call row (hub.call); what this server adds to it
    (did_you_mean, call_this, no_cell, notes) and every other tool's request and reply go on a type=meter row the report subtracts."""
    out = _handle(name, a)
    try:
        if name == "call_cell":
            extra = {k: v for k, v in out.items() if k not in CORE} if isinstance(out, dict) else {}
            texts = [json.dumps(extra, ensure_ascii=False, sort_keys=True)] if extra else []
        else: texts = [json.dumps(a, ensure_ascii=False, sort_keys=True), json.dumps(out, ensure_ascii=False, sort_keys=True)]
        if texts: hub._log({"type": "meter", "tool": name, "caller": CALLER, "model": MODEL, "tokens": savings.text_cost(texts, MODEL)})
    except Exception: pass   # the meter must never break a tool
    return out
def _handle(name, a):
    if name == "find_cell": return find_for_mcp(a.get("need", ""), a.get("words") if isinstance(a.get("words"), list) else None)
    if name == "list_cells": return {"cells": [{k: c[k] for k in ("cell", "version", "description", "description_en", "required_inputs")} for c in hub.list_cells()]}
    if name == "request_cell":
        r = hub.request_cell(str(a.get("need") or ""), caller=CALLER, model=MODEL, example=a.get("example") or None)
        return _for_model(r) if r.get("recorded") else r
    if name == "call_cell":
        data = dict(a.get("input") or {})
        if a.get("input_file"):
            f = read_input_file(a["input_file"])
            if f is None: return {"status": "invalid_input", "reason": input_file_error(a["input_file"])}
            if isinstance(f, dict): data = {**f, **data}
        cell = str(a.get("cell", ""))
        r = guides.call(cell, data, model=MODEL, caller=CALLER)
        if r.get("status") == "not_available" and not (hub.re.fullmatch(r"[a-z][a-z0-9_]{2,63}", cell) and hub.load(cell)):
            # small models often guess a cell name ("wages") instead of calling find_cell first: show the real ones
            f = find_for_mcp(cell.replace("_", " ") + " " + " ".join(str(k) for k in data), record=False)
            g = guides.guide_for(MODEL)
            # strict: only spelling fixes count here (not rename_single), so an unrelated input never gets run
            g["selection"]["repair_input"] = [x for x in g["selection"].get("repair_input", []) if x != "rename_single"]
            # the guessed name alone must point at the candidate too (top of a name-only search), so an input key
            # shared by chance ("years") can never run an unrelated cell
            nr = hub._rank(cell.replace("_", " "), 0.0); top = nr[0][0] if nr else 0
            near = {c["cell"] for sc, c in nr if sc >= 0.5 and sc >= top - 0.05}
            for cand in f["cells"]:
                if cand["cell"] not in near: continue
                # the guessed name plus the input it came with point at one real cell: when that cell's required inputs are
                # all there (after the usual repairs), run it rather than stop at a choice a small model often abandons
                fixed, _ = guides.repair(cand["cell"], data, g)
                if data and all(k in fixed for k in cand["required_inputs"]):
                    r2 = guides.call(cand["cell"], data, model=MODEL, caller=CALLER)
                    if r2.get("status") == "ok":
                        r2["resolved_from"] = cell
                        r2["note"] = "No cell is named %r; ran %s, the cell that matches this request and input. This result is verified." % (cell, cand["cell"])
                        return r2
            if top < 0.5:
                # the guessed name matches no cell: say so plainly and record it as demand, rather than offer unrelated cells
                r["no_cell"] = hub.request_cell(cell.replace("_", " ") + (" | inputs: " + ", ".join(str(k) for k in data) if data else ""), caller=CALLER, model=MODEL, auto=True)
                r["no_cell"] = {"message": r["no_cell"]["message"]}   # the guessed name matched nothing well: offer no cell at all
                r["reason"] = "no such cell"
            elif f["cells"]:
                close = [c for c in f["cells"] if c["cell"] in near] or f["cells"]
                # the model wanted a cell by a name that does not exist and the closest one did not run on its input: keep the need
                # as demand too (auto), so it is not lost if the model gives up here; the suggestion is saved with it as `nearest`
                # unless the guessed name shares a whole word with a suggested cell ("vat_calc" -> vat_supply_price): then it is a
                # misspelt existing cell, not a new need, and counting it would pad the demand list
                if not any(hub.shares_word(cell.replace("_", " "), c["cell"]) for c in close):
                    hub._log_demand(cell.replace("_", " ") + (" | inputs: " + ", ".join(str(k) for k in data) if data else ""), CALLER, model=MODEL, auto=True)
                r["did_you_mean"] = close; r["next_step"] = f["next_step"]
                if len(close) == 1:
                    # one clear match: hand back the exact call to make, so a small model only has to fill in the numbers
                    r["call_this"] = {"cell": close[0]["cell"], "input": close[0]["input_template"],
                                      "note": "Same cell, same keys; put the user's numbers in place of each <...>."}
                r["reason"] = "no cell is named %r. Call %s instead, with its exact input keys." % (cell, " or ".join(c["cell"] for c in close))
        return r
    raise ValueError("unknown tool")
def send(o):
    # ASCII-only JSON (\uXXXX escapes): on Windows a pipe defaults to the locale code page (cp949 on Korean Windows),
    # which garbles Korean text for an MCP client that reads UTF-8.
    sys.stdout.write(json.dumps(o, ensure_ascii=True) + "\n"); sys.stdout.flush()
LEDGER_NOTE = "stemseal: STEMSEAL_LOG=minimal, but the ledger still has rows written before; to keep only what minimal keeps, run: stemseal ledger --minimize"
def main():
    hub.tidy_ledger()
    if hub.log_mode() == "minimal" and hub.ledger_has_text(): print(LEDGER_NOTE, file=sys.stderr)
    for st in (sys.stdin, sys.stdout):
        try: st.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        m = json.loads(line); mid = m.get("id"); meth = m.get("method")
        if meth == "initialize": send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": (m.get("params") or {}).get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}}, "serverInfo": {"name": "stemseal", "version": __version__}}})
        elif meth == "tools/list": send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif meth == "tools/call":
            try: send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(handle(m["params"]["name"], m["params"].get("arguments") or {}), ensure_ascii=False)}]}})
            except Exception as e: send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": "error: %s" % e}], "isError": True}})
        elif mid is not None: send({"jsonrpc": "2.0", "id": mid, "result": {}})

if __name__ == "__main__":
    main()
