def cell_executor(inp):
    items = inp.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty list of {price, qty}")
    subtotal = 0
    count = 0
    for it in items:
        if not isinstance(it, dict) or "price" not in it:
            raise ValueError("each item needs price")
        price = it["price"]; qty = it.get("qty", 1)
        if isinstance(price, bool) or isinstance(qty, bool) or not isinstance(price, (int, float)) or not isinstance(qty, (int, float)):
            raise ValueError("price and qty must be numbers")
        if price < 0 or qty < 0 or qty != int(qty) or price != int(price):
            raise ValueError("price and qty must be whole numbers >= 0")
        subtotal += int(price) * int(qty)
        count += int(qty)
    pct = inp.get("discount_pct", 0) or 0
    won = inp.get("discount_won", 0) or 0
    if not isinstance(pct, (int, float)) or not isinstance(won, (int, float)) or pct < 0 or pct > 100 or won < 0:
        raise ValueError("discount_pct 0..100, discount_won >= 0")
    from fractions import Fraction
    disc = int(Fraction(subtotal) * Fraction(str(pct)) / 100) + int(won)
    disc = min(disc, subtotal)
    return {"subtotal": subtotal, "discount": disc, "total": subtotal - disc, "item_count": count}
