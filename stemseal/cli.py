# -*- coding: utf-8 -*-
"""stemseal command line.
  stemseal list                      cells on this machine
  stemseal find <need words...>      cells that fit a need
  stemseal call <cell> '<json>'      run a cell (or @file.json)
  stemseal verify                    re-check every lock (sha256) and ground-truth case
  stemseal request <need words...>   record a cell you needed; prints a link you can open to ask for it
  stemseal demand [--share]          your recorded unmet needs (kept only on this machine); --share prints a link per need to ask for it
  stemseal update [--check]          bring cells made since this install (each is re-verified here before use)
  stemseal savings [--days N]        tokens the cells saved, from this machine's ledger (measured and estimated kept apart)
  stemseal measure <cell> <model> [--n 5] [--url http://127.0.0.1:11434] [--ship]
                                     measure a cell's baseline (tokens without the cell) with a local Ollama model
  stemseal guide <model> [ko|en]     the selection guide used for a model name
  stemseal mcp                       run the MCP server on stdio (same as stemseal-mcp)"""
import json, sys
from . import hub, guides, savings, update as upd

def _p(o): print(json.dumps(o, ensure_ascii=False, indent=1))

def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv) or ["list"]
    cmd, rest = a[0], a[1:]
    if cmd == "list": _p([{k: c[k] for k in ("cell", "version", "description", "required_inputs")} for c in hub.list_cells()])
    elif cmd == "find": _p(hub.find(" ".join(rest), caller="cli"))
    elif cmd == "call":
        if len(rest) != 2: print(__doc__); return 2
        raw = rest[1]; data = json.load(open(raw[1:], encoding="utf-8")) if raw.startswith("@") else json.loads(raw)
        r = hub.call(rest[0], data, caller="cli"); _p(r); return 0 if r["status"] == "ok" else 1
    elif cmd == "verify":
        r = hub.verify_all(); _p(r)
        bad = [k for k, v in r.items() if not (v["hash_ok"] and v["deterministic"] and v["gt"].split("/")[0] == v["gt"].split("/")[1])]
        print("all %d cells verified" % len(r) if not bad else "FAILED: %s" % bad); return 1 if bad else 0
    elif cmd == "request": _p(hub.request_cell(" ".join(rest), caller="cli"))
    elif cmd == "demand":
        if "--share" in rest:
            done = {r["ticket"] for r in hub._rows() if r.get("type") == "fulfilled"}
            seen = {}
            for r in hub._rows():
                if r.get("type") == "demand" and r.get("ticket") and r["ticket"] not in done: seen[r["ticket"]] = r["need"]
            _p([{"ticket": t, "need": n, "link": hub.share_link(t, n)} for t, n in seen.items()])
        else: _p(hub.stats()["unmet_demand"])
    elif cmd == "update":
        r = upd.update(check_only="--check" in rest); _p(r); return 0 if r.get("ok") else 1
    elif cmd == "index": _p({k: list(v) for k, v in upd.build_index()["cells"].items()})
    elif cmd == "mcp":
        from . import mcp as _m; _m.main(); return 0
    elif cmd == "savings":
        try: days = int(rest[rest.index("--days") + 1]) if "--days" in rest else None
        except (ValueError, IndexError): print("--days needs a whole number of days"); return 2
        _p(savings.summarize(savings.read_ledger(), days=days))
    elif cmd == "measure":
        if len(rest) < 2: print(__doc__); return 2
        opt = lambda k, d: rest[rest.index(k) + 1] if k in rest else d
        r = savings.measure(rest[0], rest[1], n=int(opt("--n", 5)), url=opt("--url", None), ship="--ship" in rest)
        _p({k: v for k, v in r.items() if k != "runs"} if r.get("ok") else r); return 0 if r.get("ok") else 1
    elif cmd == "guide": _p(guides.brief(guides.guide_for(rest[0] if rest else ""), (rest[1] if len(rest) > 1 else "ko")))
    else: print(__doc__); return 2
    return 0

if __name__ == "__main__": sys.exit(main())
