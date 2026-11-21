def cell_executor(inp):
    extra = sorted(str(k) for k in inp if k not in ("lines",))
    if extra:
        raise ValueError("unknown input %s; use lines" % extra[:3])
    lines = inp.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ValueError("pass lines: [{name, unit_price, qty}] with whole won and whole counts")
    out = []
    for k, x in enumerate(lines, 1):
        if not isinstance(x, dict) or set(x) - {"name", "unit_price", "qty", "line_total"}:
            raise ValueError("line %d: use name, unit_price, qty" % k)
        p, n = x.get("unit_price"), x.get("qty")
        if isinstance(p, bool) or not isinstance(p, int) or p < 0 or isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise ValueError("line %d: unit_price is whole won (0 or more) and qty a whole count (0 or more)" % k)
        if "line_total" in x and x["line_total"] != p * n:
            raise ValueError("line %d: line_total does not equal unit_price times qty; leave it out and the cell computes it" % k)
        out.append({"name": x.get("name"), "unit_price": p, "qty": n, "line_total": p * n})
    return {"lines": out, "total": sum(x["line_total"] for x in out), "item_count": sum(x["qty"] for x in out)}
