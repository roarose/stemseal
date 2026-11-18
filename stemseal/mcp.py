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
 {"name": "call_cell", "description": "Run a locked cell found with find_cell. Use the cell's required input keys exactly, as in its input example. Pass its input either inline as `input` or, for large data, as `input_file` (path to a JSON file holding the input object) so the data need not be retyped. Returns status ok (verified result), not_available, or invalid_input. Never invents a result. If refused, the reply's how_to_fix shows the exact input to send again.",
  "inputSchema": {"type": "object", "properties": {"cell": {"type": "string"}, "input": {"type": "object"}, "input_file": {"type": "string"}}, "required": ["cell"]}},
 {"name": "list_cells", "description": "List every locked cell on this machine with what it computes and its required inputs. Cheap; use it when unsure what exists.",
  "inputSchema": {"type": "object", "properties": {}}},
 {"name": "request_cell", "description": "Tell the hub that you needed a calculation and no cell fit. This is how new cells get made: you get a ticket, and the cell is built as demand gathers, so come back next time. Describe the need in one or two sentences.",
  "inputSchema": {"type": "object", "properties": {"need": {"type": "string"}}, "required": ["need"]}},
]
def handle(name, a):
    if name == "find_cell": return guides.find(a.get("need", ""), model=MODEL, caller=CALLER, words=a.get("words") if isinstance(a.get("words"), list) else None)
    if name == "list_cells": return {"cells": [{k: c[k] for k in ("cell", "version", "description", "when_to_use", "required_inputs")} for c in hub.list_cells()]}
    if name == "request_cell": return hub.request_cell(a.get("need", ""), caller=CALLER)
    if name == "call_cell":
        data = dict(a.get("input") or {})
        if a.get("input_file"):
            try: f = json.load(open(a["input_file"], encoding="utf-8"))
            except Exception as e: return {"status": "invalid_input", "reason": "cannot read input_file: %s" % e}
            if isinstance(f, dict): data = {**f, **data}
        return guides.call(a.get("cell", ""), data, model=MODEL, caller=CALLER)
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
