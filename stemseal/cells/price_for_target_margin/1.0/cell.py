def cell_executor(input_data):
    c = input_data.get("cost"); m = input_data.get("margin_pct")
    if not isinstance(c, (int, float)) or c <= 0:
        raise ValueError("cost must be > 0")
    if not isinstance(m, (int, float)) or m < 0 or m >= 100:
        raise ValueError("margin_pct must be in [0, 100)")
    return {"price": round(c / (1 - m / 100))}
