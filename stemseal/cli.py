# -*- coding: utf-8 -*-
"""stemseal command line.
  stemseal list                      cells on this machine
  stemseal find <need words...>      cells that fit a need
  stemseal call <cell> '<json>'      run a cell (or @file.json)
  stemseal verify                    re-check every lock (sha256) and ground-truth case
  stemseal request <need words...> [--example "<input -> answer>"]
                                     record a cell you needed; prints a link you can open to ask for it
  stemseal demand                    your unmet needs, alike requests grouped and counted (kept only on this machine)
  stemseal demand --share            the same, with a prefilled GitHub cell-request link per need
  stemseal demand --open <n> [--yes] show the n-th need's issue text (contact data hidden), then open it in your browser if you agree
  stemseal demand --all | --json     include needs a cell now answers | raw groups as JSON
  stemseal update [--check]          bring cells made since this install (each is re-verified here before use)
  stemseal savings [--days N]        tokens the cells saved, from this machine's ledger (measured and estimated kept apart)
  stemseal measure <cell> <model> [--n 5] [--url http://127.0.0.1:11434] [--ship]
                                     measure a cell's baseline (tokens without the cell) with a local Ollama model
  stemseal guide <model> [ko|en]     the selection guide used for a model name
  stemseal mcp                       run the MCP server on stdio (same as stemseal-mcp)"""
import json, sys
from . import hub, guides, savings, update as upd

def _p(o): print(json.dumps(o, ensure_ascii=False, indent=1))

def _demand(rest):
    groups = hub.demand_summary(include_ready="--all" in rest)
    if "--json" in rest: _p(groups); return 0
    if "--open" in rest:
        i = rest.index("--open")
        try: g = groups[int(rest[i + 1]) - 1]
        except (IndexError, ValueError): print("stemseal demand --open <n>: n is a number from the `stemseal demand` list"); return 2
        title, body = hub.issue_text(g)
        print("This is what the GitHub issue will say. The repository is PUBLIC: anyone can read it.")
        print("Contact-like data (phone, email, ID, long number runs) is hidden; check names and anything else private.\n")
        print("title: %s\n\n%s" % (title, body))
        ok = "--yes" in rest
        if not ok and sys.stdin.isatty():
            try: ok = input("Open this in your browser? You still press Submit on GitHub. [y/N] ").strip().lower() in ("y", "yes")
            except EOFError: ok = False
        link = hub.share_link(g)
        if not ok: print("\nNot opened. To open it yourself: %s" % link); return 0
        import webbrowser; webbrowser.open(link); print("\nOpened. Nothing is sent until you press Submit."); return 0
    if not groups: print("No unmet needs recorded on this machine (%s)." % hub.LEDGER); return 0
    print("Unmet needs on this machine, most asked first (%s). Nothing here has been sent anywhere.\n" % hub.LEDGER)
    for n, g in enumerate(groups, 1):
        by = "%d asked by the model" % g["explicit"] + (", %d found nothing" % g["auto"] if g["auto"] else "")
        print("%2d. [%dx] %s   (%s%s)" % (n, g["count"], g["need"], by, "; ready: " + g["cell"] if g["status"] == "ready" else ""))
        print("     ticket %s · last %s%s%s" % (" ".join(g["tickets"][:4]), (g["last"] or "")[:16].replace("T", " "),
              " · models " + ", ".join(g["models"]) if g["models"] else "",
              " · closest %s (%.2f)" % (g["nearest"], g["nearest_score"]) if g["nearest"] else ""))
        for w in g["wordings"][1:3]: print("     also asked as: %s" % w)
        for e in g["examples"][:1]: print("     example: %s" % e)
        if "--share" in rest: print("     ask for it: %s" % hub.share_link(g))
    if "--share" not in rest: print("\nTo ask for one: stemseal demand --open <n>   (shows the issue text first; you decide whether to open and submit it)")
    return 0

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
    elif cmd == "request":
        ex = None
        if "--example" in rest:
            i = rest.index("--example"); ex = " ".join(rest[i + 1:i + 2]) or None; rest = rest[:i] + rest[i + 2:]
        r = hub.request_cell(" ".join(rest), caller="cli", example=ex); _p(r); return 0 if r.get("recorded") else 2
    elif cmd == "demand": return _demand(rest)
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
