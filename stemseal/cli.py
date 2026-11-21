# -*- coding: utf-8 -*-
"""stemseal command line.
  stemseal list                      cells on this machine
  stemseal find <need words...>      cells that fit a need
  stemseal call <cell> '<json>'      run a cell (or @file.json)
  stemseal verify                    re-check every lock (all files it covers), the checker and every ground-truth case
  stemseal reseal <cell ...> | --all [--dry-run] [--yes]
                                     give your own cells (format 1 lock) a format 2 lock at the same version, after re-checking them
                                     here; it seals contract.json and gt_cases.json as they are now, and shows them before writing
  stemseal request <need words...> [--example "<input -> answer>"]
                                     record a cell you needed; prints a link you can open to ask for it
  stemseal demand                    your unmet needs, alike requests grouped and counted (kept only on this machine)
  stemseal demand --share            the same, with a prefilled GitHub cell-request link per need
  stemseal demand --open <n> [--yes] show the n-th need's issue text (contact data hidden), then open it in your browser if you agree
  stemseal demand --all | --json     include needs a cell now answers | raw groups as JSON
  stemseal ledger [--minimize]       where this machine's ledger is and what it keeps; --minimize rewrites the rows already
                                     there as STEMSEAL_LOG=minimal keeps them (sentences become a hash and a few words)
  stemseal update [--check]          bring cells made since this install (each is re-verified here before use)
  stemseal savings [--days N]        tokens the cells saved, from this machine's ledger (measured and estimated kept apart)
  stemseal measure <cell> <model> [--n 5] [--url http://127.0.0.1:11434] [--ship]
                                     measure a cell's baseline (tokens without the cell) with a local Ollama model
  stemseal guide <model> [ko|en]     the selection guide used for a model name
  stemseal bench [--n 30] [--warmup 5] how long a cell call takes on this machine (saved to ~/.stemseal/bench-*.json)
  stemseal mcp                       run the MCP server on stdio (same as stemseal-mcp)"""
import json, sys
from . import hub, guides, savings, limits, update as upd

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
    for st in (sys.stdout, sys.stderr):
        try: st.reconfigure(errors="replace")   # a console that cannot show Korean prints '?' instead of failing
        except Exception: pass
    a = list(sys.argv[1:] if argv is None else argv) or ["list"]
    cmd, rest = a[0], a[1:]
    if cmd == "list":
        _p([{k: c[k] for k in ("cell", "version", "description", "required_inputs")} for c in hub.list_cells()])
        for u in hub.unsealed(): print("not usable: %s %s: %s" % (u["cell"], u["version"], u["why"]), file=sys.stderr)
    elif cmd == "find": _p(hub.find(" ".join(rest), caller="cli"))
    elif cmd == "call":
        if len(rest) != 2: print(__doc__); return 2
        raw = rest[1]; data = json.load(open(raw[1:], encoding="utf-8")) if raw.startswith("@") else json.loads(raw)
        r = hub.call(rest[0], data, caller="cli"); _p(r); return 0 if r["status"] == "ok" else 1
    elif cmd == "verify":
        r = hub.verify_all(); _p(r)
        bad = [k for k, v in r.items() if not (v["hash_ok"] and v.get("seal_ok") and v.get("policy_ok") and v.get("gt_ok") and v["deterministic"])]
        for k in bad:
            if r[k].get("seal"): print("%s: %s" % (k, r[k]["seal"]))
        print("all %d cells verified" % len(r) if not bad else "FAILED: %s" % bad)
        if not limits.MEMORY_ENFORCED: print("note: this system does not enforce the memory limit; cells are limited by time only")
        if not limits.PROCESS_LIMIT_ENFORCED: print("note: running as root, so the system does not enforce the one-process limit; run stemseal as a regular user")
        return 1 if bad else 0
    elif cmd == "request":
        ex = None
        if "--example" in rest:
            i = rest.index("--example"); ex = " ".join(rest[i + 1:i + 2]) or None; rest = rest[:i] + rest[i + 2:]
        r = hub.request_cell(" ".join(rest), caller="cli", example=ex); _p(r); return 0 if r.get("recorded") else 2
    elif cmd == "demand": return _demand(rest)
    elif cmd == "ledger":
        if "--minimize" in rest: print("rewrote %d rows in %s" % (hub.minimize_ledger(), hub.LEDGER)); return 0
        print("ledger: %s\nmode: %s (STEMSEAL_LOG)" % (hub.LEDGER, hub.log_mode()))
        if hub.ledger_has_text():
            print("rows written in full mode are still there" + ("; to keep only what minimal keeps, run: stemseal ledger --minimize" if hub.log_mode() == "minimal" else ""))
        return 0
    elif cmd == "update":
        r = upd.update(check_only="--check" in rest); _p(r); return 0 if r.get("ok") else 1
    elif cmd in ("reseal", "relock"):
        from . import reseal as _r
        dry = "--dry-run" in rest; names = [x for x in rest if not x.startswith("--")]
        if cmd == "relock": r = _r.relock(dry_run=dry); _p(r); return 0 if r["ok"] else 1
        if not names and "--all" not in rest: print(__doc__); return 2
        def confirm(plan):
            print("These cells will be sealed as their files are now (contract.json and gt_cases.json included):", file=sys.stderr)
            for x in plan:
                print("  %s %s  %s" % (x["cell"], x["version"], x["description"]), file=sys.stderr)
                for f, h in x["files"].items(): print("      %-14s %s" % (f, h), file=sys.stderr)
            if "--yes" in rest: return True
            if not sys.stdin.isatty(): print("Not sealed: add --yes to agree without a prompt.", file=sys.stderr); return False
            try: return input("Seal these %d cell(s)? [y/N] " % len(plan)).strip().lower() in ("y", "yes")
            except EOFError: return False
        r = _r.reseal(names or None, dry_run=dry, confirm=confirm); _p(r)
        return 1 if r["failed"] or (r["plan"] and not dry and not r["confirmed"]) else 0
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
    elif cmd == "bench":
        from . import bench as _b
        opt = lambda k, d: int(rest[rest.index(k) + 1]) if k in rest else d
        _p(_b.run(n=opt("--n", 30), warmup=opt("--warmup", 5)))
    elif cmd == "guide": _p(guides.brief(guides.guide_for(rest[0] if rest else ""), (rest[1] if len(rest) > 1 else "ko")))
    else: print(__doc__); return 2
    return 0

if __name__ == "__main__": sys.exit(main())
