from fractions import Fraction
def _whole(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0
def cell_executor(inp):
    extra = sorted(str(k) for k in inp if k not in ("subtotal", "pct", "won"))
    if extra:
        raise ValueError("unknown input %s; use subtotal, pct, won" % extra[:3])
    s, pct, won = inp.get("subtotal"), inp.get("pct", 0), inp.get("won", 0)
    if not _whole(s) or not _whole(pct) or not _whole(won):
        raise ValueError("subtotal, pct and won are whole numbers, 0 or more (read the customer's words with the discount step first)")
    if pct > 100:
        raise ValueError("discount_pct must be 0..100")
    disc = int(Fraction(s) * pct / 100) + won
    capped = disc > s
    disc = min(disc, s)
    return {"subtotal": s, "discount": disc, "total": s - disc, "discount_capped": capped}
