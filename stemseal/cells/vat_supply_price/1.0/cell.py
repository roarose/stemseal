from fractions import Fraction
from math import floor

def cell_executor(input_data: dict) -> dict:
    """Split a VAT-included amount into supply price and VAT (Korean practice: VAT truncated below 1 won, supply = total - VAT)."""
    if "total" not in input_data:
        raise ValueError("input must contain 'total' (the VAT-included amount)")
    total = Fraction(str(input_data["total"]))
    pct = Fraction(str(input_data.get("vat_pct", 10)))
    if total < 0:
        raise ValueError("total must be >= 0")
    if pct < 0 or pct >= 100:
        raise ValueError("vat_pct must be in [0, 100)")
    vat = floor(total * pct / (100 + pct))
    supply = total - vat
    supply_out = int(supply) if supply.denominator == 1 else float(supply)
    return {"supply_price": supply_out, "vat": vat}
