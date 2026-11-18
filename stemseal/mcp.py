#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stemseal - MCP server (stdio). Add to an MCP client as:  command: stemseal-mcp   (or: python -m stemseal.mcp)
Three tools. An AI states what it needs, gets back the few locked cells that fit, and calls one.
Env: STEMSEAL_CALLER = name recorded in the ledger for this client (default 'mcp').
     STEMSEAL_MODEL  = the client's model name (e.g. exaone3.5:7.8b). Unset, the general small-model guide is used. When set, find_cell returns that model's cell-selection guide
                       with the candidates, and call_cell repairs the input mistakes the guide knows about (see guides/)."""
import json, os, sys
from . import hub, guides, __version__
CALLER = os.environ.get("STEMSEAL_CALLER", "mcp")
MODEL = os.environ.get("STEMSEAL_MODEL")
TOOLS = [
 {"name": "find_cell", "description": "Call this first whenever the user asks for a number worked out by rules: wages, salary, rates, growth, margins, prices, percentiles, calories, currency, leave days and similar. Verified cells give the exact checked answer, and small models get these wrong when computing alone. State the need in plain words. Returns the cells that fit, each with its required inputs and an input example, or an empty list when nothing fits.",
  "inputSchema": {"type": "object", "properties": {"need": {"type": "string", "description": "What you need computed, in plain words (Korean or English)."}, "words": {"type": "array", "items": {"type": "string"}, "description": "Optional: 3-6 standard names for the calculation (e.g. 연평균 성장률, 이동평균). They are searched too, which helps the hub find a cell when the request is worded unusually."}}, "required": ["need"]}},
 {"name": "call_cell", "description": "Run a locked cell found with find_cell (use its exact name; do not guess names). Use the cell's required input keys exactly, as in its input example. Pass its input either inline as `input` or, for large data, as `input_file` (path to a JSON file holding the input object) so the data need not be retyped. Returns status ok (verified result), not_available, or invalid_input. Never invents a result. If refused, the reply's how_to_fix shows the exact input to send again.",
  "inputSchema": {"type": "object", "properties": {"cell": {"type": "string"}, "input": {"type": "object"}, "input_file": {"type": "string"}}, "required": ["cell"]}},
 {"name": "list_cells", "description": "List every locked cell on this machine with what it computes and its required inputs. Cheap; use it when unsure what exists.",
  "inputSchema": {"type": "object", "properties": {}}},
 {"name": "request_cell", "description": "Tell the hub that you needed a calculation and no cell fit. This is how new cells get made: you get a ticket, and the cell is built as demand gathers, so come back next time. Describe the need in one or two sentences.",
  "inputSchema": {"type": "object", "properties": {"need": {"type": "string"}}, "required": ["need"]}},
]
def _card(h, lang):
    """What a small model needs to act on one candidate, nothing more."""
    c = hub.load(h["cell"])["contract"]; card = {"cell": h["cell"],
        "computes": (c.get("description_en") if lang == "en" else None) or c["description"],
        "required_inputs": c["input_schema"].get("required", []), "output_keys": c.get("output_keys", [])}
    try: card["input_example"] = json.load(open(os.path.join(hub.load(h["cell"])["dir"], "gt_cases.json"), encoding="utf-8"))[0]["input"]
    except Exception: pass
    return card
NEXT = {"ko": "다음 단계: 사용자가 묻는 값과 output_keys 가 맞는 세포를 골라, call_cell 에 그 cell 이름과 input_example 과 같은 모양의 input 을 넣어 부르세요. 세포의 답이 검증된 정답입니다.",
        "en": "Next step: pick the cell whose output_keys match what the user asked, then call call_cell with that cell name and an input shaped like its input_example. The cell's answer is the verified result."}
def find_for_mcp(need, words=None):
    r = guides.find(need, model=MODEL, caller=CALLER, words=words); lang = r["guide"].get("lang", "ko")
    out = {"cells": [_card(h, lang) for h in r["cells"]]}
    if out["cells"]: out["next_step"] = NEXT[lang]
    else: out["no_cell"] = r.get("no_cell")
    return out
def handle(name, a):
    if name == "find_cell": return find_for_mcp(a.get("need", ""), a.get("words") if isinstance(a.get("words"), list) else None)
    if name == "list_cells": return {"cells": [{k: c[k] for k in ("cell", "version", "description", "description_en", "required_inputs")} for c in hub.list_cells()]}
    if name == "request_cell": return hub.request_cell(a.get("need", ""), caller=CALLER)
    if name == "call_cell":
        data = dict(a.get("input") or {})
        if a.get("input_file"):
            try: f = json.load(open(a["input_file"], encoding="utf-8"))
            except Exception as e: return {"status": "invalid_input", "reason": "cannot read input_file: %s" % e}
            if isinstance(f, dict): data = {**f, **data}
        cell = str(a.get("cell", ""))
        r = guides.call(cell, data, model=MODEL, caller=CALLER)
        if r.get("status") == "not_available" and not (hub.re.fullmatch(r"[a-z][a-z0-9_]{2,63}", cell) and hub.load(cell)):
            # small models often guess a cell name ("wages") instead of calling find_cell first: show the real ones
            f = find_for_mcp(cell.replace("_", " ") + " " + " ".join(str(k) for k in data))
            g = guides.guide_for(MODEL)
            # strict: only spelling fixes count here (not rename_single), so an unrelated input never gets run
            g["selection"]["repair_input"] = [x for x in g["selection"].get("repair_input", []) if x != "rename_single"]
            for cand in f["cells"]:
                # the guessed name plus the input it came with point at one real cell: when that cell's required inputs are
                # all there (after the usual repairs), run it rather than stop at a choice a small model often abandons
                fixed, _ = guides.repair(cand["cell"], data, g)
                if data and all(k in fixed for k in cand["required_inputs"]):
                    r2 = guides.call(cand["cell"], data, model=MODEL, caller=CALLER)
                    if r2.get("status") == "ok":
                        r2["resolved_from"] = cell
                        r2["note"] = "No cell is named %r; ran %s, the cell that matches this request and input. This result is verified." % (cell, cand["cell"])
                        return r2
            if f["cells"]:
                r["did_you_mean"] = f["cells"]; r["next_step"] = f["next_step"]
                r["reason"] = "no cell is named %r. Use one of did_you_mean, with its exact name." % cell
        return r
    raise ValueError("unknown tool")
def send(o):
    # ASCII-only JSON (\uXXXX escapes): on Windows a pipe defaults to the locale code page (cp949 on Korean Windows),
    # which garbles Korean text for an MCP client that reads UTF-8.
    sys.stdout.write(json.dumps(o, ensure_ascii=True) + "\n"); sys.stdout.flush()
def main():
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
