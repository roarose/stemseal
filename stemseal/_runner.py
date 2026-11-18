import json, sys
src = open(sys.argv[1], encoding="utf-8").read()
ns = {"__name__": "cell"}
exec(compile(src, "cell.py", "exec"), ns)
out = []
for x in json.load(sys.stdin):
    try:
        r = ns["cell_executor"](x)
        json.dumps(r)
        out.append({"ok": isinstance(r, dict), "out": r} if isinstance(r, dict) else {"ok": False, "err": "result is not an object"})
    except Exception as e:
        out.append({"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:200])})
sys.stdout.write(json.dumps(out, ensure_ascii=False))
