import re
from fractions import Fraction
# "4,500원", "2잔", "3인분" as text: one whole number plus at most one unit word. Anything else is refused, never guessed.
_NUM = r"(\d{1,3}(?:,\d{3})+|\d+)"
_UNITS = {"price": "(원)?", "qty": "(잔|개|인분|그릇|공기|병|캔|접시|판|마리|세트|장|컵|인)?"}
def _whole(v, what):
    if isinstance(v, str):
        m = re.fullmatch(_NUM + _UNITS[what], v.replace(" ", ""))
        if not m:
            raise ValueError("%s must be a whole number (like 4500 or 2), not text" % what)
        v = int(m.group(1).replace(",", ""))
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("%s must be a whole number" % what)
    if v < 0 or v != int(v):
        raise ValueError("%s must be a whole number >= 0" % what)
    return int(v)
def _amount(v, what):
    if v is None:
        return 0
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("%s must be a number" % what)
    return v
def cell_executor(inp):
    items = inp.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty list of {price, qty}")
    subtotal = 0
    count = 0
    for it in items:
        if not isinstance(it, dict) or "price" not in it:
            raise ValueError("each item must be an object like {\"price\": 4500, \"qty\": 2}")
        price = _whole(it["price"], "price")
        qty = _whole(it.get("qty", 1), "qty")
        subtotal += price * qty
        count += qty
    pct = _amount(inp.get("discount_pct"), "discount_pct")
    won = _amount(inp.get("discount_won"), "discount_won")
    if pct < 0 or pct > 100 or won < 0:
        raise ValueError("discount_pct must be 0..100 and discount_won >= 0")
    # order is fixed and stated in the contract: percent off the subtotal first (won below 1 dropped), then the fixed won discount
    disc = int(Fraction(subtotal) * Fraction(str(pct)) / 100) + int(won)
    capped = disc > subtotal
    disc = min(disc, subtotal)
    return {"subtotal": subtotal, "discount": disc, "total": subtotal - disc, "item_count": count, "discount_capped": capped}
